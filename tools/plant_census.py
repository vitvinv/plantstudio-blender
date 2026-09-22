"""Part census — headless, deterministic per-part geometry metrics.

Grows species × age with a fixed seed, draws each plant exactly once (drawing
consumes the plant's RNG — see tests/test_shape_roundtrip.py) and aggregates
the mesh buffer per plant-part export type (the original PlantStudio
kExportPart* taxonomy, see core/draw.py).

Metrics per part type:
- face count, total triangle area (mm²), world bbox (mm)
- stem pipes: segment count, total length (mm), mean radius (mm)
- TDO instances: instance count, triangle count, mean scale,
  ring radius = mean distance of instance centroids from the draw origin
  (for radially arranged rows this is the petal ring radius) (mm)

Whole plant: bbox height/width/depth (mm; height is the buffer +X axis, which
scene_bridge maps to Blender Z), face/vertex counts, live biomass per part
class.

Output: JSON (diffable baseline) and, with --table, a human-readable report.

Examples:
    python tools/plant_census.py --all --ages 30 100 --out plant_census.json
    python tools/plant_census.py --species Daylily --ages 100 --table
"""

import argparse
import json
import math
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from plantstudio_blender.core.draw import draw_plant, PART_NAMES, kExportPartLast
from plantstudio_blender.core.factory import create_plant
from plantstudio_blender.core.mesh_buffer import MeshBuffer
from plantstudio_blender.core.plant_library import SpeciesLibrary
from plantstudio_blender.core.tdo_parser import TdoLibrary
from plantstudio_blender.core.turtle import MeshTurtle

DATA_DIR = os.path.join(ROOT, "plantstudio_blender", "data")
TDO_PATH = os.path.join(DATA_DIR, "3D object library.tdo")

MM = 1000.0  # buffer vertices are in meters (scale_pixelsPerMm = 0.001)

PLA_SEED_PATTERN = re.compile(
    r"Starting seed for random number generator "
    r"\[kGeneralStartingSeedForRandomNumberGenerator\]\s*=\s*(\d+)")

PLA_SAVED_AGE_PATTERN = re.compile(
    r"Age for drawing \[kStateAge\]\s*=\s*(\d+)")


def pla_seeds(pla_path):
    """Per-plant seeds in file order (plants are stored in file order, the
    same order parse_pla_file returns species in)."""
    with open(pla_path, "r", encoding="cp1252") as f:
        return [int(m.group(1)) for m in PLA_SEED_PATTERN.finditer(f.read())]


def pla_saved_ages(pla_path):
    """Per-plant kStateAge in file order. PlantStudio exports a plant at its
    saved age, so reference comparisons grow to the same value."""
    with open(pla_path, "r", encoding="cp1252") as f:
        return [int(m.group(1)) for m in PLA_SAVED_AGE_PATTERN.finditer(f.read())]


def merged_tdo_library():
    """Library TDOs + species-embedded TDOs (mirrors operators.get_library)."""
    tdo_lib = TdoLibrary.from_file(TDO_PATH)
    lib = SpeciesLibrary(DATA_DIR)
    missing = [t for name, t in lib.embedded_tdos.items()
               if tdo_lib.get(name) is None]
    tdo_lib.merge(missing)
    return lib, tdo_lib


def draw_headless(plant):
    buffer = MeshBuffer()
    turtle = MeshTurtle(buffer)
    turtle.setScale_pixelsPerMm(0.001)
    draw_plant(plant, turtle)
    return buffer


def _face_area_mm2(vertices, face):
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = \
        (vertices[face[0]], vertices[face[1]], vertices[face[2]])
    ux, uy, uz = (bx - ax) * MM, (by - ay) * MM, (bz - az) * MM
    vx, vy, vz = (cx - ax) * MM, (cy - ay) * MM, (cz - az) * MM
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    return 0.5 * math.sqrt(nx * nx + ny * ny + nz * nz)


def _bbox_mm(points):
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return [min(xs) * MM, max(xs) * MM, min(ys) * MM, max(ys) * MM,
            min(zs) * MM, max(zs) * MM]


