"""Reference comparison — census metrics from a PlantStudio OBJ export vs ours.

Parses the part-tagged OBJ files produced by tools/plantstudio_export.py
(groups named '<plant>_<part short name>' per kLayerOutputByTypeOfPlantPart),
computes the same per-part metrics as tools/plant_census.py and prints a
side-by-side table with tolerance verdicts.

Conventions handled:
- PlantStudio writes y negated ('all y values must be negative because it
  seems our coordinate systems are different') — un-flipped here.
- overallScalingFactor_pct is undone (÷ factor) so reference units are the
  turtle's drawing units; comparisons additionally normalize by plant height.
- Each group's v-block is self-contained and face indices are written
  RELATIVE (negative indices count back from the last vertex written, see
  U3dexport.pas endVerticesAndTriangles); positive small indices are handled
  as block-local as a fallback.
- Unregistered builds add a '<plant>_reminder' quad group — skipped.

Usage:
    python tools/compare_reference_obj.py --census plant_census.json ^
        --reference "data/reference/New version 2 plants_age100.obj" ^
        --tolerance 0.05
"""

import argparse
import json
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from plantstudio_blender.core.draw import PART_NAMES, PART_SHORT_NAMES

SHORT_TO_PART = {short: pid for pid, short in PART_SHORT_NAMES.items()}


# ── OBJ parsing ─────────────────────────────────────────────────────────────


def load_reference(path):
    """Return {plant_name: {part: {"faces": n, "area": a, ...}}} plus
    whole-plant extents, in export units, y un-flipped."""
    with open(path, "r", encoding="cp1252", errors="replace") as f:
        lines = f.readlines()

    vertices = []
    plant_order = []
    plants = {}       # name -> {part: [tri index tuples]}
    current_plant = None
    current_part = None
    block_first_v = 0
    block_v_count = 0

    def resolve(index):
        if index < 0:
            return len(vertices) + index
        if block_v_count and index <= block_v_count:
            return block_first_v + index - 1
        return index - 1

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("o "):
            current_plant = line[2:].strip()
            if current_plant not in plants:
                plants[current_plant] = {}
                plant_order.append(current_plant)
            current_part = None
            block_first_v = len(vertices)
            block_v_count = 0
        elif line.startswith("g "):
            block_first_v = len(vertices)
            block_v_count = 0
            group = line[2:].strip()
            if group.endswith("_reminder"):
                current_part = None
                continue
            suffix = group.rsplit("_", 1)[-1]
            current_part = PART_NAMES[SHORT_TO_PART[suffix]] \
                if suffix in SHORT_TO_PART else None
        elif line.startswith("v "):
            x, y, z = (float(tok) for tok in line[2:].split()[:3])
            vertices.append((x, -y, z))
            block_v_count += 1
        elif line.startswith("f "):
            if current_part is None or current_plant is None:
                continue
            try:
                tri = tuple(resolve(int(tok.split("/")[0]))
                            for tok in line[2:].split()[:3])
            except (ValueError, IndexError):
                continue
            plants[current_plant].setdefault(current_part, []).append(tri)

    report = {}
    for name in plant_order:
        parts = plants[name]
        # whole-plant height: extent along +y (the un-flipped up axis)
        all_pts = [vertices[i] for tris in parts.values()
                   for tri in tris for i in tri]
        if not all_pts:
            continue
        ys = [p[1] for p in all_pts]
        height = max(ys) - min(ys)
        part_stats = {}
        for part, tris in sorted(parts.items()):
            pts = [vertices[i] for tri in tris for i in tri]
            xs = [p[0] for p in pts]
            ys_p = [p[1] for p in pts]
            zs = [p[2] for p in pts]
            area = 0.0
            for tri in tris:
                (ax, ay, az), (bx, by, bz), (cx, cy, cz) = \
                    (vertices[tri[0]], vertices[tri[1]], vertices[tri[2]])
                ux, uy, uz = bx - ax, by - ay, bz - az
                vx, vy, vz = cx - ax, cy - ay, cz - az
                area += 0.5 * math.sqrt((uy * vz - uz * vy) ** 2
                                        + (uz * vx - ux * vz) ** 2
                                        + (ux * vy - uy * vx) ** 2)
            part_stats[part] = {
                "faces": len(tris),
                "area": area,
                "extent_up": max(ys_p) - min(ys_p) if ys_p else 0.0,
                "extent_x": max(xs) - min(xs) if xs else 0.0,
                "extent_z": max(zs) - min(zs) if zs else 0.0,
            }
        report[name] = {
            "height": height,
            "width": max(p[0] for p in all_pts) - min(p[0] for p in all_pts),
            "depth": max(p[2] for p in all_pts) - min(p[2] for p in all_pts),
            "parts": part_stats,
        }
    return report


