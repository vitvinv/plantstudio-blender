"""Plant breeder checks: determinism, bounds, blend math, pick rules,
serialization round-trip (core/breeding.py — pure Python, no bpy)."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from plantstudio_blender.core import breeding
from plantstudio_blender.core.breeding import (PdBreedingStrategy, breed,
                                               get_value, params_from_dict,
                                               params_to_dict)
from plantstudio_blender.core.defaults import make_default_params
from plantstudio_blender.core.factory import create_plant
from plantstudio_blender.core.normalize import normalize_params
from plantstudio_blender.core.pla_parser import registry_by_id
from plantstudio_blender.core.rng import PdRandom

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def _species():
    from plantstudio_blender.core.plant_library import SpeciesLibrary
    return SpeciesLibrary(DATA_DIR)


def _two_species():
    """One Garden flower + one Strange breeder plant, by stable names."""
    lib = _species()
    a = lib.get("Daylily")
    b = None
    for name in lib.names():
        if "cucumber" in name.lower() or "sundew" in name.lower() \
                or "pitcher" in name.lower():
            b = lib.get(name)
            break
    if b is None:  # any Strange breeder plant fallback
        strange = lib.categories.get("Strange breeder plants") or []
        b = strange[0] if strange else lib.names()[-1] and lib.get(lib.names()[-1])
    return a, b


def _face_count(params, tdo_lib, day=60):
    from plantstudio_blender.core.mesh_buffer import MeshBuffer
    from plantstudio_blender.core.turtle import MeshTurtle
    from plantstudio_blender.core.draw import draw_plant
    plant = create_plant(params, seed=7, tdo_library=tdo_lib)
    plant.growTo(day)
    buffer = MeshBuffer()
    draw_plant(plant, MeshTurtle(buffer))
    return len(buffer.to_mesh_data()["faces"])


# ── sections json integrity ──

def test_sections_json_integrity():
    sections = breeding.load_sections()
    assert 0 < len(sections) <= 30
    reg = registry_by_id()
    for section in sections:
        assert section["name"]
        assert section["fields"], "empty section"
        for field_id in section["fields"]:
            assert field_id == "header" or field_id in reg


def test_strategy_json_round_trip():
    strategy = PdBreedingStrategy()  # medium defaults
    strategy.mutationStrengths[3] = 17
    strategy.firstPlantWeights[5] = 72
    strategy.getNonNumericalParametersFrom = 2
    strategy.mutateAndBlendColorValues = False
    clone = PdBreedingStrategy.from_dict(json.loads(json.dumps(strategy.to_dict())))
    assert clone.mutationStrengths == strategy.mutationStrengths
    assert clone.firstPlantWeights == strategy.firstPlantWeights
    assert clone.getNonNumericalParametersFrom == 2
    assert clone.mutateAndBlendColorValues is False
    # partial / empty data falls back to defaults, never crashes
    assert PdBreedingStrategy.from_dict({}).firstPlantWeights[0] == 50
    assert PdBreedingStrategy.from_dict(None).mutationStrengths[0] == 0


# ── determinism ──

def test_same_seed_same_offspring():
    a, b = _two_species()
    strategy = PdBreedingStrategy()
    dict_1 = params_to_dict(breed(a.params, b.params, strategy, _rng(280)))
    dict_2 = params_to_dict(breed(a.params, b.params, strategy, _rng(280)))
    assert dict_1 == dict_2


def test_different_seed_differs():
    a, b = _two_species()
    strategy = PdBreedingStrategy()
    dict_1 = params_to_dict(breed(a.params, b.params, strategy, _rng(280)))
    dict_2 = params_to_dict(breed(a.params, b.params, strategy, _rng(281)))
    assert dict_1 != dict_2


def test_parents_not_mutated():
    a, b = _two_species()
    before_a = params_to_dict(a.params)
    before_b = params_to_dict(b.params)
    breed(a.params, b.params, PdBreedingStrategy(), _rng(280))
    assert params_to_dict(a.params) == before_a
    assert params_to_dict(b.params) == before_b


def _rng(seed):
    rng = PdRandom()
    rng.setSeed(seed)
    return rng


# ── bounds ──

@pytest.mark.parametrize("seed", [280, 1, 9999])
def test_all_bred_values_within_bounds(seed):
    lib = _species()
    reg = registry_by_id()
    garden = lib.categories.get("Garden flowers", [])[:3]
    strange = lib.categories.get("Strange breeder plants", [])[:3]
    pairs = []
    for group in (garden, strange):
        # category lists hold PlantSpecies objects, not names
        for i, sp_a in enumerate(group):
            pairs.append((sp_a, group[(i + 1) % len(group)]))
    assert pairs
    strategy = PdBreedingStrategy()
    for sp_a, sp_b in pairs:
        child = breed(sp_a.params, sp_b.params, strategy, _rng(seed))
        for entry in reg.values():
            if not entry["access"].startswith("p"):
                continue  # plant state (age etc.) is not bred nor clamped
            if entry["type"] not in (1, 2) or entry.get("transfer") == 2:
                continue  # skip SCurves: non-numeric copies, not clamped
            value = get_value(child, entry)
            assert value is not None, entry["id"]
            assert entry["lo"] - 1e-9 <= value <= entry["hi"] + 1e-9, entry["id"]


# ── blend math (known inputs) ──

def _entry(field_id):
    return registry_by_id()[field_id]


def test_weight_one_takes_parent_a():
    a = make_default_params()
    b = make_default_params()
    a.pInternode.LengthAtOptimalFinalBiomassAndExpansion_mm = 40.0
    b.pInternode.LengthAtOptimalFinalBiomassAndExpansion_mm = 80.0
    normalize_params(a)
    normalize_params(b)
    strategy = PdBreedingStrategy()
    strategy.mutationStrengths = [0] * 30  # pure blend, no mutation noise
    strategy.firstPlantWeights = [100] * 30
    child = breed(a, b, strategy, _rng(5))
    entry = _entry("kInternodeLengthAtOptimalFinalBiomassAndExpansion_mm")
    assert get_value(child, entry) == 40.0


def test_equal_values_skip_blend_but_still_mutate():
    a = make_default_params()
    b = make_default_params()
    strategy = PdBreedingStrategy()
    strategy.mutationStrengths = [60] * 30
    # equal values: no blend, but the Gaussian mutation still applies
    # (stdDev = 0.5*value*0.6) — the child can drift from the shared value
    child = breed(a, b, strategy, _rng(280))
    entry = _entry("kGeneralLineDivisions")
    # 1..20 smallint: whatever the mutation drew, it must stay in bounds
    assert 1 <= get_value(child, entry) <= 20
    # with zero strength the value must be the untouched shared value
    strategy0 = PdBreedingStrategy()
    strategy0.mutationStrengths = [0] * 30
    child0 = breed(a, b, strategy0, _rng(280))
    assert get_value(child0, entry) == get_value(a, entry)


def test_strength_zero_pure_blend():
    a = make_default_params()
    b = make_default_params()
    a.pInternode.LengthAtOptimalFinalBiomassAndExpansion_mm = 40.0
    b.pInternode.LengthAtOptimalFinalBiomassAndExpansion_mm = 80.0
    normalize_params(a)
    normalize_params(b)
    strategy = PdBreedingStrategy()
    strategy.mutationStrengths = [0] * 30
    child = breed(a, b, strategy, _rng(5))
    entry = _entry("kInternodeLengthAtOptimalFinalBiomassAndExpansion_mm")
    assert get_value(child, entry) == 60.0  # intround(40*0.5 + 80*0.5)


def test_smallint_clamped_to_registry_bounds():
    a = make_default_params()
    b = make_default_params()
    a.pGeneral.ageAtMaturity = 500.0
    b.pGeneral.ageAtMaturity = 480.0
    normalize_params(a)
    normalize_params(b)
    strategy = PdBreedingStrategy()
    strategy.mutationStrengths = [100] * 30  # max mutation
    for seed in range(20):
        child = breed(a, b, strategy, _rng(seed))
        value = get_value(child, _entry("kGeneralAgeAtMaturity"))
        assert 10 <= value <= 500


# ── non-numeric rules ──

def test_boolean_copied_per_rule():
    a = make_default_params()
    b = make_default_params()
    a.pGeneral.MaleFlowersAreSeparate = True
    b.pGeneral.MaleFlowersAreSeparate = False
    normalize_params(a)
    normalize_params(b)
    entry = _entry("kGeneralMaleFlowersAreSeparate")

    strategy = PdBreedingStrategy()
    strategy.getNonNumericalParametersFrom = 0  # kFromFirstPlant
    assert get_value(breed(a, b, strategy, _rng(1)), entry) is True
    strategy.getNonNumericalParametersFrom = 1  # kFromSecondPlant
    assert get_value(breed(a, b, strategy, _rng(1)), entry) is False


def test_tdo_copied_from_chosen_parent_by_name():
    lib = _species()
    a = lib.get("Daylily")
    b = None
    for name in lib.names():
        other = lib.get(name)
        leaf_name = breeding._tdo_name(
            get_value(other.params, _entry("kLeafObject3D")))
        if leaf_name and leaf_name != breeding._tdo_name(
                get_value(a.params, _entry("kLeafObject3D"))):
            b = other
            break
    assert b is not None, "need two species with different leaf objects"
    entry = _entry("kLeafObject3D")
    a_name = breeding._tdo_name(get_value(a.params, entry))
    b_name = breeding._tdo_name(get_value(b.params, entry))
    assert a_name and b_name and a_name != b_name

    strategy = PdBreedingStrategy()
    strategy.getNonNumericalParametersFrom = 1  # kFromSecondPlant
    child = breed(a.params, b.params, strategy, _rng(1))
    value = get_value(child, entry)
    assert breeding._tdo_name(value) == b_name
    # TDO references are names, never deep-copied geometry instances
    assert isinstance(value, str)


def test_single_parent_mutation_changes_numerics():
    a = make_default_params()
    normalize_params(a)
    strategy = PdBreedingStrategy()  # medium mutation
    child = breed(a, None, strategy, _rng(280))
    before = params_to_dict(a)
    after = params_to_dict(child)
    assert before != after


def test_single_parent_zero_mutation_is_identity():
    a = make_default_params()
    normalize_params(a)
    strategy = PdBreedingStrategy()
    strategy.mutationStrengths = [0] * 30
    strategy.mutateAndBlendColorValues = False  # else colors still mutate
    child = breed(a, None, strategy, _rng(280))
    before = params_to_dict(a)
    after = params_to_dict(child)
    # the two registry data quirks legitimately move: the original clamps
    # to parameters.tab bounds, and their defaults sit outside them
    # (determinate hi=1.0 default=30; leaflets lo=1 default=0)
    diff = {k for k in before if before[k] != after.get(k)}
    assert diff <= {"pMeristem.DeterminateProbability",
                    "pLeaf.CompoundNumLeaflets"}, diff


def test_offspring_differs_from_both_parents():
    a, b = _two_species()
    child = breed(a.params, b.params, PdBreedingStrategy(), _rng(280))
    child_dict = params_to_dict(child)
    assert child_dict != params_to_dict(a.params)
    assert child_dict != params_to_dict(b.params)


# ── custom-params serialization round trip ──

def test_params_dict_round_trip_and_mesh_parity():
    lib = _species()
    tdo_lib = _tdo_library(lib)
    a = lib.get("Daylily")
    plain = params_to_dict(a.params)
    rebuilt = params_from_dict(plain)
    assert params_to_dict(rebuilt) == plain
    day = 60
    assert (_face_count(a.params, tdo_lib, day)
            == _face_count(rebuilt, tdo_lib, day))


def _tdo_library(lib):
    from plantstudio_blender.core.tdo_parser import TdoLibrary
    path = os.path.join(DATA_DIR, "3D object library.tdo")
    tdo_lib = TdoLibrary.from_file(path)
    tdo_lib.merge(list(lib.embedded_tdos.values()))
    return tdo_lib


def test_bred_params_serialize_and_rebuild():
    a, b = _two_species()
    tdo_lib = _tdo_library(_species())
    child = breed(a.params, b.params, PdBreedingStrategy(), _rng(280))
    plain = params_to_dict(child)
    rebuilt = params_from_dict(plain)
    assert params_to_dict(rebuilt) == plain
    # the rebuilt params grow to a plant with the same face count
    assert (_face_count(child, tdo_lib, 60)
            == _face_count(rebuilt, tdo_lib, 60))
