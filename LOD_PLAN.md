# Plan: LOD (Level of Detail) for PlantStudio-Blender

**Status:** Active (Aug 26, 2026)
**Author:** user + Hermes (rewritten Aug 26 after a bad agent attempt was reverted)
**Where:** code lives ONLY in `C:\Users\vitvin_v\dev\plantstudio-blender`. The `digital-garden` repo is a generated mirror — never hand-edit code there; it is updated by `python scripts/sync_addon.py` from plantstudio-blender.

## Goal

Expose a Level-of-Detail system so plants can be previewed, rendered and exported at different detail levels (and optionally auto-selected by camera distance in the viewport). Low LOD saves geometry: ~50–67% fewer faces, still a recognizable silhouette.

## Current State (honest — read this, not the reverted attempt)

The headless core in **plantstudio-blender** has **NO LOD today**. Current facts:

- `MeshTurtle.__init__(mesh_buffer=None)` — no `lod_level` parameter.
- `draw_tdo` draws **every** triangle; no triangle subsampling.
- Pipe cross-section is fixed: `PIPE_FACES = 3` (triangle), `add_pipe` clamps `max(3, faces)`.
- Radial repetitions (petals, sepals, buds) are drawn at full count.
- A previous weak agent (Freebuf) implemented an LOD system in the digital-garden mirror (wrong repo) with corrupted file encoding (UTF-8 mojibake: `â`/`Ã` instead of `—`/`×`). It was **reverted**. Nothing from that attempt survives; do not look for leftover code.

Everything below must be implemented **from scratch, cleanly, in plantstudio-blender**.

## Design

Three independent mechanisms, controlled by one `lod_level` int on `MeshTurtle` (0 = low, 1 = medium, 2 = full):

| LOD Level | Triangle Step | Pipe Faces | Repetition Scale | Effect |
|-----------|--------------|------------|-------------------|--------|
| 0 (low)  | every 3rd    | 2 (diamond)| halved (>3)       | ~67% reduction on TDO objects |
| 1 (mid)  | every 2nd    | 3 (tri)    | full              | ~50% reduction |
| 2 (full) | all          | 3 (tri)    | full              | full quality |

- **`lod_triangle_step()`** — subsample TDO triangles (draw every Nth; step 1 = all).
- **`lod_scale_repetitions(count)`** — halve radial repetitions (petals, sepals, buds) at LOD 0; always ≥ 1; counts ≤ 3 unchanged.
- **`lod_pipe_faces()`** — 2 faces (diamond cross-section) at LOD 0, `PIPE_FACES` at LOD 1+.

## Phase 0 — Headless LOD in the core (required base; do this first)

Files: `plantstudio_blender/core/turtle.py`, `plantstudio_blender/core/draw.py`, `plantstudio_blender/core/mesh_buffer.py`, `plantstudio_blender/tests/test_mesh_output.py`, `scripts/audit_geometry.py`.

1. **`turtle.py`**: add `lod_level=0` param to `MeshTurtle.__init__`; `_LOD_TRIANGLE_STEP = (3, 2, 1)`; implement the three helpers above.
2. **`draw.py`**: use `turtle.lod_pipe_faces()` and `turtle.lod_scale_repetitions(...)` instead of hard-coded `PIPE_FACES` / `5`; use `step = turtle.lod_triangle_step()` in the TDO triangle loop (regular subsampling, keeps silhouette).
3. **`mesh_buffer.py`**: change pipe clamp `max(3, faces)` → `max(2, faces)` and update the comment (2 = diamond/ribbon for LOD 0; default stays 3).
4. **`tests/test_mesh_output.py`**: add `TestLOD` covering:
   - LOD 0 faces < LOD 2 faces for a known species (e.g. phlox at day 200)
   - LOD 0 mesh non-degenerate (verts > 0, faces > 0)
   - default `MeshTurtle()` has `lod_level == 0`
   - `lod_triangle_step()`: 0→3, 1→2, 2→1, 5→1 (clamps)
   - `lod_scale_repetitions()`: LOD0 10→5, LOD0 2→2, LOD1 10→10
   - `lod_pipe_faces()`: LOD0→2, LOD1→3, LOD2→3
   - budget: every species in the bundled library ≤ 18 000 faces at LOD 0 (day 200, seed 280, scale 0.001)
5. **`scripts/audit_geometry.py`**: add `--lod` arg (choices `[0, 1, 2]`, default `0`), thread it through `draw()` to `MeshTurtle`.

**Acceptance:** `python -m pytest plantstudio_blender/tests/ -q` from the repo root is green (existing tests still pass — LOD 0 must remain default for headless/CI so nothing else changes).

## Phase 1 — Expose LOD in the Blender UI

Files: UI bridge only — `plantstudio_blender/ui_panel.py`, `plantstudio_blender/operators.py`, plus `plantstudio_blender/core/` as needed. Keep the headless core independent of `bpy`.

1. **Panel control** — `PlantStudio LOD Level` enum property on the plant object: `('LOW', "Low (LOD 0)"), ('MEDIUM', "Medium (LOD 1)"), ('FULL', "Full (LOD 2)")`, default `FULL`, stored as RNA property so it persists in `.blend`. Place in the existing PlantStudio panel.
2. **Operator `PLANTSTUDIO_OT_regenerate_lod`** — reads the enum, re-runs `draw_plant()` with the chosen `lod_level` on a fresh `MeshTurtle`, swaps verts/faces/colors on the existing mesh object in place; button in the panel; optional shortcut.
3. **Auto-LOD toggle (optional stretch)** — `PlantStudio Auto LOD` bool; `depsgraph_update_post` handler switches LOD by camera distance (`≤ 2m → FULL`, `2–5m → MEDIUM`, `> 5m → LOW`).

**Acceptance:** in Blender, changing the enum and pressing the button regenerates the mesh with visibly fewer/denser geometry; `.blend` round-trip keeps the setting.

## Phase 2 — Export at LOD

`plantstudio_blender/export` (or wherever the glTF/OBJ export lives):

1. LOD dropdown on the export operator; passes `lod_level` into `MeshTurtle` before exporting; default FULL (no surprises).
2. Batch mode: export all three LODs to `plant_lod0.glb`, `plant_lod1.glb`, `plant_lod2.glb`.
3. Embed LOD level as a custom property (extras) in glTF so the runtime (8th Wall AR) can query it.

## Working rules (every phase)

- Edit ONLY in `C:\Users\vitvin_v\dev\plantstudio-blender`. Never edit `digital-garden/plantstudio_blender/` — it is regenerated.
- All files UTF-8: em dash `—` and multiplication sign `×` must survive as real characters, no mojibake.
- After each phase: `python -m pytest plantstudio_blender/tests/ -q` from the repo root.
- When everything is done: `python scripts/sync_addon.py` from plantstudio-blender (pushes the addon repo, copies the headless subset to digital-garden, commits + pushes digital-garden).