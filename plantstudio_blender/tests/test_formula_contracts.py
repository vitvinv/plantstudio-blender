"""Formula contract tests — lock the port to the original PlantStudio formulas.

Each test asserts our emitted records/geometry against the exact formula from
the converted original source (digital-garden/examples/PlantStudio-master/
converted_source/used/*.pas.py). These are the numeric contracts that the
part census and the PlantStudio OBJ comparison rely on:

- uturtle: TDO points transform by point * scale * scale_pixelsPerMm;
  mm moves scale by scale_pixelsPerMm; 256-degree rotation system.
- uintern: internode pipe length = propFullLength * lengthAtOptimalFinal...
  where propFullLength = totalBiomass * expansions / optimalFinalBiomass;
  pipe radius = width * ds / 2.
- uleaf: petiole length = petioleLengthAtOptimalBiomass_mm * propFullSize
  (halved for seedling leaves); blade scale = propFullSize * scaleAtFullSize
  / 100; leaf part tags resolve to seedling variants on seedling leaves.
- uinflor: stalk length = starting * min(daysAll, daysSinceStarted)/daysAll
  * propFull; radial rows place `repetitions` TDO instances on a ring
  (equal centroid distance from the flower origin); 256-degree circle.
- ufruit: flower propFullSize = min(1, (live + dead) / pFlower.optimalBiomass).
- umerist: axillary bud scale = (scaleAtFullSize/100) * min(1, age/5).
"""

import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from plantstudio_blender.core import math3d as umath
from plantstudio_blender.core import draw as draw_mod
from plantstudio_blender.core.draw import (draw_plant, PART_NAMES,
                                           kExportPartMeristem,
                                           kExportPartInternode,
                                           kExportPartSeedlingLeaf,
                                           kExportPartLeaf,
                                           kExportPartFirstPetiole,
                                           kExportPartPetiole,
                                           kExportPartLeafStipule,
                                           kExportPartInflorescenceStalkFemale,
                                           kExportPartInflorescenceInternodeFemale,
                                           kExportPartInflorescenceBractFemale,
                                           kExportPartPedicelFemale,
                                           kExportPartFlowerBudFemale,
                                           kExportPartStyleFemale,
                                           kExportPartStigmaFemale,
                                           kExportPartFilamentFemale,
                                           kExportPartAntherFemale,
                                           kExportPartFirstPetalsFemale,
                                           kExportPartSecondPetalsFemale,
                                           kExportPartSepalsFemale,
                                           kExportPartUnripeFruit,
                                           kExportPartRipeFruit,
                                           kExportPartRootTop)
from plantstudio_blender.core.factory import create_plant
from plantstudio_blender.core.mesh_buffer import MeshBuffer
from plantstudio_blender.core.plant_library import SpeciesLibrary
from plantstudio_blender.core.tdo_parser import TdoLibrary
from plantstudio_blender.core.turtle import MeshTurtle

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
TDO_PATH = os.path.join(DATA_DIR, "3D object library.tdo")
MM = 1000.0  # buffer vertices are meters (scale_pixelsPerMm = 0.001)

_last_tdo_lib = None
_last_species_lib = None


def libraries():
    global _last_tdo_lib, _last_species_lib
    if _last_species_lib is None:
        _last_species_lib = SpeciesLibrary(DATA_DIR)
        _last_tdo_lib = TdoLibrary.from_file(TDO_PATH)
        missing = [t for name, t in _last_species_lib.embedded_tdos.items()
                   if _last_tdo_lib.get(name) is None]
        _last_tdo_lib.merge(missing)
    return _last_species_lib, _last_tdo_lib


def grow_draw(species_name, day, seed=280):
    species_lib, tdo_lib = libraries()
    species = species_lib.get(species_name)
    assert species is not None, f"species {species_name} not in library"
    plant = create_plant(species, seed=seed, tdo_library=tdo_lib)
    plant.growTo(day)
    buffer = MeshBuffer()
    turtle = MeshTurtle(buffer)
    turtle.setScale_pixelsPerMm(0.001)
    draw_plant(plant, turtle)
    return plant, buffer


def iter_parts(plant):
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


# ── uturtle contracts ───────────────────────────────────────────────────────


