from bpy.props import EnumProperty, CollectionProperty, IntProperty, PointerProperty, FloatProperty, StringProperty, \
    BoolProperty
from bpy.types import PropertyGroup, Material

from ...shared.data import bone_filter_mode_items, ExportSpaceMixin, ForwardUpAxisMixin
from ...shared.types import PSX_PG_bone_collection_list_item

empty_set = set()

object_eval_state_items = (
    ('EVALUATED', 'Evaluated', 'Use data from fully evaluated object'),
    ('ORIGINAL', 'Original', 'Use data from original object with no modifiers applied'),
)

export_space_items = [
    ('WORLD', 'World', 'Export in world space'),
    ('ARMATURE', 'Armature', 'Export in armature space'),
]

class PSK_PG_material_list_item(PropertyGroup):
    material: PointerProperty(type=Material)
    index: IntProperty()

class PSK_PG_material_name_list_item(PropertyGroup):
    material_name: StringProperty()
    index: IntProperty()


class PskExportMixin(ExportSpaceMixin, ForwardUpAxisMixin):
    object_eval_state: EnumProperty(
        items=object_eval_state_items,
        name='Object Evaluation State',
        default='EVALUATED'
    )
    should_exclude_hidden_meshes: BoolProperty(
        default=False,
        name='Visible Only',
        description='Export only visible meshes'
    )
    scale: FloatProperty(
        name='Scale',
        default=1.0,
        description='Scale factor to apply to the exported mesh and armature',
        min=0.0001,
        soft_max=100.0
    )
    bone_filter_mode: EnumProperty(
        name='Bone Filter',
        options=empty_set,
        description='',
        items=bone_filter_mode_items,
    )
    bone_collection_list: CollectionProperty(type=PSX_PG_bone_collection_list_item)
    bone_collection_list_index: IntProperty(default=0)
    material_name_list: CollectionProperty(type=PSK_PG_material_name_list_item)
    material_name_list_index: IntProperty(default=0)


class PSK_PG_export(PropertyGroup, PskExportMixin):
    pass


classes = (
    PSK_PG_material_list_item,
    PSK_PG_material_name_list_item,
    PSK_PG_export,
)
