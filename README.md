# PlantStudio-Blender Addon

An extension that brings the functions of **PlantStudio™ Botanical Illustration Software** into Blender. Create, grow, and tweak herbaceous plants (wildflowers, grasses, vegetables, garden flowers, shrubs) with a realtime wizard, then export them for use in your projects.
Fair warning: I am not a programmer. I have developed this addon with help of a coding agent to serve as a stylized engine for my art project. For now, my plan is to make a faithful recreation of PlantStudio in the modern environment, with a few quality of life improvements. That being said, a help from anyone with an actual coding experience will be much appreciated.

---

## What It Is

**PlantStudio-Blender** is a Python 3 port of **PlantStudio** (originally by Cynthia F. Kurtz & Paul Fernhout, Kurtz-Fernhout Software), wrapped as a Blender 4.2+ addon. The original PlantStudio was a Windows 95/98-era application for simulating herbaceous (non-woody) plant growth using a meristem/biomass model. This port:

- **Preserves original behavior, but realtime** — deterministic growth, parameter registry, `.pla`/`.tdo` file formats.
- **Runs headless** — the core (`plantstudio_blender/core/`) has zero Blender dependencies and can be imported in any Python 3.11+ environment for batch generation, testing, or server-side use.
- **Runs in Blender** — N-panel with a **Wizard** exposes 70+ parameters across 8 steps (Meristems → Internodes → Leaves → Compound Leaves → Inflorescence Placement → Inflorescence Drawing → Flowers → Fruits), with mesh rebuild on every slider change.
- **Bundles the original species library** — 9 `.pla` files (~1.4 MB) covering garden flowers, wildflowers, grasses, shrubs, vegetables, and "Strange Breeder" experimental plants, plus the original `3D object library.tdo` with 100+ hand-modeled plant parts (leaves, petals, buds, fruits).
- **Exports with metadata** — one-click JSON config export (`plant_id`, `species`, `seed`, `planted_date`) for use in headless pipelines (see `digital-garden-AR`).

---

## Architecture Overview

```
plantstudio_blender/
├── core/                    # Headless simulation & drawing (NO bpy)
│   ├── plant.py             # PdPlant — whole-plant growth, biomass allocation, traversal
│   ├── meristem.py          # PdMeristem — branching, phytomer/inflorescence creation
│   ├── internode.py         # PdInternode — stem segments
│   ├── leaf.py              # PdLeaf — simple & compound leaves
│   ├── inflorescence.py     # PdInflorescence — flower stalks, bracts, flowers
│   ├── flower_fruit.py      # PdFlowerFruit — flower & fruit development
│   ├── turtle.py            # MeshTurtle — 3D turtle graphics → MeshBuffer
│   ├── mesh_buffer.py       # MeshBuffer — indexed vertex/face/color buffers
│   ├── draw.py              # draw_plant() — high-level drawing dispatch
│   ├── params.py            # Parameter containers (pGeneral, pMeristem, …)
│   ├── pla_parser.py        # .pla file parser (parameter registry + embedded TDOs)
│   ├── tdo_parser.py        # .tdo file parser (3D object library)
│   ├── normalize.py         # Post-parse normalization (s-curves, refs, units)
│   ├── factory.py           # create_plant() / grow_species() entry points
│   ├── rng.py               # PdRandom — deterministic LFSR (matches original)
│   ├── math3d.py            # Vector/matrix/SCurve math
│   ├── matrix3d.py          # KfMatrix / KfPoint3D (PlantStudio coords)
│   ├── plant_library.py     # SpeciesLibrary — parsed .pla cache
│   └── defaults.py          # Hard-coded defaults when no .pla loads
├── ui_panel.py              # Blender N-panel (PlantStudio-Blender tab)
├── operators.py             # Blender operators (create, load, save, regrow, export…)
├── wizard.py                # Realtime wizard: knobs ↔ params, live rebuild timer
├── scene_bridge.py          # Mesh build, material creation, collection management
├── animator.py              # Growth animation operator (modal timer)
├── export/                  # glTF/OBJ export (WIP)
├── data/                    # Bundled .pla files + 3D object library.tdo
├── tools/                   # Validation / comparison scripts
└── tests/                   # Pytest suite (mesh output, LOD, parser round-trips)
```

**Key design principle:** the `core/` package is pure Python — no `import bpy`. The Blender bridge lives entirely in the top-level modules (`ui_panel.py`, `operators.py`, `wizard.py`, `scene_bridge.py`, `animator.py`). This makes the simulation testable in CI and reusable outside Blender.

---

## Simulation Model (How Plants Grow)

PlantStudio uses a **meristem-driven, biomass-allocation model**:

1. **Meristems** (apical & axillary) accumulate photosynthetic biomass each day.
2. When a meristem's biomass crosses a threshold, it **creates a phytomer**: an internode + leaf (+ axillary buds).
3. **Branching** is probabilistic: axillary buds activate based on `branchingIndex`, `branchingDistance`, `branchingAngle`, and sympodial/monopodial settings.
4. **Biomass allocation** follows an S-curve (`growthSCurve.c1`, `c2`) toward `ageAtMaturity`. After flowering starts, a fraction (`fractionReproductiveAllocationAtMaturity_frn`) diverts to reproductive structures.
5. **Inflorescences** form on active reproductive meristems (apical or axillary), each with stalk, bracts, and flowers.
6. **Flowers** grow, open, and optionally set fruit based on biomass thresholds and day counts.
7. **Determinism**: a single `PdRandom` (LFSR) seeded from `startingSeedForRandomNumberGenerator` drives every stochastic decision — same seed = identical plant.