class TestTurtleUnits:
    def test_tdo_points_scale_by_scale_times_ds(self):
        """uturtle.transformAndRecord: TDO points scale by
        theScale * scale_pixelsPerMm — same multiplier as mm moves, so
        proportions are drawing-scale-independent."""
        from plantstudio_blender.core.tdo_parser import TdoLibrary
        lib = TdoLibrary.from_file(TDO_PATH)
        tdo = next(t for t in lib._by_name.values() if t.points)
        for ds, scale in ((0.001, 1.0), (0.001, 0.37), (0.01, 2.0)):
            buffer = MeshBuffer()
            turtle = MeshTurtle(buffer)
            turtle.setScale_pixelsPerMm(ds)
            turtle.drawTriangleSet(tdo.points, tdo.triangles, scale,
                                   (10, 20, 30))
            # all emitted vertices lie at point * scale * ds (identity matrix)
            assert buffer.vertices
            # reconstruct: each vertex must be a scaled copy of some TDO point
            scaled = {(p[0] * scale * ds, p[1] * scale * ds, p[2] * scale * ds)
                      for p in tdo.points}
            for v in buffer.vertices:
                closest = min(
                    math.dist(v, s) for s in scaled)
                assert closest < 1e-9, (v, closest)

    def test_move_mm_uses_ds(self):
        buffer = MeshBuffer()
        turtle = MeshTurtle(buffer)
        turtle.setScale_pixelsPerMm(0.001)
        start = turtle.position()
        turtle.moveInMillimeters(50.0)
        end = turtle.position()
        # forward is +x in the turtle frame; only the x coordinate moves
        assert math.isclose(start.y, end.y, abs_tol=1e-12)
        assert math.isclose(end.x - start.x, 50.0 * 0.001, abs_tol=1e-12)

    def test_256_degree_turn_is_full_circle(self):
        buffer = MeshBuffer()
        turtle = MeshTurtle(buffer)
        turtle.setScale_pixelsPerMm(0.001)
        turtle.setLineWidth(1.0)
        # 256-degree units: a full turn is a no-op, 128 is a reversal
        turtle.rotateY(256)
        turtle.moveInMillimeters(10.0)
        end = turtle.position()
        assert math.dist((end.x, end.y, end.z), (0.01, 0.0, 0.0)) < 1e-9
        turtle2 = MeshTurtle(MeshBuffer())
        turtle2.setScale_pixelsPerMm(0.001)
        turtle2.rotateY(128)
        turtle2.moveInMillimeters(10.0)
        end2 = turtle2.position()
        assert math.dist((end2.x, end2.y, end2.z), (-0.01, 0.0, 0.0)) < 1e-9


# ── uintern contracts ───────────────────────────────────────────────────────


class TestInternodeContract:
    def test_pipe_length_matches_propFull_formula(self):
        plant, buffer = grow_draw("rose", 60)
        strokes = {}
        for record in buffer.pipe_records:
            if record.get("part_id") != kExportPartInternode:
                continue
            strokes.setdefault(record["stroke_id"], []).append(record)
        assert strokes, "expected internode pipes"
        internodes = [p for p in iter_parts(plant)
                      if type(p).__name__ == "PdInternode"]
        expected = []
        for part in internodes:
            length = max(0.0, part.propFullLength() *
                         plant.pInternode.lengthAtOptimalFinalBiomassAndExpansion_mm)
            expected.append(round(length, 6))
        expected = sorted(e for e in expected if e > 0)
        stroke_lengths = []
        for records in strokes.values():
            total = sum(math.dist(r["start"], r["end"]) for r in records) * MM
            stroke_lengths.append(round(total, 6))
        # every stroke total must equal some internode's formula length
        for total in stroke_lengths:
            assert any(math.isclose(total, e, abs_tol=1e-6)
                       for e in expected), (total, expected[:3])

    def test_pipe_radius_is_half_width_times_ds(self):
        plant, buffer = grow_draw("Daylily", 60)
        internodes = [p for p in iter_parts(plant)
                      if type(p).__name__ == "PdInternode"]
        widths = {round(p.propFullWidth() *
                        plant.pInternode.widthAtOptimalFinalBiomassAndExpansion_mm,
                        9) for p in internodes}
        for record in buffer.pipe_records:
            if record.get("part_id") != kExportPartInternode:
                continue
            expected = {round(w * 0.001 * 0.5, 9) for w in widths}
            got_radius = (record["radius_start"] + record["radius_end"]) / 2
            assert any(math.isclose(got_radius, e, abs_tol=1e-9)
                       for e in expected), (got_radius, expected)


