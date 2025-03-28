from typing import List, Iterable, cast, Optional

import bpy
from bpy.props import CollectionProperty
from bpy.types import AnimData, Object
from bpy.types import Armature
from mathutils import Matrix

from .data import get_coordinate_system_transform


def rgb_to_srgb(c: float):
    if c > 0.0031308:
        return 1.055 * (pow(c, (1.0 / 2.4))) - 0.055
    else:
        return 12.92 * c


def get_nla_strips_in_frame_range(animation_data: AnimData, frame_min: float, frame_max: float):
    if animation_data is None:
        return
    for nla_track in animation_data.nla_tracks:
        if nla_track.mute:
            continue
        for strip in nla_track.strips:
            if (strip.frame_start < frame_min and strip.frame_end > frame_max) or \
                    (frame_min <= strip.frame_start < frame_max) or \
                    (frame_min < strip.frame_end <= frame_max):
                yield strip


def populate_bone_collection_list(armature_object: Object, bone_collection_list: CollectionProperty) -> None:
    """
    Updates the bone collections collection.

    Bone collection selections are preserved between updates unless none of the groups were previously selected;
    otherwise, all collections are selected by default.
    """
    has_selected_collections = any([g.is_selected for g in bone_collection_list])
    unassigned_collection_is_selected, selected_assigned_collection_names = True, []

    if armature_object is None:
        return

    if has_selected_collections:
        # Preserve group selections before clearing the list.
        # We handle selections for the unassigned group separately to cover the edge case
        # where there might be an actual group with 'Unassigned' as its name.
        unassigned_collection_idx, unassigned_collection_is_selected = next(iter([
            (i, g.is_selected) for i, g in enumerate(bone_collection_list) if g.index == -1]), (-1, False))

        selected_assigned_collection_names = [
            g.name for i, g in enumerate(bone_collection_list) if i != unassigned_collection_idx and g.is_selected]

    bone_collection_list.clear()

    armature = cast(Armature, armature_object.data)

    if armature is None:
        return

    item = bone_collection_list.add()
    item.name = 'Unassigned'
    item.index = -1
    # Count the number of bones without an assigned bone collection
    item.count = sum(map(lambda bone: 1 if len(bone.collections) == 0 else 0, armature.bones))
    item.is_selected = unassigned_collection_is_selected

    for bone_collection_index, bone_collection in enumerate(armature.collections_all):
        item = bone_collection_list.add()
        item.name = bone_collection.name
        item.index = bone_collection_index
        item.count = len(bone_collection.bones)
        item.is_selected = bone_collection.name in selected_assigned_collection_names if has_selected_collections else True


def get_export_bone_names(armature_object: Object, bone_filter_mode: str, bone_collection_indices: Iterable[int]) -> List[str]:
    """
    Returns a sorted list of bone indices that should be exported for the given bone filter mode and bone collections.

    Note that the ancestors of bones within the bone collections will also be present in the returned list.

    :param armature_object: Blender object with type 'ARMATURE'
    :param bone_filter_mode: One of ['ALL', 'BONE_COLLECTIONS']
    :param bone_collection_indices: A list of bone collection indices to export.
    :return: A sorted list of bone indices that should be exported.
    """
    if armature_object is None or armature_object.type != 'ARMATURE':
        raise ValueError('An armature object must be supplied')

    armature_data = cast(Armature, armature_object.data)
    bones = armature_data.bones
    bone_names = [x.name for x in bones]

    # Get a list of the bone indices that we are explicitly including.
    bone_index_stack = []
    is_exporting_unassigned_bone_collections = -1 in bone_collection_indices
    bone_collections = list(armature_data.collections_all)

    for bone_index, bone in enumerate(bones):
        # Check if this bone is in any of the collections in the bone collection indices list.
        this_bone_collection_indices = set(bone_collections.index(x) for x in bone.collections)
        is_in_exported_bone_collections = len(set(bone_collection_indices).intersection(this_bone_collection_indices)) > 0

        if bone_filter_mode == 'ALL' or \
                (len(bone.collections) == 0 and is_exporting_unassigned_bone_collections) or \
                is_in_exported_bone_collections:
            bone_index_stack.append((bone_index, None))

    # For each bone that is explicitly being added, recursively walk up the hierarchy and ensure that all of
    # those ancestor bone indices are also in the list.
    bone_indices = dict()
    while len(bone_index_stack) > 0:
        bone_index, instigator_bone_index = bone_index_stack.pop()
        bone = bones[bone_index]
        if bone.parent is not None:
            parent_bone_index = bone_names.index(bone.parent.name)
            if parent_bone_index not in bone_indices:
                bone_index_stack.append((parent_bone_index, bone_index))
        bone_indices[bone_index] = instigator_bone_index

    # Sort the bone index list in-place.
    bone_indices = [(x[0], x[1]) for x in bone_indices.items()]
    bone_indices.sort(key=lambda x: x[0])

    # Split out the bone indices and the instigator bone names into separate lists.
    # We use the bone names for the return values because the bone name is a more universal way of referencing them.
    # For example, users of this function may modify bone lists, which would invalidate the indices and require an
    # index mapping scheme to resolve it. Using strings is more comfy and results in less code downstream.
    instigator_bone_names = [bones[x[1]].name if x[1] is not None else None for x in bone_indices]
    bone_names = [bones[x[0]].name for x in bone_indices]

    # Ensure that the hierarchy we are sending back has a single root bone.
    bone_indices = [x[0] for x in bone_indices]
    root_bones = [bones[bone_index] for bone_index in bone_indices if bones[bone_index].parent is None]
    if len(root_bones) > 1:
        # There is more than one root bone.
        # Print out why each root bone was included by linking it to one of the explicitly included bones.
        root_bone_names = [bone.name for bone in root_bones]
        for root_bone_name in root_bone_names:
            bone_name = root_bone_name
            while True:
                # Traverse the instigator chain until the end to find the true instigator bone.
                # TODO: in future, it would be preferential to have a readout of *all* instigator bones.
                instigator_bone_name = instigator_bone_names[bone_names.index(bone_name)]
                if instigator_bone_name is None:
                    print(f'Root bone "{root_bone_name}" was included because {bone_name} was marked for export')
                    break
                bone_name = instigator_bone_name

        raise RuntimeError('Exported bone hierarchy must have a single root bone.\n'
                           f'The bone hierarchy marked for export has {len(root_bones)} root bones: {root_bone_names}.\n'
                           f'Additional debugging information has been written to the console.')

    return bone_names


