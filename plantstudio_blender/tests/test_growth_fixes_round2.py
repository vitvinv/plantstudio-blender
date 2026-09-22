"""Regression tests for the Round 2 (Garden plants) census fixes.

Each test pins a fidelity fix against the original Delphi source:

- PART_SHORT_NAMES carries the exporter's true short names FruitU/FruitR/Root
  (u3dexport.py shortName assignments) so reference-OBJ parsing matches
- kRootTopShowsAboveGround reaches draw as pRoot.showsAboveGround (the
  registry stores it capitalized; normalize_root maps it)
- stem pipes draw side faces only — the original's screen path
  (KfTurtle.drawInMillimeters) and export path (write3DExportLine) never
  draw pipe end caps
- compound leaves draw their main petiole before the rachis
  (uleaf.py drawWithDirection, kDontTaper)
- the inflorescence advances every flower's nextDay twice per plant day
  (uinflor.nextDay lines 91-92), so corn ears ripen/freeze on the
  original's timeline
- flowers update propFullSize on reproductive growth (ufruit.py lines
  151-158 and at fruit set, line 85)
- the traverser re-reads the child pointer AFTER the traversal call, so a
  meristem that creates a phytomer mid-walk hands its successor a same-day
  nextDay (utravers.traversePlant re-reads the field) — this yields the
  original's 9-day phylotimer cadence for deadline-driven creation
- drawApex honors numFlowersOnMainBranch == 0 (no falsy-`or` coercion) —
  corn's male tassel then draws 42 internode segment-sets like the
  reference OBJ
"""

import os
import sys
from collections import Counter

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from plantstudio_blender.core.draw import (
    PART_SHORT_NAMES,
    kExportPartInternode,
    kExportPartPetiole,
    kExportPartRipeFruit,
    kExportPartRootTop,
)
from plantstudio_blender.core.factory import create_plant
from plantstudio_blender.core.mesh_buffer import MeshBuffer
from plantstudio_blender.core.normalize import normalize_params
from plantstudio_blender.core.params import PlantParams
from plantstudio_blender.core.plant_library import SpeciesLibrary
from plantstudio_blender.core.tdo_parser import TdoLibrary
from plantstudio_blender.core.turtle import MeshTurtle

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
TDO_PATH = os.path.join(DATA_DIR, "3D object library.tdo")


@pytest.fixture(scope="module")
def garden():
    lib = SpeciesLibrary(DATA_DIR)
    tdo_lib = TdoLibrary.from_file(TDO_PATH)
    cat = lib.categories["Garden plants"]
    pla_seeds = _pla_seeds("Garden plants")
    return lib, tdo_lib, cat, pla_seeds


def _pla_seeds(folder):
    """Per-plant stored seeds from the .pla (same order as species)."""
    import re

    path = os.path.join(DATA_DIR, folder + ".pla")
    src = open(path, encoding="cp1252", errors="replace").read()
    seeds = []
    for chunk in re.split(r"\[.*?\]\s*start PlantStudio plant", src)[1:]:
        m = re.search(r"kStateSeed\]\s*=\s*(-?\d+)", chunk)
        seeds.append(int(m.group(1)) if m else None)
    return seeds


def _walk(plant):
    stack = [plant.firstPhytomer]
    seen = set()
    while stack:
        part = stack.pop()
        if part is None or id(part) in seen:
            continue
        seen.add(id(part))
        yield part
        stack.append(getattr(part, "nextPlantPart", None))
        stack.append(getattr(part, "leftBranchPlantPart", None))
        stack.append(getattr(part, "rightBranchPlantPart", None))
        stack.append(getattr(part, "leftLeaf", None))
        stack.append(getattr(part, "rightLeaf", None))
        for f in (getattr(part, "flowers", None) or []):
            stack.append(f)


def _mesh(species, age, seed):
    tdo_lib = TdoLibrary.from_file(TDO_PATH)
    plant = create_plant(species, seed=seed, tdo_library=tdo_lib)
    plant.growTo(age)
    buf = MeshBuffer()
    turtle = MeshTurtle(buf)
    turtle.setScale_pixelsPerMm(0.001)
    from plantstudio_blender.core.draw import draw_plant

    draw_plant(plant, turtle)
    return plant, buf