The parameter registry (1,000+ entries) maps **field IDs** (e.g., `kGeneralAgeAtMaturity`) to **access strings** (e.g., `pGeneral.ageAtMaturity`). The parser loads this registry once; `.pla` files reference parameters by field ID, so new parameters can be added without breaking old files.

---

## File Formats

| Format | Purpose | Notes |
|--------|---------|-------|
| `.pla` | Plant species definition | Text, Latin-1 encoded. Sections: `[Species Name] start PlantStudio plant <v2.0>` + `Param Name [kFieldID] =value`. Embedded TDO blocks (`start 3D object` … `end 3D object`) for custom parts. |
| `.tdo` | 3D object library | Text. `Name=…`, `Point=x y z`, `Triangle=i j k` (1-based). Also a compact inline form `N[name],P[x y z],T[i j k]…` used in parameters.tab. |
| `.json` (user preset) | Saved wizard state | `{name, category, base_species, knobs: {knob_name: value}}`. Stored under `data/user-presets/<category>/<name>.json`. |
| `.json` (export config) | AR / cloud regeneration | `{plant_id, species, seed, planted_date}` (ISO date). Written to `digital-garden-AR/src/assets/plants/`. |

---

## User Workflow (In Blender)

1. **Open the N-panel** → *PlantStudio-Blender* tab.
2. **New Plant** box:
   - **Load Preset** menu → pick a library species (grouped by category) or a saved user preset.
   - **Seed** spinner (default 280) — changes the stochastic shape.
   - **Create** button → grows a new plant at the current *Age (days)*.
3. **Plant List** — Blender-style `UIList` of all plants in the `PlantStudio Plants` collection. Checkbox = include in export. Select one to edit.
4. **Wizard** (for selected plant) — 8 steps, each a collapsible box with labeled sliders/enum pickers/color pickers:
   - **Meristems** — branching index/distance/angle, determinate probability, sympodial, secondary branching.
   - **Internodes** — length, width, biomass, curving, days to create.
   - **Leaves** — petiole length/width/angle, leaf biomass, leaf size (TDO scale), grow days.
   - **Compound Leaves** — leaflets, pinnate/palmate, rachis:petiole ratio.
   - **Inflorescence Placement** — flowering start age, apical/axillary inflorescence counts, reproductive allocation fraction.
   - **Inflorescence Drawing** — stalk length, flowers on main branch / per branch / branches, days to all flowers.
   - **Flowers** — petals per flower, petal size/angle, flower biomass.
   - **Fruits** — fruit biomass threshold, days to fruit.
   - **Shape pickers** (per step) — choose any TDO library object for bud, leaf, stipule, petal, fruit.
   - **Color picker** — unripe fruit color.
   - **Age (days)** slider — rebuilds at any age instantly.
   - **Save Preset** button → writes a `.json` preset (base species + knob deltas).
5. **Live rebuild** — every knob change triggers a lightweight timer (`bpy.app.timers`) that re-draws the mesh in place (growth-affecting knobs re-simulate; draw-only knobs reuse the cached grown plant).
6. **Export Plant Config** — writes one JSON per checked plant for the digital garden pipeline.
7. **Animate Growth** operator — modal timer that steps the plant day-by-day over frames, updating the timeline.

---

## Making Of / History

| Phase | What Happened |
|-------|---------------|
| **Original (1997–2000s)** | PlantStudio written in Delphi/Object Pascal by Kurtz-Fernhout Software. Sold as shareware; later released free. Simulates herbaceous plants using a meristem/biomass model with 1,000+ parameters. |
| **Open-source release (2020s)** | Paul Fernhout (`pdfernhout`) published the source on GitHub (`github.com/pdfernhout/PlantStudio`) — Delphi code, `.pla`/`.tdo` specs, parameter registry, and the full species library. |
| **Python port (2024–2025)** | A clean-room Python 3 port of the simulation core (`PdPlant`, `PdMeristem`, `PdInternode`, `PdLeaf`, `PdInflorescence`, `PdFlowerFruit`, `PdRandom`, 3D math, parser, normalizer) — zero Blender deps. Validated against original `.pla` files: same seed → same vertex count / topology. |
| **Blender addon wrapper (2025–2026)** | Built the Blender bridge: `MeshTurtle` → `MeshBuffer` → `bpy.mesh`, material per color, collection management, wizard PropertyGroups, live timer rebuild, preset I/O, export operator. Bundled the 9 `.pla` files + `3D object library.tdo` from the original repo. |
| **LOD system (2026, in progress)** | Planned three-level LOD (triangle subsampling, pipe face reduction, repetition halving) exposed in UI and export — see `LOD_PLAN.md`. |
| **Digital-garden sync (2026)** | `scripts/sync_addon.py` pushes the headless `core/` subset to a companion repo (`digital-garden`) for cloud regeneration; VS Code task for one-button sync. |

---

## Development

```bash
# Run tests (headless, no Blender needed)
cd C:/Users/vitvin_v/dev/plantstudio-blender
python -m pytest plantstudio_blender/tests/ -q

# Install in Blender (developer mode)
# 1. Edit → Preferences → Add-ons → Install from Disk → select plantstudio_blender.zip
# 2. Enable "PlantStudio-Blender"
# 3. N-panel → PlantStudio-Blender tab

# Sync headless core to digital-garden mirror
python scripts/sync_addon.py
```

**Requirements:** Python 3.11+, Blender 4.2 LTS or 5.x LTS. No external Python packages (stdlib only).

---

## License

GPL-3.0 — see `LICENSE`. The original PlantStudio source (Delphi) is © Kurtz-Fernhout Software, used with permission / under its original freeware terms. The Python port and Blender addon are derivative works.