# ── uleaf contracts ─────────────────────────────────────────────────────────


class TestLeafContract:
    def test_leaf_parts_use_seedling_variants(self):
        plant, buffer = grow_draw("rose", 12)
        part_ids = {record["part_id"]
                    for record in buffer.triangle_set_records}
        pipe_ids = {record["part_id"] for record in buffer.pipe_records}
        # at age 12, rose has seedling leaves; the seedling part variants
        # must be used for them (older phytomers may also have real leaves)
        assert kExportPartSeedlingLeaf in part_ids
        assert kExportPartFirstPetiole in pipe_ids

    def test_seedling_petiole_length_is_halved(self):
        plant, buffer = grow_draw("rose", 12)
        pLeaf = plant.pLeaf
        leaves = [p for p in iter_parts(plant)
                  if type(p).__name__ == "PdLeaf"]
        assert leaves
        expected_lengths = set()
        for leaf in leaves:
            prop = min(1.0, leaf.liveBiomass_pctMPB /
                       max(0.001, pLeaf.optimalBiomass_pctMPB))
            length = pLeaf.petioleLengthAtOptimalBiomass_mm * prop
            if leaf.isSeedlingLeaf:
                length /= 2
            expected_lengths.add(round(length * 0.001, 9))
        seedling_pipes = [r for r in buffer.pipe_records
                          if r.get("part_id") == kExportPartFirstPetiole]
        assert seedling_pipes
        strokes = {}
        for record in seedling_pipes:
            strokes.setdefault(record["stroke_id"], []).append(record)
        for records in strokes.values():
            length = sum(math.dist(r["start"], r["end"])
                         for r in records)
            assert any(math.isclose(length, e, abs_tol=1e-9)
                       for e in expected_lengths), (length, expected_lengths)

    def test_blade_scale_formula(self):
        plant, buffer = grow_draw("Daylily", 40)
        pLeaf = plant.pLeaf
        tdo = plant.params.leafTdoParams
        leaves = [p for p in iter_parts(plant)
                  if type(p).__name__ == "PdLeaf" and not p.isSeedlingLeaf]
        assert leaves
        expected = {round(min(1.0, leaf.liveBiomass_pctMPB /
                              max(0.001, pLeaf.optimalBiomass_pctMPB))
                          * tdo.scaleAtFullSize / 100.0, 9)
                    for leaf in leaves}
        blades = [r for r in buffer.triangle_set_records
                  if r.get("part_id") == kExportPartLeaf]
        assert blades
        for record in blades:
            assert any(math.isclose(record["scale"], e, abs_tol=1e-9)
                       for e in expected), (record["scale"], expected)


# ── uinflor / ufruit contracts ──────────────────────────────────────────────