# ── comparison ──────────────────────────────────────────────────────────────


def normalize_name(name):
    """PlantStudio short names take the first N chars of the plant name and
    then drop spaces/punctuation ('flower t' -> 'flowert')."""
    keep = set("abcdefghijklmnopqrstuvwxyz0123456789")
    return "".join(c for c in name.lower() if c in keep)


def inventory_check(reference, species_names):
    """3-way parity: OBJ plants vs census species. Prints the mapping and
    returns (ok, messages) — fails on any extra or missing plant."""
    messages = []
    ok = True
    matched = {}
    for obj_plant in reference:
        match = match_species(obj_plant, species_names)
        if match is None:
            messages.append(f"MISSING in census: OBJ plant {obj_plant!r} "
                            f"has no census species")
            ok = False
        else:
            matched[obj_plant] = match
    used = set(matched.values())
    for name in species_names:
        if name not in used:
            messages.append(f"MISSING in OBJ: census species {name!r} "
                            f"has no exported plant")
            ok = False
    for obj_plant, match in sorted(matched.items()):
        messages.append(f"OK: {obj_plant!r} -> {match!r}")
    return ok, messages


def match_species(obj_plant, census_species):
    """Map a truncated OBJ plant name to the census species name."""
    obj_norm = normalize_name(obj_plant)
    matches = [name for name in census_species
               if normalize_name(name).startswith(obj_norm)]
    if not matches:
        return None
    return max(matches, key=len)


def compare_plant(census_plant, reference_plant, tolerance,
                  ref_unit_mm=1.0, know_units=False, tdo_double_sided=True,
                  mm_per_unit=None):
    """Return (rows, whole_plant_diffs) for one plant at one age.

    tdo_double_sided: the user's PlantStudio build persists
    'makeTrianglesDoubleSided' for 3D-object exports, so every TDO triangle
    (and its area) appears twice in the reference. Pipe (cylinder) parts are
    unaffected. When our census marks a part as TDO instances, the reference
    metrics are halved before comparing.

    mm_per_unit: when given (per-plant kStateDrawingScale conversion), the
    reference metrics are converted to mm and the AREA verdicts compare
    absolute areas (ours mm² vs converted ref mm²) instead of
    height-normalized fractions — shape-only residuals then surface in the
    up-extent and whole-plant rows, not as per-part area FAILs.
    """
    ref = reference_plant
    ours_whole = census_plant["whole_plant"]
    ref_height_raw = ref["height"]
    ours_height = ours_whole["height_mm"]
    ref_height = ref_height_raw * ref_unit_mm  # for the absolute height row
    our_parts = census_plant["parts"]
    if mm_per_unit is not None:
        ref_height_raw = ref_height_raw * mm_per_unit

    rows = []
    names = sorted(set(ref["parts"]) | set(our_parts))
    for name in names:
        ours = our_parts.get(name)
        theirs = ref["parts"].get(name)
        row = {"part": name}
        for label, data, key_area in (("ours", ours, "area_mm2"),
                                      ("ref", theirs, "area")):
            if data is None:
                row[f"{label}_faces"] = None
                row[f"{label}_area_frac"] = None
                row[f"{label}_up_frac"] = None
            else:
                # fractions are computed in each side's own units: the
                # plant height of the SAME unit system normalizes them
                h = ours_height if label == "ours" else ref_height_raw
                faces = data["faces"]
                area = data[key_area]
                if label == "ref":
                    if tdo_double_sided and ours is not None \
                            and ours.get("tdo_instances", 0) > 0:
                        # exporter wrote each TDO triangle twice
                        faces = faces / 2.0
                        area = area / 2.0
                    if mm_per_unit is not None:
                        area = area * mm_per_unit ** 2
                row[f"{label}_faces"] = faces
                row[f"{label}_area_frac"] = area / max(h, 1e-9) ** 2
                if label == "ours":
                    # our bbox is [xmin, xmax, ymin, ymax, zmin, zmax] in mm
                    # and the up axis is buffer +X
                    bbox = data.get("bbox_mm") or [0, 0, 0, 0, 0, 0]
                    extent_up = bbox[1] - bbox[0]
                else:
                    extent_up = data.get("extent_up", 0.0)
                    if mm_per_unit is not None:
                        extent_up = extent_up * mm_per_unit
                row[f"{label}_up_frac"] = extent_up / max(h, 1e-9)
                row[f"{label}_area_abs"] = area
        # verdicts
        area_metric = "area_abs" if mm_per_unit is not None else "area_frac"
        area_near_zero = 0.01 if mm_per_unit is not None else 0.001
        verdicts = []
        for metric, near_zero in ((area_metric, area_near_zero),
                                  ("up_frac", 0.01)):
            a, b = row.get(f"ours_{metric}"), row.get(f"ref_{metric}")
            if a is None and b is None:
                verdicts.append("absent")
            elif a is None:
                # ours absent: the original still emits degenerate (zero-
                # length/zero-area) cylinders we weld away — pass those
                verdicts.append("degenerate" if b < near_zero else "MISSING")
            elif b is None:
                verdicts.append("MISSING")
            else:
                denom = max(abs(a), abs(b), 1e-9)
                diff = abs(a - b) / denom
                verdicts.append("PASS" if diff <= tolerance
                                else f"FAIL({diff:.0%})")
        row["verdict_area"] = verdicts[0]
        row["verdict_extent"] = verdicts[1]
        rows.append(row)

    whole = {
        "height": (ours_height, ref_height, know_units),
        "width": (ours_whole["width_mm"] / max(ours_height, 1e-9),
                  ref["width"] / max(ref_height_raw, 1e-9), True),
        "depth": (ours_whole["depth_mm"] / max(ours_height, 1e-9),
                  ref["depth"] / max(ref_height_raw, 1e-9), True),
    }
    if mm_per_unit is not None:
        # absolute view: convert the reference to mm
        whole = {
            "height": (ours_height, ref_height_raw, True),
            "width": (ours_whole["width_mm"],
                      ref["width"] * mm_per_unit, True),
            "depth": (ours_whole["depth_mm"],
                      ref["depth"] * mm_per_unit, True),
        }
    return rows, whole