def is_bdk_addon_loaded() -> bool:
    return 'bdk' in dir(bpy.ops)


def convert_blender_bones_to_psx_bones(
        bones: List[bpy.types.Bone],
        bone_class: type,
        export_space: str = 'WORLD',        # perhaps export space should just be a transform matrix, since the below is not actually used unless we're using WORLD space.
        armature_object_matrix_world: Matrix = Matrix.Identity(4),
        scale = 1.0,
        forward_axis: str = 'X',
        up_axis: str = 'Z'
) -> Iterable[type]:
    '''
    Function that converts a Blender bone list into a bone list that
    @param bones:
    @return:
    '''
    scale_matrix = Matrix.Scale(scale, 4)

    coordinate_system_transform = get_coordinate_system_transform(forward_axis, up_axis)
    coordinate_system_default_rotation = coordinate_system_transform.to_quaternion()

    psx_bones = []
    for bone in bones:
        psx_bone = bone_class()

        try:
            psx_bone.name = bytes(bone.name, encoding='windows-1252')
        except UnicodeEncodeError:
            raise RuntimeError(
                f'Bone name "{bone.name}" contains characters that cannot be encoded in the Windows-1252 codepage')

        # TODO: flags & children_count should be initialized to zero anyways, so we can probably remove these lines?
        psx_bone.flags = 0
        psx_bone.children_count = 0

        try:
            parent_index = bones.index(bone.parent)
            psx_bone.parent_index = parent_index
            psx_bones[parent_index].children_count += 1
        except ValueError:
            psx_bone.parent_index = 0

        if bone.parent is not None:
            rotation = bone.matrix.to_quaternion().conjugated()
            inverse_parent_rotation = bone.parent.matrix.to_quaternion().inverted()
            parent_head = inverse_parent_rotation @ bone.parent.head
            parent_tail = inverse_parent_rotation @ bone.parent.tail
            location = (parent_tail - parent_head) + bone.head
        else:
            def get_armature_local_matrix():
                match export_space:
                    case 'WORLD':
                        return armature_object_matrix_world
                    case 'ARMATURE':
                        return Matrix.Identity(4)
                    case _:
                        raise ValueError(f'Invalid export space: {export_space}')

            armature_local_matrix = get_armature_local_matrix()
            location = armature_local_matrix @ bone.head
            location = coordinate_system_transform @ location
            bone_rotation = bone.matrix.to_quaternion().conjugated()
            local_rotation = armature_local_matrix.to_3x3().to_quaternion().conjugated()
            rotation = bone_rotation @ local_rotation
            rotation.conjugate()
            rotation = coordinate_system_default_rotation @ rotation

        location = scale_matrix @ location

        # If the armature object has been scaled, we need to scale the bone's location to match.
        _, _, armature_object_scale = armature_object_matrix_world.decompose()
        location.x *= armature_object_scale.x
        location.y *= armature_object_scale.y
        location.z *= armature_object_scale.z

        psx_bone.location.x = location.x
        psx_bone.location.y = location.y
        psx_bone.location.z = location.z

        psx_bone.rotation.w = rotation.w
        psx_bone.rotation.x = rotation.x
        psx_bone.rotation.y = rotation.y
        psx_bone.rotation.z = rotation.z

        psx_bones.append(psx_bone)

    return psx_bones