def _iter_parts(plant):
    seen = set()
    stack = [plant.firstPhytomer]
    while stack:
        part = stack.pop()
        if part is None or id(part) in seen:
            continue
        seen.add(id(part))
        yield part
        stack.extend([
            getattr(part, "leftBranchPlantPart", None),
            getattr(part, "rightBranchPlantPart", None),
            getattr(part, "nextPlantPart", None),
            getattr(part, "leftLeaf", None),
            getattr(part, "rightLeaf", None),
        ])
        stack.extend(getattr(part, "flowers", []) or [])


def _biomass_by_class(plant):
    totals = {}
    for part in _iter_parts(plant):
        cls = type(part).__name__
        totals[cls] = totals.get(cls, 0.0) + \
            float(getattr(part, "liveBiomass_pctMPB", 0.0) or 0.0)
    return {cls: round(value, 6) for cls, value in sorted(totals.items())}


def _part_census(buffer):
    """Aggregate the buffer per part export type."""
    vertices = buffer.vertices
    per_part = {}

    def slot(part_id):
        key = part_id if part_id is not None else -1
        if key not in per_part:
            per_part[key] = {
                "faces": 0,
                "area_mm2": 0.0,
                "pipe_segments": 0,
                "pipe_length_mm": 0.0,
                "pipe_radius_mm": [],
                "tdo_instances": 0,
                "tdo_triangles": 0,
                "tdo_scale_sum": 0.0,
                "ring_radius_mm": [],
                "_points": [],
            }
        return per_part[key]

    for face, part_id in zip(buffer.faces, buffer.face_part_ids):
        entry = slot(part_id)
        entry["faces"] += 1
        entry["area_mm2"] += _face_area_mm2(vertices, face)
        for index in face:
            entry["_points"].append(vertices[index])

    for record in buffer.pipe_records:
        entry = slot(record.get("part_id"))
        entry["pipe_segments"] += 1
        (sx, sy, sz), (ex, ey, ez) = record["start"], record["end"]
        entry["pipe_length_mm"] += math.dist((sx, sy, sz), (ex, ey, ez)) * MM
        mean_radius = (record["radius_start"] + record["radius_end"]) / 2.0
        entry["pipe_radius_mm"].append(mean_radius * MM)

    for record in buffer.triangle_set_records:
        entry = slot(record.get("part_id"))
        entry["tdo_instances"] += 1
        entry["tdo_triangles"] += record["triangles"]
        entry["tdo_scale_sum"] += record["scale"]
        origin = record.get("origin")
        centroid = record.get("centroid")
        if origin and centroid:
            entry["ring_radius_mm"].append(math.dist(origin, centroid) * MM)

    result = {}
    for key, entry in per_part.items():
        radii = entry.pop("pipe_radius_mm")
        ring = entry.pop("ring_radius_mm")
        name = PART_NAMES.get(key, f"untagged({key})") if key != -1 else "untagged"
        result[name] = {
            "faces": entry["faces"],
            "area_mm2": round(entry["area_mm2"], 3),
            "bbox_mm": _bbox_mm(entry["_points"]),
            "pipe_segments": entry["pipe_segments"],
            "pipe_length_mm": round(entry["pipe_length_mm"], 3),
            "pipe_radius_mm": round(sum(radii) / len(radii), 4) if radii else None,
            "tdo_instances": entry["tdo_instances"],
            "tdo_triangles": entry["tdo_triangles"],
            "tdo_mean_scale": round(entry["tdo_scale_sum"] /
                                    max(1, entry["tdo_instances"]), 6),
            "ring_radius_mm": round(sum(ring) / len(ring), 4) if ring else None,
        }
        entry["_points"] = []
    return result


def census_for_species(species, ages, seed, tdo_library):
    """Grow + draw one plant per age; return {age: census}.

    seed=None uses the species' params default (what PdPlant does when the
    .pla didn't set one) — pass the .pla's stored seed for PlantStudio-
    identical plants.
    """
    results = {}
    for age in ages:
        plant = create_plant(species, seed=seed, tdo_library=tdo_library)
        plant.growTo(age)
        buffer = draw_headless(plant)
        xs = [v[0] for v in buffer.vertices]
        ys = [v[1] for v in buffer.vertices]
        zs = [v[2] for v in buffer.vertices]
        results[str(age)] = {
            "whole_plant": {
                "height_mm": round((max(xs) - min(xs)) * MM, 3) if xs else 0.0,
                "width_mm": round((max(ys) - min(ys)) * MM, 3) if ys else 0.0,
                "depth_mm": round((max(zs) - min(zs)) * MM, 3) if zs else 0.0,
                "faces": len(buffer.faces),
                "vertices": len(buffer.vertices),
                "live_biomass_by_class": _biomass_by_class(plant),
            },
            "parts": _part_census(buffer),
        }
    return results