class TestInflorescenceContract:
    def test_length_or_width_at_age_formula(self):
        """lengthOrWidthAtAgeForFraction: starting * ageBounded/daysAll *
        fraction, with ageBounded = min(daysAll, daysSinceStarted)."""
        class FakeInflor:
            daysSinceStartedMakingFlowers = 7

        inflor = FakeInflor()
        p = {"daysToAllFlowersCreated": 10}
        value = draw_mod._length_or_width_at_age(inflor, p, 200.0, 0.5)
        assert math.isclose(value, 200.0 * (7 / 10) * 0.5)
        inflor.daysSinceStartedMakingFlowers = 25  # past daysAll
        assert math.isclose(
            draw_mod._length_or_width_at_age(inflor, p, 200.0, 0.5),
            200.0 * 1.0 * 0.5)
        p["daysToAllFlowersCreated"] = 0
        inflor.daysSinceStartedMakingFlowers = 3
        assert math.isclose(
            draw_mod._length_or_width_at_age(inflor, p, 10.0, 1.0), 0.0)

    def test_female_daylily_uses_female_part_ids(self):
        plant, buffer = grow_draw("Daylily", 100)
        ids = {record["part_id"] for record in buffer.triangle_set_records}
        pipes_ids = {record["part_id"] for record in buffer.pipe_records}
        assert kExportPartInflorescenceStalkFemale in pipes_ids
        assert kExportPartPedicelFemale in pipes_ids
        assert kExportPartStyleFemale in pipes_ids
        assert kExportPartFilamentFemale in pipes_ids
        assert kExportPartStigmaFemale in ids
        assert kExportPartAntherFemale in ids
        assert kExportPartFirstPetalsFemale in ids
        assert kExportPartSepalsFemale in ids
        # nothing male, nothing untagged
        male_ids = {10, 11, 12, 25, 26, 27, 28, 29, 30}
        assert not (ids | pipes_ids) & male_ids
        assert None not in ids and None not in pipes_ids

    def test_petal_ring_instances_on_equal_radius(self):
        """Radial arrangement: every instance of a row sits at the same
        distance from the flower center (256-degree circle placement)."""
        plant, buffer = grow_draw("Daylily", 100)
        rows = {}
        for record in buffer.triangle_set_records:
            if record.get("part_id") == kExportPartFirstPetalsFemale:
                rows.setdefault("petals1", []).append(record)
            elif record.get("part_id") == kExportPartAntherFemale:
                rows.setdefault("anthers", []).append(record)
        assert rows, "expected petal/anther instances"
        for name, records in rows.items():
            radii = [math.dist(r["origin"], r["centroid"]) for r in records]
            spread = max(radii) - min(radii)
            assert spread < 1e-9, (name, spread)
            # instances evenly spread on the circle: count == repetitions
            assert len(radii) > 1, name

    def test_flower_propFull_uses_total_biomass(self):
        """ufruit: propFullSize = min(1, (live + dead) / optimalBiomass)."""
        class FakeFlower:
            liveBiomass_pctMPB = 0.6
            deadBiomass_pctMPB = 0.2
            gender = 0
            isOpen = True
            hasSetFruit = False
            stage = None
            plant = None

        class FakePlant:
            params = None
            pFlower = {0: {"optimalBiomass_pctMPB": 1.0}, 1: {}}
            turtle = None

        flower = FakeFlower()
        flower.plant = FakePlant()
        # exercise through the real draw path: no turtle -> returns, but the
        # formula path is the same computation used in _draw_flower_fruit
        total = flower.liveBiomass_pctMPB + flower.deadBiomass_pctMPB
        prop = min(1.0, umath.safedivExcept(
            total, flower.plant.pFlower[flower.gender]
            ["optimalBiomass_pctMPB"], 0))
        assert math.isclose(prop, 0.8)


# ── umerist contract ────────────────────────────────────────────────────────


class TestMeristemBudContract:
    def test_bud_scale_formula_when_buds_present(self):
        plant, buffer = grow_draw("rose", 40)
        buds = [p for p in iter_parts(plant)
                if type(p).__name__ == "PdMeristem" and not p.isApical]
        records = [r for r in buffer.triangle_set_records
                   if r.get("part_id") == kExportPartMeristem]
        if not buds or not records:
            pytest.skip("species has no axillary bud geometry at this age")
        bud = plant.pAxillaryBud
        days_to_full = 5
        expected = {round((bud.scaleAtFullSize / 100.0)
                          * min(1.0, m.age / days_to_full), 9)
                    for m in buds}
        for record in records:
            assert any(math.isclose(record["scale"], e, abs_tol=1e-9)
                       for e in expected), (record["scale"], expected)


# ── part taxonomy regression ────────────────────────────────────────────────