def print_comparison(rows, whole, tolerance, absolute=False):
    def fmt(v, width=10, scale=1.0, precision=4):
        return (f"{v * scale:{width}.{precision}f}" if v is not None
                else " " * width + "-")

    area_key = "area_abs" if absolute else "area_frac"
    header = "area ours" if absolute else "area/ours"
    header2 = "area ref" if absolute else "area/ref"
    print(f"\n  {'part':30s} {'faces ours':>10s} {'faces ref':>9s} "
          f"{header:>14s} {header2:>14s} {'up/ours':>8s} {'up/ref':>8s} "
          f"  verdicts")
    for r in rows:
        ours_area = r.get("ours_" + area_key)
        ref_area = r.get("ref_" + area_key)
        print(f"  {r['part']:30s} "
              f"{r['ours_faces'] if r['ours_faces'] is not None else '-':>10} "
              f"{r['ref_faces'] if r['ref_faces'] is not None else '-':>9} "
              f"{fmt(ours_area, 14, 1.0, 2)} {fmt(ref_area, 14, 1.0, 2)} "
              f"{fmt(r['ours_up_frac'], 8, 100, 2)}% "
              f"{fmt(r['ref_up_frac'], 8, 100, 2)}%"
              f"  {r['verdict_area']} / {r['verdict_extent']}")
    print("  whole plant (%s):" % ("absolute mm" if absolute
                                   else "height-normalized"))
    for key, (a, b, comparable) in whole.items():
        if comparable:
            diff = abs(a - b) / max(abs(a), abs(b), 1e-9)
            verdict = "PASS" if diff <= tolerance else f"FAIL({diff:.0%})"
            print(f"    {key:8s} ours={a:10.4f} ref={b:10.4f}  {verdict}")
        else:
            print(f"    {key:8s} ours={a:10.4f} ref={b:10.4f}  "
                  f"info (units differ; pass --pixels-per-mm to compare)")


