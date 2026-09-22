"""Violet height triage v2: per-petiole pitch, ours vs ref, exact chunking.

Counts (reconciled with census/compare):
- violet: 6 phytomers x 2 leaves = 12 regular petioles, +2 seedling petioles
- each petiole = 7 pipe divisions x 3-sided pipe x 2 tris = 42 tris
- leaf TDO = 15 tris x 14 instances = 210 tris

Ref chunking is by exact tri count in file (draw) order; base = chunk
endpoint nearer the crown axis (min sqrt(x^2+z^2)), pitch = signed elevation
of base->tip in y-up mm.
"""
import math
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from plant_census import merged_tdo_library  # noqa: E402
from plantstudio_blender.core.factory import create_plant  # noqa: E402
from plantstudio_blender.core.draw import draw_plant  # noqa: E402
from plantstudio_blender.core.mesh_buffer import MeshBuffer  # noqa: E402
from plantstudio_blender.core.turtle import MeshTurtle  # noqa: E402

MM = 1000.0
OBJ = os.path.join(os.path.dirname(__file__), "violet_only_age100.obj")
SCALE = 1.66  # export units per mm

PETIOLE_TRIS = 42  # 7 divisions x 3 sides x 2
LEAF_TRIS = 15


def pitch(base, tip, up_idx):
    d = [tip[k] - base[k] for k in range(3)]
    horiz = [d[k] for k in range(3) if k != up_idx]
    h = math.hypot(*horiz)
    return math.degrees(math.atan2(d[up_idx], h)) if h > 1e-9 else 90.0


def ours():
    lib, tdo_lib = merged_tdo_library()
    species = next(s for s in lib.species if s.name == "violet")
    plant = create_plant(species, seed=8737, tdo_library=tdo_lib)
    plant.growTo(60)
    buffer = MeshBuffer()
    turtle = MeshTurtle(buffer)
    turtle.setScale_pixelsPerMm(0.001)
    draw_plant(plant, turtle)
    strokes = {}
    for rec in buffer.pipe_records:
        if rec["part_id"] in (5, 4):  # Petiole, FirstPetiole
            strokes.setdefault((rec["part_id"], rec["stroke_id"]),
                               []).append(rec)
    rows = []
    for (pid, sid), recs in sorted(strokes.items(),
                                   key=lambda kv: (kv[0][0], kv[0][1] or 0)):
        base = tuple(MM * c for c in recs[0]["start"])
        tip = tuple(MM * c for c in recs[-1]["end"])
        if base[0] > tip[0]:  # base closer to ground/up-axis origin
            base, tip = tip, base
        rows.append({"kind": "seed" if pid == 4 else "reg",
                     "base": base, "tip": tip, "tris": 6 * len(recs)})
    blades = [r for r in buffer.triangle_set_records
              if r.get("part_id") in (3, 2)]
    return rows, blades, 1  # up = x for ours


def ref_chunks():
    verts = []
    groups = {}
    current = None
    block_first = 0
    block_count = 0
    with open(OBJ, encoding="cp1252", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if line.startswith("g "):
                suffix = line[2:].strip().rsplit("_", 1)[-1]
                current = suffix if suffix in ("Petiole", "1stPetiole",
                                               "Leaf", "1stLeaf") else None
                block_first = len(verts)
                block_count = 0
            elif line.startswith("v "):
                x, y, z = (float(t) for t in line[2:].split()[:3])
                verts.append((x, -y, z))  # un-flip up axis
                block_count += 1
            elif line.startswith("f ") and current:
                idx = []
                for tok in line[2:].split()[:3]:
                    i = int(tok.split("/")[0])
                    if i < 0:
                        idx.append(len(verts) + i)
                    elif block_count and i <= block_count:
                        idx.append(block_first + i - 1)
                    else:
                        idx.append(i - 1)
                groups.setdefault(current, []).append(tuple(idx))
    return verts, groups


def main():
    our_rows, our_blades, up = ours()
    verts, groups = ref_chunks()

    print("=== OURS (mm, +x up) — petiole strokes ===")
    for i, r in enumerate(our_rows):
        p = pitch(r["base"], r["tip"], 0)
        print(f"{r['kind']:4s} petiole {i:2d} tris={r['tris']:3d} "
              f"base=({r['base'][0]:7.1f},{r['base'][1]:7.1f},{r['base'][2]:7.1f}) "
              f"tip=({r['tip'][0]:7.1f},{r['tip'][1]:7.1f},{r['tip'][2]:7.1f}) "
              f"len={math.dist(r['base'], r['tip']):6.1f} pitch={p:6.1f}")
    print(f"blade TDO instances: {len(our_blades)}")

    print("\n=== REF (mm, +y up; raw/1.66) — exact 42-tri chunks ===")
    for pname, kind in (("Petiole", "reg"), ("1stPetiole", "seed")):
        tris = groups.get(pname, [])
        n = len(tris) // PETIOLE_TRIS
        print(f"-- {pname}: {len(tris)} tris -> {n} petioles")
        pitches = []
        for i in range(n):
            chunk = tris[i * PETIOLE_TRIS:(i + 1) * PETIOLE_TRIS]
            pts = [tuple(c / SCALE for c in verts[ix]) for t in chunk
                   for ix in t]
            # base = endpoint nearest crown axis (min xz radius)
            ends = []
            for cand in pts:
                ends.append((math.hypot(cand[0], cand[2]), cand))
            ends.sort()
            base = ends[0][1]
            far = max(pts, key=lambda p: math.dist(base, p))
            # tip = point of chunk farthest from base (pipe tip)
            p = pitch(base, far, 1)
            pitches.append(p)
            print(f"{kind:4s} petiole {i:2d} "
                  f"base=({base[0]:7.1f},{base[1]:7.1f},{base[2]:7.1f}) "
                  f"tip=({far[0]:7.1f},{far[1]:7.1f},{far[2]:7.1f}) "
                  f"len={math.dist(base, far):6.1f} pitch={p:6.1f}")
        if pitches:
            print(f"   pitch mean={sum(pitches)/len(pitches):6.1f} "
                  f"min={min(pitches):6.1f} max={max(pitches):6.1f}")

    for pname in ("Leaf", "1stLeaf"):
        tris = groups.get(pname, [])
        n = len(tris) // LEAF_TRIS
        print(f"-- {pname}: {len(tris)} tris -> {n} blade instances")
        for i in range(n):
            chunk = tris[i * LEAF_TRIS:(i + 1) * LEAF_TRIS]
            pts = [tuple(c / SCALE for c in verts[ix]) for t in chunk
                   for ix in t]
            c = [sum(p[k] for p in pts) / len(pts) for k in range(3)]
            ymax = max(p[1] for p in pts)
            print(f"   blade {i:2d} centroid=({c[0]:7.1f},{c[1]:7.1f},"
                  f"{c[2]:7.1f}) ymax={ymax:7.1f}")


if __name__ == "__main__":
    main()
