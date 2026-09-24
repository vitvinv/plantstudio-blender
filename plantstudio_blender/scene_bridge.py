"""PlantStudio-Blender bridge from PdPlant data to Blender meshes and materials.

Uses only stable bpy APIs available in Blender 4.2 LTS and 5.x LTS.
"""

import os
import bpy
import bmesh
import mathutils

from .core.factory import create_plant
from .core.mesh_buffer import MeshBuffer
from .core.turtle import MeshTurtle
from .core.draw import draw_plant

COLLECTION_NAME = "PlantStudio Plants"

# Preview floor on pipe radii (meters). The original clamped its 2D pen to
# >=1 pixel, so hair-thin petioles (0.06-0.5mm) stayed visible; in 3D they
# vanish and leaf blades look detached from branches. 1mm radius matches the
# original's pen at its default zoom. Set turtle.min_pipe_radius = 0 for
# faithful radii (tests/tools do).
MIN_PREVIEW_PIPE_RADIUS = 0.001


def is_plant(obj):
    """True when obj is a PlantStudio plant object (never in bpy-stubbed tests)."""
    return (obj is not None and getattr(obj, "type", None) == 'MESH'
            and "ps_species" in obj)


def plants():
    """All PlantStudio plant objects in the scene collection."""
    coll = bpy.data.collections.get(COLLECTION_NAME)
    return [o for o in coll.objects if is_plant(o)] if coll else []


def ensure_collection(name, parent=None):
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        # re-fetch by name: linking into the scene may reallocate and the
        # fresh data-block reference can go stale (crash on undo)
        if bpy.context.scene.collection.children.get(name) is None:
            bpy.context.scene.collection.children.link(coll)
    return coll


def color_to_rgba(color, alpha=1.0):
    """PlantStudio 0-255 color -> (r, g, b, a) 0-1."""
    r, g, b = (float(c) / 255.0 for c in color[:3])
    return (r, g, b, alpha)


def make_material(name, color):
    """Create a Blender material from a PlantStudio color (if not existing)."""
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = color_to_rgba(color)
        bsdf.inputs["Roughness"].default_value = 0.6
    return mat


def orient_vertices(vertices):
    """PlantStudio grows along +X (turtle forward). Blender's up is +Z.

    Rotate -90° about Y: (x, y, z) -> (-z, y, x). This makes plants
    stand upright in Blender and exports correctly via glTF (Y-up).
    """
    return [(-z, y, x) for (x, y, z) in vertices]


def build_mesh_object(plant, name):
    """Build a bpy mesh object from a grown plant."""
    buffer = MeshBuffer()
    turtle = MeshTurtle(buffer)
    turtle.setScale_pixelsPerMm(0.001)  # mm -> meters
    # original drew sub-mm petioles as >=1-pixel-wide 2D lines; in 3D they
    # vanish and leaf blades look detached from branches
    turtle.min_pipe_radius = MIN_PREVIEW_PIPE_RADIUS
    draw_plant(plant, turtle)
    data = buffer.to_mesh_data()
    data["vertices"] = orient_vertices(data["vertices"])

    mesh = bpy.data.meshes.new(name)
    # guard: from_pydata with zero polygons leaves the mesh in a state that
    # Blender's undo cannot serialize — crash on the next Ctrl+Z (age-0
    # plants legitimately draw nothing)
    if data["faces"]:
        mesh.from_pydata(data["vertices"], [], data["faces"])
        mesh.update()
    else:
        mesh.update()
        mesh.use_fake_user = True

    # materials: one per unique color (slots must exist before foreach_set)
    color_to_mat = {}
    indices = []
    for color in data["face_colors"]:
        mat_name = f"{name}_mat_{color[0]}_{color[1]}_{color[2]}"
        if mat_name not in color_to_mat:
            mat = make_material(mat_name, color)
            mesh.materials.append(mat)
            color_to_mat[mat_name] = len(mesh.materials) - 1
        indices.append(color_to_mat[mat_name])
    mesh.polygons.foreach_set("material_index", indices)

    obj = bpy.data.objects.new(name, mesh)
    return obj


def plant_object_name(species, seed, day=None):
    return f"{species.replace(' ', '_')}_{seed}"


def build_plant_object(species, seed, day, collection, tdo_library):
    """Grow + build + link a plant object. Returns the bpy object."""
    plant = create_plant(species, seed=seed, tdo_library=tdo_library)
    plant.growTo(day)
    day = plant.age  # growTo clamps to ageAtMaturity (matches original)
    sp_name = getattr(species, "name", "plant")
    name = plant_object_name(sp_name, seed, day)
    obj = build_mesh_object(plant, name)
    # store metadata
    obj["ps_species"] = sp_name
    obj["ps_seed"] = seed
    obj["ps_day"] = day
    # day/seed the mesh was last built at; refresh handlers rebuild when
    # ps_day/ps_seed (possibly keyframed/animated) differ from these
    obj["ps_built_day"] = day
    obj["ps_built_seed"] = seed
    collection.objects.link(obj)
    return obj


def rebuild_plant_mesh(obj, plant, fast=False):
    """
    Rebuild the mesh of an existing plant object in place (no new object).

    fast=True: lower-detail draw (fewer stem divisions) for realtime preview.
    """
    buffer = MeshBuffer()
    turtle = MeshTurtle(buffer)
    turtle.setScale_pixelsPerMm(0.001)  # mm -> meters
    turtle.min_pipe_radius = MIN_PREVIEW_PIPE_RADIUS  # see build_mesh_object
    if fast:
        # realtime preview: 1 division per stem, low pipe faces
        try:
            plant.pGeneral.lineDivisions = 1
        except AttributeError:
            pass
    draw_plant(plant, turtle)
    data = buffer.to_mesh_data()
    data["vertices"] = orient_vertices(data["vertices"])

    # draw BEFORE clearing: a rebuild that raises mid-draw must leave the
    # previous (correct) mesh, not an empty (vanished) plant
    name = obj.name
    new_mesh = bpy.data.meshes.new(name + "_tmp")
    if data["faces"]:
        new_mesh.from_pydata(data["vertices"], [], data["faces"])
        new_mesh.update()
    else:
        new_mesh.update()
        new_mesh.use_fake_user = True

    # rebuild material slots to match current colors (slots before foreach_set)
    color_to_slot = {}
    mesh = new_mesh
    mesh.materials.clear()
    indices = []
    for color in data["face_colors"]:
        mat_name = f"{name}_mat_{color[0]}_{color[1]}_{color[2]}"
        if mat_name not in color_to_slot:
            mat = make_material(mat_name, color)
            mesh.materials.append(mat)
            color_to_slot[mat_name] = len(mesh.materials) - 1
        indices.append(color_to_slot[mat_name])
    # empty write into foreach_set corrupts mesh memory (crash on undo) —
    # polygons count is the truth (face indices may have welded to zero)
    if indices and len(mesh.polygons) == len(indices):
        mesh.polygons.foreach_set("material_index", indices)

    # swap in the finished mesh only after it is fully built; the object
    # keeps its previous mesh if anything above raised (no vanishing plants)
    old = obj.data
    obj.data = new_mesh
    if old.users == 0:
        bpy.data.meshes.remove(old)

    return obj