def pla_file_zoom(src):
    """File-header view zoom ('scale=' before the first plant section).

    The exporter bakes it into coordinates; all previously validated
    folders save 1.0, so it stayed invisible until the breeder folder
    shipped scale=1.79 (Bushes 1.13 and the anchor 0.28 predate it but
    only ever compared height-normalized, where the zoom cancels).
    """
    m = re.search(r"(?m)^scale\s*=\s*([\d.eE+-]+)", src)
    return float(m.group(1)) if m and float(m.group(1)) > 0 else 1.0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--census", required=True,
                        help="plant_census.json from tools/plant_census.py")
    parser.add_argument("--reference", required=True, nargs="+",
                        help="reference OBJ file(s) from PlantStudio export")
    parser.add_argument("--age", type=int, default=100,
                        help="census age to compare against")
    parser.add_argument("--saved-ages", action="store_true",
                        help="use each species' saved kStateAge (the census "
                             "was run with --saved-ages; each census entry "
                             "has a single age key)")
    parser.add_argument("--tolerance", type=float, default=0.05,
                        help="relative tolerance for PASS (default 0.05)")
    parser.add_argument("--pixels-per-mm", type=float, default=None,
                        help="reference export units per mm (the .pla "
                             "drawingScale_PixelsPerMm times any window "
                             "zoom); enables absolute height comparison")
    parser.add_argument("--saved-scales", action="store_true",
                        help="PRIMARY verdict mode: read each plant's saved "
                             "kStateDrawingScale from --pla (export units = "
                             "mm x scale) and compare per-part AREAS in "
                             "absolute units; height-normalized residuals "
                             "then appear only in the up/whole-plant rows")
    parser.add_argument("--pla", default=None,
                        help="source .pla file (for --saved-scales; "
                             "default: data/<reference basename>.pla)")
    parser.add_argument("--inventory", action="store_true",
                        help="run the 3-way inventory parity check "
                             "(OBJ plants vs census species) and exit")
    args = parser.parse_args(argv)

    with open(args.census, encoding="utf-8") as f:
        census = json.load(f)
    species = census["species"]
    ref_unit_mm = 1.0 / args.pixels_per_mm if args.pixels_per_mm else 1.0

    if args.inventory:
        failures = 0
        for obj_path in args.reference:
            reference = load_reference(obj_path)
            print(f"=== inventory: {os.path.basename(obj_path)} "
                  f"({len(reference)} OBJ plants, {len(species)} census "
                  f"species) ===")
            ok, messages = inventory_check(reference, species)
            for m in messages:
                print(f"  {m}")
            if not ok:
                failures += 1
        return 1 if failures else 0

    saved_scales = {}
    if args.saved_scales:
        pla = args.pla
        if pla is None:
            stem = os.path.splitext(os.path.basename(args.reference[0]))[0]
            stem = re.sub(r"_(saved|age\d+)$", "", stem)
            pla = os.path.join(ROOT, "plantstudio_blender", "data",
                               stem + ".pla")
        src = open(pla, encoding="cp1252", errors="replace").read()
        chunks = re.split(r"\[(.*?)\]\s*start PlantStudio plant", src)
        for i in range(1, len(chunks), 2):
            m = re.search(r"kStateDrawingScale\]\s*=\s*([\d.eE+-]+)",
                          chunks[i + 1])
            if m:
                saved_scales[chunks[i]] = float(m.group(1))
        # file-header view zoom: the exporter bakes it into coordinates
        file_scale = pla_file_zoom(chunks[0])

    failures = 0
    for obj_path in args.reference:
        reference = load_reference(obj_path)
        print(f"\n=== {os.path.basename(obj_path)} "
              f"({len(reference)} plants) ===")
        for obj_plant, ref_plant in reference.items():
            match = match_species(obj_plant, species)
            if match is None:
                print(f"  {obj_plant}: no census species matches")
                continue
            census_entry = species[match]
            if "error" in census_entry:
                print(f"  {match}: census has error {census_entry['error']}")
                continue
            if args.saved_ages:
                age_keys = sorted(census_entry["ages"])
                if len(age_keys) != 1:
                    print(f"  {match}: --saved-ages expects exactly one age "
                          f"key, got {age_keys}")
                    continue
                age = int(age_keys[0])
            else:
                age = args.age
            census_plant = census_entry["ages"].get(str(age))
            if census_plant is None:
                print(f"  {match}: census has no age {age}")
                continue
            mm_per_unit = None
            if args.saved_scales:
                scale = saved_scales.get(match)
                if scale is None:
                    print(f"  {match}: no kStateDrawingScale in .pla "
                          f"(--saved-scales skipped for this plant)")
                elif scale <= 0:
                    print(f"  {match}: kStateDrawingScale {scale} invalid")
                else:
                    mm_per_unit = 1.0 / (scale * file_scale)
            print(f"\n  plant {obj_plant!r} = census species {match!r} "
                  f"@ age {age}"
                  + (f"  [scale {scale:g} units/mm = {mm_per_unit:.4f} "
                     f"mm/unit" + (f", file zoom {file_scale:g}"
                                   if file_scale != 1.0 else "") + "]"
                     if mm_per_unit is not None else ""))
            rows, whole = compare_plant(
                census_plant, ref_plant, args.tolerance,
                ref_unit_mm=ref_unit_mm,
                know_units=args.pixels_per_mm is not None or mm_per_unit is not None,
                mm_per_unit=mm_per_unit)
            print_comparison(rows, whole, args.tolerance,
                             absolute=mm_per_unit is not None)
            if any("FAIL" in r["verdict_area"] + r["verdict_extent"]
                   for r in rows):
                failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
