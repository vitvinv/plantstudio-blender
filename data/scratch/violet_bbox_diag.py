"""Which ref group owns the violet plant's vertical extremes?"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

OBJ = os.path.join(os.path.dirname(__file__), "violet_only_age100.obj")
SCALE = 1.66

verts = []
groups = {}
current = None
block_first = 0
block_count = 0
with open(OBJ, encoding="cp1252", errors="replace") as f:
    for raw in f:
        line = raw.strip()
        if line.startswith("g "):
            current = line[2:].strip()
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
            groups.setdefault(current, []).extend(idx)

pts = {g: [tuple(c / SCALE for c in verts[i]) for i in idx]
       for g, idx in groups.items()}

gmax = max(pts.items(), key=lambda kv: max(p[1] for p in kv[1]))
gmin = min(pts.items(), key=lambda kv: min(p[1] for p in kv[1]))
print(f"ref global max_y = {max(p[1] for p in gmax[1]):8.2f} owned by {gmax[0]}")
print(f"ref global min_y = {min(p[1] for p in gmin[1]):8.2f} owned by {gmin[0]}")
print(f"ref height (y extent) = {75.8722:.2f} (compare output)")
print()
print(f"{'group':22s} {'ymin':>8s} {'ymax':>8s} {'extent':>8s}")
for g in sorted(pts):
    ys = [p[1] for p in pts[g]]
    print(f"{g:22s} {min(ys):8.2f} {max(ys):8.2f} {max(ys)-min(ys):8.2f}")

print("\nOURS (census census_violet.json, mm, buffer +x = up):")
import json
with open(os.path.join(os.path.dirname(__file__), "census_violet.json"),
          encoding="utf-8") as f:
    cen = json.load(f)
parts = cen["species"]["violet"]["ages"]["60"]["parts"]
whole = cen["species"]["violet"]["ages"]["60"]["whole_plant"]
print(f"whole: height={whole['height_mm']} width={whole['width_mm']} "
      f"depth={whole['depth_mm']}")
print(f"{'part':30s} {'up_min':>8s} {'up_max':>8s} {'extent':>8s}")
for name, p in parts.items():
    bb = p["bbox_mm"]  # [xmin,xmax,ymin,ymax,zmin,zmax], up = x
    print(f"{name:30s} {bb[0]:8.2f} {bb[1]:8.2f} {bb[1]-bb[0]:8.2f}")