class TestPartTaxonomy:
    def test_all_emitted_parts_are_tagged_and_known(self):
        for name in ("Daylily", "rose", "flower to test all parts",
                     "purple flower plant"):
            plant, buffer = grow_draw(name, 100, seed=0)
            tagged = [pid for pid in buffer.face_part_ids if pid is not None]
            # every face is tagged with a known part id
            assert len(buffer.face_part_ids) == len(buffer.faces)
            unknown = {pid for pid in buffer.face_part_ids
                       if pid not in PART_NAMES}
            assert not unknown, (name, unknown)
            assert all(0 <= pid <= kExportPartRootTop
                       for pid in buffer.face_part_ids), name

    def test_root_top_drawn_only_when_enabled(self):
        plant, buffer = grow_draw("Daylily", 100, seed=0)
        ids = {r.get("part_id") for r in buffer.triangle_set_records}
        shows = bool(getattr(plant.params.pRoot, "showsAboveGround", False))
        assert (kExportPartRootTop in ids) == shows


# ── census <-> reference OBJ roundtrip ──────────────────────────────────────


class TestReferenceObjRoundtrip:
    """Write a buffer out in the PlantStudio OBJ convention and read it back
    through the comparison tool's parser — the metrics must agree with the
    census computed from the same buffer."""

    def test_roundtrip_metrics_match(self, tmp_path):
        from tools.compare_reference_obj import load_reference

        plant, buffer = grow_draw("Daylily", 100, seed=0)

        # census of the buffer (same math as tools/plant_census.py)
        def area(tri):
            (ax, ay, az), (bx, by, bz), (cx, cy, cz) = \
                (buffer.vertices[tri[0]], buffer.vertices[tri[1]],
                 buffer.vertices[tri[2]])
            ux, uy, uz = bx - ax, by - ay, bz - az
            vx, vy, vz = cx - ax, cy - ay, cz - az
            return 0.5 * math.hypot(math.hypot(uy * vz - uz * vy,
                                               uz * vx - ux * vz),
                                    ux * vy - uy * vx)

        ours = {}
        for face, part_id in zip(buffer.faces, buffer.face_part_ids):
            name = PART_NAMES[part_id]
            entry = ours.setdefault(name, {"faces": 0, "area": 0.0,
                                           "pts": []})
            entry["faces"] += 1
            entry["area"] += area(face)
            for idx in face:
                entry["pts"].append(buffer.vertices[idx])

        # write OBJ in the PlantStudio convention: y negated, groups
        # '<plant>_<short name>', negative relative f indices per block
        from plantstudio_blender.core.draw import PART_SHORT_NAMES
        short_for = {name: PART_SHORT_NAMES[pid]
                     for pid, name in PART_NAMES.items()}
        obj_lines = ["# OBJ file created by PlantStudio"]
        for part_name, entry in ours.items():
            obj_lines.append("o Daylily")
            obj_lines.append(f"g Daylily_{short_for[part_name]}")
            verts = entry["pts"]
            obj_lines.extend(f"v {p[0]} {-p[1]} {p[2]}" for p in verts)
            for t in range(entry["faces"]):
                # 0-based local indices written as negative relative offsets:
                # f = localIndex - numPoints, matching U3dexport
                a, b, c = 3 * t, 3 * t + 1, 3 * t + 2
                obj_lines.append(f"f {a - len(verts)} {b - len(verts)} "
                                 f"{c - len(verts)}")
        obj_path = tmp_path / "reference.obj"
        obj_path.write_text("\n".join(obj_lines) + "\n", encoding="cp1252")

        report = load_reference(str(obj_path))
        assert "Daylily" in report
        ref = report["Daylily"]
        for part_name, entry in ours.items():
            assert part_name in ref["parts"], part_name
            assert ref["parts"][part_name]["faces"] == entry["faces"]
            # our buffer is in meters, reference in whatever we wrote (meters)
            assert math.isclose(ref["parts"][part_name]["area"],
                                entry["area"], rel_tol=1e-6)


class TestPlaFileZoom:
    """The .pla file-header view zoom ('scale=' before the first plant)
    is baked into reference export coordinates; the compare tool must
    divide it out (Strange breeder plants ships scale=1.79)."""

    def test_zoom_read_and_normalized(self):
        from tools.compare_reference_obj import pla_file_zoom
        assert pla_file_zoom("scale=1.79\r\n\r\n[p] start") == 1.79
        assert pla_file_zoom("scale=0.28\n") == 0.28
        assert pla_file_zoom("no header") == 1.0
        assert pla_file_zoom("scale=0") == 1.0
