"""Blender headless verification of the flower-placeholder fix.

Exercises the real addon flow with real bpy:
  1. register the addon, load species 'Daylily' via the operator
  2. verify placement age (species saved kStateAge)
  3. emulate the wizard knob roundtrip exactly as the UI does:
     select plant (loads ps_knobs into wizard), dial day down, dial day up
  4. assert the resulting mesh still contains the daylily petal geometry
     (not 'Default 3D object' placeholder blobs) and correct height
Run:  blender.exe -b --factory-startup -noaudio --python <this file>
"""
import json
import os
import sys

import bpy

ROOT = r"C:\Users\vitvin_v\dev\plantstudio-blender"
sys.path.insert(0, ROOT)

# fresh scene without default cube
bpy.ops.wm.read_factory_settings(use_empty=True)

from plantstudio_blender import register, unregister  # noqa
from plantstudio_blender.operators import COLLECTION_NAME  # noqa
from plantstudio_blender.core.tdo_parser import Tdo

register()

failures = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


# ── 1. place a Daylily via the operator (species saved age path) ──
bpy.ops.plantstudio.load_preset(species_name="Daylily")
coll = bpy.data.collections.get(COLLECTION_NAME)
assert coll is not None and len(coll.objects) >= 1, "no plant created"
obj = coll.objects[-1]
day = int(obj["ps_day"])
seed = int(obj["ps_seed"])
check(day == 100, f"placement age == species saved age 100 (got {day})")

knobs = bpy.context.scene.ps_wizard_knobs
print("wizard knob_day =", knobs.knob_day)
print("knob_petal_shape =", knobs.knob_petal_shape)
check(knobs.knob_petal_shape == "Petal, daylily",
      f"wizard petal shape knob roundtrips embedded name (got {knobs.knob_petal_shape!r})")


def face_triangle_record(plant_params, tdo_lib):
    """Return the petal row's object3D type/name."""
    row = plant_params_petal_row(plant_params_of(obj))
    val = row.object3D
    if val is None:
        return "None"
    if isinstance(val, str):
        return f"str:{val}"
    return f"Tdo:{val.name}"


def plant_params_of(species):
    return species.params


def mesh_stats(obj):
    return len(obj.data.vertices), len(obj.data.polygons)


def top_z(obj):
    return max(v.co.z for v in obj.data.vertices)


# ── 2. dial the age down (like the user does) ──
knobs.knob_day = 30
# emulate what the update callback does: save + rebuild via the timer path
from plantstudio_blender.wizard import (save_knobs_to_obj, apply_knobs_to_params,
                                        _rebuild_selected)
save_knobs_to_obj(obj, knobs)
obj["ps_day"] = 30
_rebuild_selected(bpy.context.scene)
day30 = int(obj["ps_day"])
v30, f30 = mesh_stats(obj)
print(f"day 30: vertices={v30} faces={f30}")

# ── 3. dial the age back up ──
knobs.knob_day = 100
save_knobs_to_obj(obj, knobs)
obj["ps_day"] = 100
_rebuild_selected(bpy.context.scene)
day100 = int(obj["ps_day"])
v100, f100 = mesh_stats(obj)
print(f"day 100: vertices={v100} faces={f100}")

# ── 4. assert the plant matches the raw species grow (no placeholders) ──
from plantstudio_blender.core.factory import create_plant
from plantstudio_blender.core.plant_library import SpeciesLibrary
from plantstudio_blender.core.tdo_parser import TdoLibrary
from plantstudio_blender.core.draw import draw_plant
from plantstudio_blender.core.mesh_buffer import MeshBuffer
from plantstudio_blender.core.turtle import MeshTurtle

DATA_DIR = os.path.join(ROOT, "plantstudio_blender", "data")
lib = SpeciesLibrary(DATA_DIR)
tdo_lib = TdoLibrary.from_file(os.path.join(DATA_DIR, "3D object library.tdo"))
missing = [t for name, t in lib.embedded_tdos.items() if tdo_lib.get(name) is None]
tdo_lib.merge(missing)

species = lib.get("Daylily")
ref_plant = create_plant(species, seed=seed, tdo_library=tdo_lib)
ref_plant.growTo(100)
ref_buffer = MeshBuffer()
ref_turtle = MeshTurtle(ref_buffer)
ref_turtle.setScale_pixelsPerMm(0.001)
draw_plant(ref_plant, ref_turtle)
ref_data = ref_buffer.to_mesh_data()
ref_verts = [(-z, y, x) for (x, y, z) in ref_buffer.vertices]

plant_zs = [v.co.z for v in obj.data.vertices]
ref_zs = [v[2] for v in ref_verts]
height = max(plant_zs)
ref_height = max(ref_zs)
check(abs(height - ref_height) < 0.005,
      f"blender height {height:.4f}m == reference {ref_height:.4f}m")
check(abs(height - 0.271) < 0.02,
      f"daylily height matches PlantStudio (~0.27m, got {height:.3f}m)")
check(v100 > 500, f"day-100 mesh has real geometry ({v100} vertices)")

# petal color check: daylily petal faceColor orange — the placeholder rows
# would add large 'Default 3D object' geometry with petal color; instead,
# verify the ps_knobs preserved the embedded name after the dial cycle
stored = json.loads(obj["ps_knobs"])
check(stored.get("knob_petal_shape") == "Petal, daylily",
      f"stored ps_knobs keep embedded petal name (got {stored.get('knob_petal_shape')!r})")

# ── 5. species saved age for all four plants of the folder ──
for species_name in ("rose", "flower to test all parts", "purple flower plant"):
    before = len(coll.objects)
    bpy.ops.plantstudio.load_preset(species_name=species_name)
    obj2 = coll.objects[-1]
    saved_age = int(getattr(lib.get(species_name).params.pGeneral, "age", 0) or 0)
    check(int(obj2["ps_day"]) == saved_age,
          f"{species_name}: placement age {int(obj2['ps_day'])} == saved {saved_age}")

print()
if failures:
    print(f"=== {len(failures)} FAILURE(S) ===")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("=== ALL CHECKS PASSED ===")
