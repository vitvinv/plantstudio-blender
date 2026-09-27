"""PlantStudio-Blender bridge from PdPlant data to Blender meshes and materials.

Uses only stable bpy APIs available in Blender 4.2 LTS and 5.x LTS.
"""

import os
import bpy
import bmesh
import mathutils

from .core.factory import create_plant
from .core.growth import PCT_PROP, pct_for_days
from .core.mesh_buffer import MeshBuffer
from .core.turtle import MeshTurtle
from .core.draw import draw_plant

COLLECTION_NAME = "PlantStudio Plants"


def is_plant(obj):
    """True when obj is a PlantStudio plant object (never in bpy-stubbed tests)."""
    return (obj is not None and getattr(obj, "type", None) == 'MESH'
            and "ps_species" in obj)


def plants():
    """All PlantStudio plant objects under the PlantStudio collection tree.

    Users organize plants into sub-collections (per render status etc.);
    walk the tree so reorganizing never silently detaches a plant from
    the rebuild loop. Only the named collection and its descendants are
    scanned — a plant moved outside it stops being managed on purpose.
    """
    root = bpy.data.collections.get(COLLECTION_NAME)
    if root is None:
        return []
    found = []

    def walk(coll):
        for o in coll.objects:
            if is_plant(o):
                found.append(o)
        for child in coll.children:
            walk(child)

    walk(root)
    return found


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
    # full-growth day (ageAtMaturity) + 0-100% growth mirror of ps_day
    obj["ps_maturity"] = int(getattr(plant.pGeneral, "ageAtMaturity", 100) or 100)
    obj[PCT_PROP] = pct_for_days(day, obj["ps_maturity"])
    # day/seed the mesh was last built at; refresh handlers rebuild when
    # ps_day/ps_seed/ps_pct (possibly keyframed/animated) differ from these
    obj["ps_built_day"] = day
    obj["ps_built_seed"] = seed
    collection.objects.link(obj)
    return obj


# Meshes swapped out by rebuilds wait here for the idle-timer purge;
# names (not references) so the list never keeps a datablock alive.
_pending_purge = []


def _schedule_purge():
    """Start the purge timer once (noop under bpy-stubbed tests)."""
    try:
        timers = bpy.app.timers
        if getattr(timers, "is_registered", lambda f: False)(_purge_pending_meshes):
            return
        timers.register(_purge_pending_meshes, first_interval=0.5)
    except Exception:
        pass  # stubbed bpy without timers: purge on save handles orphans


def _purge_pending_meshes():
    """Free rebuild-orphaned meshes when nothing holds render references."""
    try:
        rendering = bpy.app.is_job_running("RENDER")
    except AttributeError:  # older Blender / bpy-stubbed tests
        rendering = False
    if rendering:
        return 1.0  # retry after the job finishes
    for name in list(_pending_purge):
        _pending_purge.remove(name)
        mesh = bpy.data.meshes.get(name)
        if mesh is None:
            continue  # already gone (purged on save / file change / undo)
        try:
            if mesh.users == 1 and mesh.use_fake_user:
                mesh.use_fake_user = False  # orphaned empty-mesh holder
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        except (ReferenceError, RuntimeError):
            pass  # freed elsewhere mid-loop; save-time purge catches strays
    return None  # unregister; the next rebuild re-registers


def rebuild_plant_mesh(obj, plant, fast=False):
    """
    Rebuild the mesh of an existing plant object in place (no new object).

    The object's own mesh datablock is rewritten (clear_geometry +
    from_pydata): no obj.data assignment and no temp meshes. Swapping
    obj.data inside frame_change_post during an F12 render fires
    rna_Object_data_update -> DEG_relations_tag_update while the render
    job's depsgraph is mid-rebuild and crashes Blender (access violation
    in graph_id_tag_update; a fresh-datablock swap was the crash in
    both render crash reports). A geometry-only rewrite is what the
    render loop re-evaluates safely, and it leaves no orphans behind.

    fast=True: lower-detail draw (fewer stem divisions) for realtime preview.
    """
    buffer = MeshBuffer()
    turtle = MeshTurtle(buffer)
    turtle.setScale_pixelsPerMm(0.001)  # mm -> meters
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
    mesh = obj.data
    fresh = mesh is None or mesh.users != 1  # shared/missing data: swap path
    if fresh:
        mesh = bpy.data.meshes.new(name + "_tmp")
    else:
        mesh.clear_geometry()

    if data["faces"]:
        mesh.from_pydata(data["vertices"], [], data["faces"])
        mesh.update()
    else:
        mesh.update()
        if not fresh:
            mesh.use_fake_user = False  # owned mesh: keep purgeable

    # material slots: sync incrementally (assign/pop only on change) —
    # per-frame clear+append churns depsgraph updates during renders
    color_to_slot = {}
    indices = []
    desired = []
    for color in data["face_colors"]:
        mat_name = f"{name}_mat_{color[0]}_{color[1]}_{color[2]}"
        if mat_name not in color_to_slot:
            mat = make_material(mat_name, color)
            color_to_slot[mat_name] = len(desired)
            desired.append(mat)
        indices.append(color_to_slot[mat_name])
    while len(mesh.materials) > len(desired):
        mesh.materials.pop()
    for i, mat in enumerate(desired):
        if i >= len(mesh.materials):
            mesh.materials.append(mat)
        elif mesh.materials[i] != mat:
            mesh.materials[i] = mat
    # empty write into foreach_set corrupts mesh memory (crash on undo) —
    # polygons count is the truth (face indices may have welded to zero)
    if indices and len(mesh.polygons) == len(indices):
        mesh.polygons.foreach_set("material_index", indices)

    if fresh:  # fallback swap path (object shared/lost its mesh)
        old = obj.data
        obj.data = mesh
        # Defer the free to an idle timer: freeing from inside
        # frame_change_post while a render job — or an EEVEE viewport in
        # rendered shading, which is NOT a RENDER job — still references
        # it leaves dangling render data behind; the timer also reclaims
        # fake-user temp meshes (file bloat).
        if old is not None:
            _pending_purge.append(old.name)
            _schedule_purge()

    return obj
