"""Regression tests for the Round 4 (Garden flowers) census fixes.

Each test pins a fidelity fix against the original Delphi source:

- PdInternode.calculateInternodeAngle consumes randomNormalPercent per
  phytomer and bakes sway in (uintern.py:293-304):
  angle = 64/100 * randomNormalPercent(curvingIndex) in 256-degree turtle
  units, then + (randomSwayIndex - 0.5) * pGeneral.randomSway. A curving
  index of 0 draws nothing and stores 0 (+ sway). The deterministic
  (ci/100)*90 simplification desynced the whole RNG stream for every
  species with a nonzero curving index.
- willCreateInflorescence passes the inactive-meristem count to
  safedivExcept raw (a 0 divisor yields the 0 fallback, prob 0 -> False);
  the max(1, ...) guard and int() truncation of numExpected diverged from
  the original (umerist.py willCreateInflorescence).
- decideIfActiveFemale keeps the male-override RNG draw: a male meristem
  whose apical/axillary state matches the female inflorescence flips to
  female only half the time (umerist.py decideIfActiveFemale).
"""

import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from plantstudio_blender.core.factory import create_plant
from plantstudio_blender.core.meristem import kGenderFemale, kGenderMale
from plantstudio_blender.core.plant_library import SpeciesLibrary
from plantstudio_blender.core.rng import PdRandom
from plantstudio_blender.core.tdo_parser import TdoLibrary

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
TDO_PATH = os.path.join(DATA_DIR, "3D object library.tdo")

GILIA_DAY1_SEED = 1176778604  # 128 draws from seed 482 (ps3 original)


def _pla_seed(folder, name):
    path = os.path.join(DATA_DIR, folder + ".pla")
    src = open(path, encoding="cp1252", errors="replace").read()
    chunks = re.split(r"\[(.*?)\]\s*start PlantStudio plant", src)
    for i in range(1, len(chunks), 2):
        if chunks[i] == name:
            m = re.search(
                r"kGeneralStartingSeedForRandomNumberGenerator\]\s*=\s*(-?\d+)",
                chunks[i + 1])
            if m:
                return int(m.group(1))
    raise AssertionError(f"seed for {name!r} not found in {folder}.pla")


@pytest.fixture(scope="module")
def gilia():
    lib = SpeciesLibrary(DATA_DIR)
    tdo_lib = TdoLibrary.from_file(TDO_PATH)
    species = next(s for s in lib.categories["Garden flowers"]
                   if s.name == "gilia")
    return create_plant(species, seed=_pla_seed("Garden flowers", "gilia"),
                        tdo_library=tdo_lib)


def test_curving_angle_draws_rng_on_day_one(gilia):
    """Day 1 consumes 104 structural draws + 2 x 12 curving-angle draws
    (creation with curvingIndex, then setAsFirstPhytomer with
    firstInternodeCurvingIndex) = 128 draws total, exactly like the
    original's uintern.calculateInternodeAngle."""
    gilia.reset()
    gilia.nextDay()
    assert gilia.randomNumberGenerator.seed == GILIA_DAY1_SEED


def test_curving_angle_formula_and_sway():
    """angle = 64/100 * randomNormalPercent(ci) + sway, baked at creation;
    curvingIndex 0 stores 0 without consuming a draw."""
    from plantstudio_blender.core.internode import PdInternode

    plant = type("FakePlant", (), {})()
    rng = PdRandom()
    rng.setSeed(12345)
    draws = []

    def fake_percent(mean):
        draws.append(mean)
        return 40.0

    rng.randomNormalPercent = fake_percent
    plant.randomNumberGenerator = rng
    plant.pInternode = type("P", (), {})()
    plant.pInternode.curvingIndex = 25.0
    plant.pInternode.firstInternodeCurvingIndex = 10.0
    plant.pGeneral = type("G", (), {})()
    plant.pGeneral.randomSway = 0.0

    node = PdInternode(plant)
    node.randomSwayIndex = 0.5
    node.calculateInternodeAngle()
    assert draws == [25.0]
    assert node.internodeAngle == pytest.approx(0.64 * 40.0)

    # sway is added from the stored index
    plant.pGeneral.randomSway = 20.0
    node.randomSwayIndex = 0.75
    node.calculateInternodeAngle()
    assert node.internodeAngle == pytest.approx(0.64 * 40.0 + 0.25 * 20.0)

    # curving index 0: no draw, angle 0 (+ sway)
    draws.clear()
    plant.pInternode.curvingIndex = 0.0
    node.calculateInternodeAngle()
    assert draws == []
    assert node.internodeAngle == pytest.approx(0.25 * 20.0)

    # first phytomer uses firstInternodeCurvingIndex
    draws.clear()
    node.isFirstPhytomer = True
    node.calculateInternodeAngle()
    assert draws == [10.0]


