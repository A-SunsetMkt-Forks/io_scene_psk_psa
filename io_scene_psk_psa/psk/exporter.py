from typing import Type

from bpy.props import BoolProperty, StringProperty, CollectionProperty, IntProperty, EnumProperty
from bpy.types import Operator, PropertyGroup, UIList
from bpy_extras.io_utils import ExportHelper

from .builder import build_psk, PskBuildOptions, get_psk_input_objects
from .data import *
from ..helpers import populate_bone_group_list
from ..types import BoneGroupListItem

MAX_WEDGE_COUNT = 65536
MAX_POINT_COUNT = 4294967296
MAX_BONE_COUNT = 256
MAX_MATERIAL_COUNT = 256


def _write_section(fp, name: bytes, data_type: Type[Structure] = None, data: list = None):
    section = Section()
    section.name = name
    if data_type is not None and data is not None:
        section.data_size = sizeof(data_type)
        section.data_count = len(data)
    fp.write(section)
    if data is not None:
        for datum in data:
            fp.write(datum)


def export_psk(psk: Psk, path: str):
    if len(psk.wedges) > MAX_WEDGE_COUNT:
        raise RuntimeError(f'Number of wedges ({len(psk.wedges)}) exceeds limit of {MAX_WEDGE_COUNT}')
    if len(psk.points) > MAX_POINT_COUNT:
        raise RuntimeError(f'Numbers of vertices ({len(psk.points)}) exceeds limit of {MAX_POINT_COUNT}')
    if len(psk.materials) > MAX_MATERIAL_COUNT:
        raise RuntimeError(f'Number of materials ({len(psk.materials)}) exceeds limit of {MAX_MATERIAL_COUNT}')
    if len(psk.bones) > MAX_BONE_COUNT:
        raise RuntimeError(f'Number of bones ({len(psk.bones)}) exceeds limit of {MAX_BONE_COUNT}')
    elif len(psk.bones) == 0:
        raise RuntimeError(f'At least one bone must be marked for export')

    with open(path, 'wb') as fp:
        _write_section(fp, b'ACTRHEAD')
        _write_section(fp, b'PNTS0000', Vector3, psk.points)

        wedges = []
        for index, w in enumerate(psk.wedges):
            wedge = Psk.Wedge16()
            wedge.material_index = w.material_index
            wedge.u = w.u
            wedge.v = w.v
            wedge.point_index = w.point_index
            wedges.append(wedge)

        _write_section(fp, b'VTXW0000', Psk.Wedge16, wedges)
        _write_section(fp, b'FACE0000', Psk.Face, psk.faces)
        _write_section(fp, b'MATT0000', Psk.Material, psk.materials)
        _write_section(fp, b'REFSKELT', Psk.Bone, psk.bones)
        _write_section(fp, b'RAWWEIGHTS', Psk.Weight, psk.weights)


def is_bone_filter_mode_item_available(context, identifier):
    input_objects = get_psk_input_objects(context)
    armature_object = input_objects.armature_object
    if identifier == 'BONE_GROUPS':
        if not armature_object or not armature_object.pose or not armature_object.pose.bone_groups:
            return False
    # else if... you can set up other conditions if you add more options
    return True