def print_table(census):
    for species_name, data in census.get("species", {}).items():
        if "error" in data:
            print(f"\n{species_name}: ERROR {data['error']}")
            continue
        for age, age_data in data["ages"].items():
            whole = age_data["whole_plant"]
            print(f"\n{species_name} @ age {age}: "
                  f"h={whole['height_mm']:.1f} w={whole['width_mm']:.1f} "
                  f"d={whole['depth_mm']:.1f} faces={whole['faces']}")
            print(f"  {'part':28s} {'faces':>6s} {'area_mm2':>10s} "
                  f"{'pipes':>6s} {'pipe_mm':>9s} {'tdo':>5s} {'ring_mm':>8s}")
            for name, part in age_data["parts"].items():
                print(f"  {name:28s} {part['faces']:6d} {part['area_mm2']:10.2f} "
                      f"{part['pipe_segments']:6d} {part['pipe_length_mm']:9.2f} "
                      f"{part['tdo_instances']:5d} "
                      f"{(part['ring_radius_mm'] if part['ring_radius_mm'] is not None else float('nan')):8.2f}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--species", nargs="*", default=None,
                        help="species names (default: all)")
    parser.add_argument("--category", nargs="*", default=None,
                        help="category (pla file stem) filter")
    parser.add_argument("--ages", nargs="*", type=int, default=[30, 100])
    parser.add_argument("--saved-ages", action="store_true",
                        help="grow each species to its saved kStateAge from "
                             "its .pla (PlantStudio exports plants at their "
                             "saved age) instead of --ages")
    parser.add_argument("--seed", type=int, default=None,
                        help="override the RNG seed for all species "
                             "(default: each species' seed from its .pla)")
    parser.add_argument("--out", default=None,
                        help="write JSON census here")
    parser.add_argument("--table", action="store_true",
                        help="print human-readable table")
    args = parser.parse_args(argv)

    lib, tdo_lib = merged_tdo_library()
    species = lib.species
    if args.category:
        species = [s for s in species if s.category in args.category]
    if args.species:
        wanted = set(args.species)
        missing = wanted - {s.name for s in species}
        if missing:
            parser.error(f"unknown species: {sorted(missing)}")
        species = [s for s in species if s.name in wanted]

    # per-category .pla seeds (file order == species parse order)
    seeds_by_category = {}
    saved_ages_by_category = {}
    if args.seed is None:
        for category in lib.categories:
            path = os.path.join(DATA_DIR, f"{category}.pla")
            if os.path.exists(path):
                seeds_by_category[category] = pla_seeds(path)
                saved_ages_by_category[category] = pla_saved_ages(path)

    census = {
        "meta": {
            "tool": "plant_census.py",
            "seed": args.seed if args.seed is not None else "per .pla",
            "ages": "per .pla kStateAge" if args.saved_ages else args.ages,
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "species_count": len(species),
        },
        "species": {},
    }
    for s in species:
        if args.seed is not None:
            seed = args.seed
        else:
            cat_species = lib.categories.get(s.category, [])
            seeds = seeds_by_category.get(s.category)
            if seeds and len(seeds) == len(cat_species):
                seed = seeds[cat_species.index(s)]
            else:
                seed = None
        if args.saved_ages:
            cat_species = lib.categories.get(s.category, [])
            ages = saved_ages_by_category.get(s.category)
            if ages and len(ages) == len(cat_species):
                ages = [ages[cat_species.index(s)]]
            else:
                ages = list(args.ages)
        else:
            ages = list(args.ages)
        try:
            census["species"][s.name] = {
                "category": s.category,
                "seed": seed,
                "ages": census_for_species(s, ages, seed, tdo_lib),
            }
        except Exception as e:
            census["species"][s.name] = {
                "category": s.category,
                "error": f"{type(e).__name__}: {e}",
            }

    if args.table:
        print_table(census)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(census, f, indent=1, sort_keys=True)
        print(f"wrote {args.out}", file=sys.stderr)
    if not args.table and not args.out:
        print(json.dumps(census, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