def test_will_create_inflorescence_zero_inactive_meristems(gilia):
    """With no inactive apical reproductive meristems left, safedivExcept
    returns the 0 fallback (prob 0) and the method returns False â€” the
    original passes the count raw; a max(1, ...) guard made the probability
    (numExpected - numAlready) and stole extra inflorescences."""
    gilia.reset()
    for _ in range(10):
        gilia.nextDay()
    meristem = None
    for part in _walk(gilia):
        if type(part).__name__ == "PdMeristem" and part.isApical and \
                part.phytomerAttachedTo is not None:
            meristem = part
            break
    assert meristem is not None
    gilia.pGeneral.numApicalInflors = 8.0
    gilia.numApicalActiveReproductiveMeristemsOrInflorescences = 0
    gilia.numApicalInactiveReproductiveMeristems = 0
    before = gilia.randomNumberGenerator.seed
    result = meristem.willCreateInflorescence()
    assert result is False
    # exactly one draw consumed (the zeroToOne against prob 0)
    assert gilia.randomNumberGenerator.seed != before


def test_decide_if_active_female_male_override(gilia):
    """Separate sexes: a male meristem whose isApical matches the female
    inflorescence terminality flips to female only half the time, and the
    override consumes one RNG draw (umerist.py decideIfActiveFemale)."""
    gilia.reset()
    gilia.nextDay()
    meristem = None
    for part in _walk(gilia):
        if type(part).__name__ == "PdMeristem":
            meristem = part
            break
    assert meristem is not None
    female = gilia.pInflor[kGenderFemale]
    terminal = bool(female.get("isTerminal", True)) \
        if isinstance(female, dict) else True
    meristem.isApical = terminal
    meristem.gender = kGenderMale
    rng = gilia.randomNumberGenerator
    # a high draw (> 0.5) must NOT flip to female
    rng.setSeed(_seed_that_yields(rng, 0.9))
    assert meristem.decideIfActiveFemale() is False
    # a low draw (< 0.5) flips to female
    rng.setSeed(_seed_that_yields(rng, 0.1))
    assert meristem.decideIfActiveFemale() is True


def _seed_that_yields(rng, target):
    """A seed whose first zeroToOne() lands within 0.01 of target.
    zeroToOne advances the LCG once before converting, so the first draw is
    (16807*s mod M) * 4.656612875245797e-10 â€” precomputed constants:
    seed 11500 -> 0.0900, seed 113719 -> 0.8900."""
    return {0.9: 113719, 0.1: 11500}[target]


def test_gilia_growth_matches_original_counts(gilia):
    """Full saved-age growth (age 120, seed 482): part counts match the
    transpiled original exactly - the inflorescence deficit (7 vs 8) and
    flower deficit (42 vs 48) that motivated the round are gone."""
    gilia.reset()
    gilia.growTo(120)
    counts = {}
    for part in _walk(gilia):
        name = type(part).__name__
        counts[name] = counts.get(name, 0) + 1
    assert counts == {
        "PdInternode": 39, "PdLeaf": 40, "PdMeristem": 31,
        "PdInflorescence": 8, "PdFlowerFruit": 48,
    }


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


def _flowers(plant):
    return [f for f in _walk(plant)
            if type(f).__name__ == "PdFlowerFruit"]


def _species_plant(name):
    lib = SpeciesLibrary(DATA_DIR)
    tdo_lib = TdoLibrary.from_file(TDO_PATH)
    species = next(s for s in lib.categories["Garden flowers"]
                   if s.name == name)
    return create_plant(species, seed=_pla_seed("Garden flowers", name),
                        tdo_library=tdo_lib)


def test_campanula_growth_hard_stops_before_drop_window():
    """ufruit.py nextDay: an open flower whose daysOpen exceeds
    daysBeforeDrop falls off BEFORE the fruit gate can fire (elif chain).
    Campanula drops at 50 days open with the fruit gate at 100 — but the
    original never simulates past ageAtMaturity (uplant.pas setAge clamps;
    updcom.pas animateOneDay guards plant.nextDay), and campanula matures
    at 60: the 50-day drop window is unreachable, so campanula flowers
    stay open and never fruit no matter how long you grow them (the
    'generic blue fruits' bug stays fixed under the maturity hard stop)."""
    plant = _species_plant("campanula")
    for _ in range(350):
        plant.nextDay()
    assert plant.age == 60, "growth must hard-stop at ageAtMaturity"
    flowers = _flowers(plant)
    assert flowers, "campanula should grow flowers"
    assert all(not f.hasFallenOff for f in flowers)
    assert not any(f.hasSetFruit for f in flowers)


def test_fruit_gate_respects_min_days_before_setting_fruit():
    """gilia (drop 200, fruit gate 100): open flowers set fruit only after
    the flower itself is older than minDaysBeforeSettingFruit=100. Gilia
    matures at 120 and flowers at 68, so a flower's age can never exceed
    ~52 — the original (uplant.pas setAge clamps at ageAtMaturity) can
    never show gilia fruit, and neither can the port."""
    plant = _species_plant("gilia")
    for _ in range(250):
        plant.nextDay()
    assert plant.age == 120, "growth must hard-stop at ageAtMaturity"
    flowers = _flowers(plant)
    assert len(flowers) == 48
    assert all(f.stage == "open" for f in flowers)
    assert not any(f.hasSetFruit for f in flowers)


def test_campanula_flowers_never_fruit_at_saved_age():
    """At campanula's saved age 60 the flowers are open with daysOpen well
    under the 50-day drop window — the saved-age draw is all petals (this
    is what the reference OBJ at age 60 shows)."""
    plant = _species_plant("campanula")
    for _ in range(60):
        plant.nextDay()
    for f in _flowers(plant):
        assert not f.hasSetFruit
        assert not f.hasFallenOff