class PSK_UL_MaterialList(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row()
        row.label(text=str(getattr(item, 'material_name')), icon='MATERIAL')


class MaterialListItem(PropertyGroup):
    material_name: StringProperty()
    index: IntProperty()

    @property
    def name(self):
        return self.material_name


def populate_material_list(mesh_objects, material_list):
    material_list.clear()

    material_names = []
    for mesh_object in mesh_objects:
        for i, material in enumerate(mesh_object.data.materials):
            # TODO: put this in the poll arg?
            if material is None:
                raise RuntimeError('Material cannot be empty (index ' + str(i) + ')')
            if material.name not in material_names:
                material_names.append(material.name)

    for index, material_name in enumerate(material_names):
        m = material_list.add()
        m.material_name = material_name
        m.index = index


class PskMaterialListItemMoveUp(Operator):
    bl_idname = 'psk_export.material_list_item_move_up'
    bl_label = 'Move Up'
    bl_options = {'INTERNAL'}
    bl_description = 'Move the selected material up one slot'

    @classmethod
    def poll(cls, context):
        pg = getattr(context.scene, 'psk_export')
        return pg.material_list_index > 0

    def execute(self, context):
        pg = getattr(context.scene, 'psk_export')
        pg.material_list.move(pg.material_list_index, pg.material_list_index - 1)
        pg.material_list_index -= 1
        return {"FINISHED"}


class PskMaterialListItemMoveDown(Operator):
    bl_idname = 'psk_export.material_list_item_move_down'
    bl_label = 'Move Down'
    bl_options = {'INTERNAL'}
    bl_description = 'Move the selected material down one slot'

    @classmethod
    def poll(cls, context):
        pg = getattr(context.scene, 'psk_export')
        return pg.material_list_index < len(pg.material_list) - 1

    def execute(self, context):
        pg = getattr(context.scene, 'psk_export')
        pg.material_list.move(pg.material_list_index, pg.material_list_index + 1)
        pg.material_list_index += 1
        return {"FINISHED"}


class PskExportOperator(Operator, ExportHelper):
    bl_idname = 'export.psk'
    bl_label = 'Export'
    bl_options = {'INTERNAL', 'UNDO'}
    __doc__ = 'Export mesh and armature to PSK'
    filename_ext = '.psk'
    filter_glob: StringProperty(default='*.psk', options={'HIDDEN'})

    filepath: StringProperty(
        name='File Path',
        description='File path used for exporting the PSK file',
        maxlen=1024,
        default='')

    def invoke(self, context, event):
        try:
            input_objects = get_psk_input_objects(context)
        except RuntimeError as e:
            self.report({'ERROR_INVALID_CONTEXT'}, str(e))
            return {'CANCELLED'}

        pg = getattr(context.scene, 'psk_export')

        # Populate bone groups list.
        populate_bone_group_list(input_objects.armature_object, pg.bone_group_list)

        try:
            populate_material_list(input_objects.mesh_objects, pg.material_list)
        except RuntimeError as e:
            self.report({'ERROR_INVALID_CONTEXT'}, str(e))
            return {'CANCELLED'}

        context.window_manager.fileselect_add(self)

        return {'RUNNING_MODAL'}

    @classmethod
    def poll(cls, context):
        try:
            get_psk_input_objects(context)
        except RuntimeError as e:
            cls.poll_message_set(str(e))
            return False
        return True

    def draw(self, context):
        layout = self.layout
        pg = getattr(context.scene, 'psk_export')

        layout.prop(pg, 'use_raw_mesh_data')

        # BONES
        layout.label(text='Bones', icon='BONE_DATA')
        bone_filter_mode_items = pg.bl_rna.properties['bone_filter_mode'].enum_items_static
        row = layout.row(align=True)
        for item in bone_filter_mode_items:
            identifier = item.identifier
            item_layout = row.row(align=True)
            item_layout.prop_enum(pg, 'bone_filter_mode', item.identifier)
            item_layout.enabled = is_bone_filter_mode_item_available(context, identifier)

        if pg.bone_filter_mode == 'BONE_GROUPS':
            row = layout.row()
            rows = max(3, min(len(pg.bone_group_list), 10))
            row.template_list('PSX_UL_BoneGroupList', '', pg, 'bone_group_list', pg, 'bone_group_list_index', rows=rows)

        layout.separator()

        # MATERIALS
        layout.label(text='Materials', icon='MATERIAL')
        row = layout.row()
        rows = max(3, min(len(pg.bone_group_list), 10))
        row.template_list('PSK_UL_MaterialList', '', pg, 'material_list', pg, 'material_list_index', rows=rows)
        col = row.column(align=True)
        col.operator(PskMaterialListItemMoveUp.bl_idname, text='', icon='TRIA_UP')
        col.operator(PskMaterialListItemMoveDown.bl_idname, text='', icon='TRIA_DOWN')

        layout.separator()

        layout.prop(pg, 'should_ignore_bone_name_restrictions')

    def execute(self, context):
        pg = context.scene.psk_export
        options = PskBuildOptions()
        options.bone_filter_mode = pg.bone_filter_mode
        options.bone_group_indices = [x.index for x in pg.bone_group_list if x.is_selected]
        options.use_raw_mesh_data = pg.use_raw_mesh_data
        options.material_names = [m.material_name for m in pg.material_list]
        options.should_ignore_bone_name_restrictions = pg.should_ignore_bone_name_restrictions

        try:
            psk = build_psk(context, options)
            export_psk(psk, self.filepath)
            self.report({'INFO'}, f'PSK export successful')
        except RuntimeError as e:
            self.report({'ERROR_INVALID_CONTEXT'}, str(e))
            return {'CANCELLED'}
        return {'FINISHED'}


class PskExportPropertyGroup(PropertyGroup):
    bone_filter_mode: EnumProperty(
        name='Bone Filter',
        options=set(),
        description='',
        items=(
            ('ALL', 'All', 'All bones will be exported.'),
            ('BONE_GROUPS', 'Bone Groups',
             'Only bones belonging to the selected bone groups and their ancestors will be exported.')
        )
    )
    bone_group_list: CollectionProperty(type=BoneGroupListItem)
    bone_group_list_index: IntProperty(default=0)
    use_raw_mesh_data: BoolProperty(default=False, name='Raw Mesh Data', description='No modifiers will be evaluated as part of the exported mesh')
    material_list: CollectionProperty(type=MaterialListItem)
    material_list_index: IntProperty(default=0)
    should_ignore_bone_name_restrictions: BoolProperty(
        default=False,
        name='Ignore Bone Name Restrictions',
        description='Bone names restrictions will be ignored. Note that bone names without properly formatted names '
                    'cannot be referenced in scripts'
    )


classes = (
    MaterialListItem,
    PSK_UL_MaterialList,
    PskMaterialListItemMoveUp,
    PskMaterialListItemMoveDown,
    PskExportOperator,
    PskExportPropertyGroup,
)