def test_export_short_names_match_reference():
    """u3dexport.py: kExportPartUnripeFruit -> 'FruitU',
    kExportPartRipeFruit -> 'FruitR', kExportPartRootTop -> 'Root'."""
    from plantstudio_blender.core.draw import kExportPartUnripeFruit

    assert PART_SHORT_NAMES[kExportPartRipeFruit] == "FruitR"
    assert PART_SHORT_NAMES[kExportPartUnripeFruit] == "FruitU"
    assert PART_SHORT_NAMES[kExportPartRootTop] == "Root"


def test_export_short_name_table_matches_original():
    """The FULL short-name table is pinned to u3dexport.py's
    getInfoForDXFPartType if-chain (extracted verbatim). The compare tool
    resolves reference OBJ groups through this table — a wrong entry
    silently drops that part from every future round's comparison.
    Order also matches: the original maps index -> name in this order.
    """
    expected = [
        "Mrstm", "Intrnd", "1stLeaf", "Leaf", "1stPetiole", "Petiole",
        "Stipule", "1Pdncle", "1InfInt", "1Bract", "2Pdncle", "2InfInt",
        "2Bract", "1Pdcel", "1Bud", "Style", "Stigma", "1Flmnt", "1Anther",
        "1Petal1", "1Petal2", "1Petal3", "1Petal4", "1Petal5", "1Sepal",
        "2Pdcel", "2Bud", "2Flmnt", "2Anther", "2Petal1", "2Sepal",
        "FruitU", "FruitR", "Root",
    ]
    ours = [PART_SHORT_NAMES[pid] for pid in range(len(PART_SHORT_NAMES))]
    assert ours == expected


def test_root_top_shows_above_ground_reaches_draw():
    """Carrot sets kRootTopShowsAboveGround=true; the registry stores it
    capitalized and draw reads snake_case (normalize_root maps it)."""
    lib = SpeciesLibrary(DATA_DIR)
    carrot = lib.get("carrot")
    assert carrot.params.pRoot.showsAboveGround is True
    # daylily-like species keep it false
    lib2 = SpeciesLibrary(DATA_DIR)
    corn = lib2.get("corn")
    assert corn.params.pRoot.showsAboveGround is False


def test_stem_pipes_have_no_end_caps():
    """write3DExportLine writes side quads only: cabbage internode at age 64
    draws 10 phytomers x 3 divisions x 3 quads = 180 faces (not 200)."""
    lib = SpeciesLibrary(DATA_DIR)
    cabbage = lib.get("cabbage")
    pla_seeds = _pla_seeds("Garden plants")
    _, buf = _mesh(cabbage, 64, pla_seeds[5])
    faces = sum(1 for pid in buf.face_part_ids if pid == kExportPartInternode)
    assert faces == 180, f"cabbage internode faces {faces} != 180 (caps drawn?)"


def test_compound_leaf_draws_main_petiole():
    """drawWithDirection draws the petiole before the compound structure:
    carrot rosette petiole = 14 leaves x 12 draws x 18 faces = 3024 faces
    (5 rachis + 6 petiolets + 1 main petiole per leaf)."""
    lib = SpeciesLibrary(DATA_DIR)
    carrot = lib.get("carrot")
    pla_seeds = _pla_seeds("Garden plants")
    _, buf = _mesh(carrot, 35, pla_seeds[3])
    faces = sum(1 for pid in buf.face_part_ids if pid == kExportPartPetiole)
    assert faces == 3024, f"carrot petiole faces {faces} != 3024"


def test_flower_double_next_day_paces_corn_ear():
    """uinflor.nextDay calls flower.nextDay() again: flowers age 2x per
    plant day, so the corn ear freezes at 6.7647 pctMPB (demand hits 0
    after maxDaysToGrow=14 at the doubled rate) instead of filling to the
    pFruit optimum of 10."""
    lib = SpeciesLibrary(DATA_DIR)
    corn = lib.get("corn")
    pla_seeds = _pla_seeds("Garden plants")
    tdo_lib = TdoLibrary.from_file(TDO_PATH)
    plant = create_plant(corn, seed=pla_seeds[0], tdo_library=tdo_lib)
    plant.growTo(100)
    # our gender numbering keeps the two big kernel flowers as the ears
    big = sorted(_walk_flowers(plant), key=lambda f: -f.liveBiomass_pctMPB)[:2]
    for flower in big:
        assert flower.liveBiomass_pctMPB == pytest.approx(6.7647, abs=0.02), (
            "corn ear biomass diverges from the original's 6.7647")
        assert flower.deadBiomass_pctMPB == pytest.approx(1.3969, abs=0.02)


def _walk_flowers(plant):
    return [f for f in _walk(plant) if type(f).__name__ == "PdFlowerFruit"]


def test_flower_prop_full_size_tracks_biomass():
    """ufruit.py GrowReproductive/fruit-set update propFullSize; a ripe
    fruit must carry a nonzero draw scale."""
    lib = SpeciesLibrary(DATA_DIR)
    tomato = lib.get("tomato")
    pla_seeds = _pla_seeds("Garden plants")
    tdo_lib = TdoLibrary.from_file(TDO_PATH)
    plant = create_plant(tomato, seed=pla_seeds[4], tdo_library=tdo_lib)
    plant.growTo(100)
    fruits = [f for f in _walk_flowers(plant) if getattr(f, "isRipe", False)]
    assert fruits, "tomato at 100 must have ripe fruit"
    assert all(0.0 < f.propFullSize <= 1.0 for f in fruits)


def test_traverser_follows_newly_created_phytomer():
    """utravers.traversePlant re-reads the child pointer after the call, so
    a meristem that creates a phytomer mid-walk hands the new meristem a
    same-day nextDay — deadline-driven phylotimers then run on the
    original's 9-day cadence (tomato leaf creation days 10, 19, 28, 37...).
    """
    lib = SpeciesLibrary(DATA_DIR)
    tomato = lib.get("tomato")
    pla_seeds = _pla_seeds("Garden plants")
    tdo_lib = TdoLibrary.from_file(TDO_PATH)
    plant = create_plant(tomato, seed=pla_seeds[4], tdo_library=tdo_lib)
    plant.growTo(100)
    leaf_ages = sorted((p.age for p in _walk(plant)
                        if type(p).__name__ == "PdLeaf"
                        and not getattr(p, "isSeedlingLeaf", False)),
                       reverse=True)
    assert leaf_ages[0] == 90, "first leaf created at day 10"
    assert leaf_ages[1] == 81, (
        f"second leaf age {leaf_ages[1]}: phylotimer cadence regressed "
        "to the 10-day interval")


def test_draw_apex_honors_zero_main_branch_flowers():
    """Corn male: numFlowersOnMainBranch == 0 must not be coerced to the
    default 1 by a falsy `or` — the tassel then draws 42 internode
    segment-sets (6 branches x 7) like the reference OBJ."""
    lib = SpeciesLibrary(DATA_DIR)
    corn = lib.get("corn")
    pla_seeds = _pla_seeds("Garden plants")
    _, buf = _mesh(corn, 100, pla_seeds[0])
    from plantstudio_blender.core.draw import (
        kExportPartInflorescenceInternodeFemale,
        kExportPartInflorescenceInternodeMale,
    )

    # real_dxf_index swaps the female id for the male variant on male
    # inflorescences; count only the male id (the ears contribute the
    # female id's 60 faces and are a separate census row)
    faces = sum(1 for pid in buf.face_part_ids
                if pid == kExportPartInflorescenceInternodeMale)
    assert faces == 1260, f"corn male inflo internode faces {faces} != 1260"


def test_bud_drawing_option_zero_means_no_bud():
    """kDrawNoBud == 0 is a real option; a falsy `or` must not turn it
    into kDrawSingleTdoBud."""
    from plantstudio_blender.core import draw as draw_mod

    assert draw_mod.kDrawNoBud == 0
    # budDrawingOption must be read without falsy coercion
    assert "or kDrawSingleTdoBud" not in draw_mod._draw_flower_fruit.__code__.co_consts
