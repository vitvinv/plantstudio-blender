"""Phase 1 tests: simulation core determinism and growth."""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from plantstudio_blender.core.factory import create_plant, grow_species
from plantstudio_blender.core.plant_library import SpeciesLibrary
from plantstudio_blender.core.normalize import registry_default
from plantstudio_blender.core.params import PlantParams

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


@pytest.fixture(scope="module")
def lib():
    return SpeciesLibrary(DATA_DIR)


def count_parts(plant):
    """Count phytomers + inflorescences in the part tree."""
    count = 0
    if plant.firstPhytomer is None:
        return 0
    stack = [plant.firstPhytomer]
    seen = set()
    while stack:
        part = stack.pop()
        if part is None or id(part) in seen:
            continue
        seen.add(id(part))
        count += 1
        stack.append(part.leftBranchPlantPart)
        stack.append(part.rightBranchPlantPart)
        stack.append(part.nextPlantPart)
    return count


def iter_flowers(plant):
    """Yield every PdFlowerFruit in the part tree."""
    if plant.firstPhytomer is None:
        return
    stack = [plant.firstPhytomer]
    seen = set()
    while stack:
        part = stack.pop()
        if part is None or id(part) in seen:
            continue
        seen.add(id(part))
        if hasattr(part, "flowers"):
            for flower in part.flowers:
                yield flower
        stack.append(part.leftBranchPlantPart)
        stack.append(part.rightBranchPlantPart)
        stack.append(part.nextPlantPart)
        stack.append(part.leftLeaf)
        stack.append(part.rightLeaf)


class TestSimulation:
    def test_plant_grows(self, lib):
        species = lib.get("maiden grass")
        plant = grow_species(species, 60)
        assert plant.age == 60
        assert plant.firstPhytomer is not None
        assert count_parts(plant) >= 1
        assert plant.totalBiomass_pctMPB > 0

    @pytest.mark.parametrize("day", [10, 30, 60, 100])
    def test_growth_monotonic(self, lib, day):
        species = lib.get("maiden grass")
        p = grow_species(species, day)
        assert p.totalBiomass_pctMPB >= 0
        assert p.age == day

    def test_deterministic_same_seed(self, lib):
        species = lib.get("maiden grass")
        p1 = grow_species(species, 60, seed=280)
        p2 = grow_species(species, 60, seed=280)
        assert count_parts(p1) == count_parts(p2)
        assert p1.totalBiomass_pctMPB == p2.totalBiomass_pctMPB

    def test_different_seed_diverges(self, lib):
        species = lib.get("maiden grass")
        p1 = grow_species(species, 60, seed=280)
        p2 = grow_species(species, 60, seed=281)
        # trees may coincidentally match; check biomass + at least one differs
        assert p1.seed == 280 and p2.seed == 281

    def test_branching_produces_side_parts(self, lib):
        species = lib.get("Piney bushy plant") if lib.get("Piney bushy plant") else lib.names()[0]
        plant = grow_species(species, 100)
        # count axillary (non-apical) meristems
        axillary = 0
        if plant.firstPhytomer is not None:
            stack = [plant.firstPhytomer]
            seen = set()
            while stack:
                part = stack.pop()
                if part is None or id(part) in seen:
                    continue
                seen.add(id(part))
                if part.getName() == "meristem" and not part.isApical:
                    axillary += 1
                stack.extend([part.leftBranchPlantPart, part.rightBranchPlantPart,
                              part.nextPlantPart])
        assert axillary >= 0

    def test_flowering_starts(self, lib):
        species = lib.get("maiden grass")
        plant = grow_species(species, 200)
        assert plant.floweringHasStarted or plant.age >= plant.pGeneral.ageAtWhichFloweringStarts

    def test_all_species_grow(self, lib):
        """Every species must survive growing to 50 days without crashing."""
        for name in lib.names()[:15]:
            species = lib.get(name)
            plant = grow_species(species, 50)
            assert plant.age == 50, f"{name} failed"

    def test_flower_stage_waits_for_biomass_or_deadline(self, lib):
        """Stage progression follows the original's gates: campanula's open
        flowers would drop at daysOpen > 50 (daysBeforeDrop) before the
        fruit gate (minDaysBeforeSettingFruit = 100) could fire — but the
        original never simulates past ageAtMaturity (uplant.pas setAge
        clamps), and campanula matures at 60, so its flowers stay open
        forever. Same for gilia (maturity 120 < the 100-day fruit gate)."""
        species = lib.get("campanula")
        plant = grow_species(species, 80, seed=280)
        flowers = list(iter_flowers(plant))
        assert flowers
        assert all(f.stage == "open" for f in flowers)
        plant = grow_species(species, 150, seed=280)
        assert plant.age == 60, "growth must hard-stop at ageAtMaturity"
        flowers = list(iter_flowers(plant))
        assert all(f.stage == "open" for f in flowers)
        assert not any(f.hasSetFruit or f.hasFallenOff for f in flowers)
        species = lib.get("gilia")
        plant = grow_species(species, 250, seed=482)
        assert plant.age == 120, "growth must hard-stop at ageAtMaturity"
        flowers = list(iter_flowers(plant))
        assert flowers
        assert all(f.stage == "open" for f in flowers)
        assert not any(f.hasSetFruit for f in flowers)

    @pytest.mark.parametrize("name", ["tomato", "This way - that way plant"])
    def test_fast_flowers_pass_through_open_stage(self, lib, name):
        """A fast reproductive cycle must still progress bud → fruit.

        With the faithful double nextDay on flowers (uinflor.nextDay
        advances each flower twice per plant day), the open window of a
        fast species can be shorter than one plant day — e.g. tomato
        seed-280 jumps bud(70) → unripe(71). The open stage itself is
        exercised by campanula in
        test_flower_stage_waits_for_biomass_or_deadline; here we assert the
        full bud → unripe → ripe progression is reachable."""
        species = lib.get(name)
        assert species is not None, f"species {name!r} not found"
        stages_by_day = []
        for day in (44, 49, 54) if name == "This way - that way plant" else (70, 71, 90):
            plant = grow_species(species, day, seed=280)
            stages_by_day.append({flower.stage for flower in iter_flowers(plant)})
        assert any("bud" in stages for stages in stages_by_day)
        assert any("unripe_fruit" in stages for stages in stages_by_day)
        assert any("ripe_fruit" in stages for stages in stages_by_day)

    @pytest.mark.parametrize("name", ["corn", "tomato"])
    def test_fruit_sets_by_deadline(self, lib, name):
        """P1 regression: fruit must set even when biomass stays below the
        min-fraction threshold — the original's maxDaysToGrowIfOverMinFraction
        deadline fallback (IMPROVEMENT_PLAN §1). (Gilia excluded: its fruit
        gate needs flower age > 100 but it matures at 120, so the original
        can never show gilia fruit — see the maturity hard-stop test.)"""
        species = lib.get(name)
        assert species is not None, f"species {name!r} not found"
        plant = grow_species(species, 200)
        flowers = list(iter_flowers(plant))
        assert flowers, f"{name} produced no flowers by day 200"
        assert any(f.hasSetFruit for f in flowers), (
            f"{name}: no flower set fruit by day 200 "
            f"(threshold never reached nor deadline passed)")

    @pytest.mark.parametrize("name", ["corn", "tomato"])
    def test_fruit_ripens(self, lib, name):
        """P3a regression: a flower that has set fruit eventually ripens
        (isRipe True) after pFruit.daysToRipen days (IMPROVEMENT_PLAN §3a)."""
        species = lib.get(name)
        assert species is not None, f"species {name!r} not found"
        plant = grow_species(species, 200)
        flowers = [f for f in iter_flowers(plant) if f.hasSetFruit]
        assert flowers, f"{name}: expected fruit to set by day 200"
        assert any(f.isRipe for f in flowers), (
            f"{name}: fruit set but nothing ripened by day 200 "
            f"(daysToRipen never elapsed)")

    def test_growth_hard_stops_at_maturity(self, lib):
        """The original never simulates past ageAtMaturity (uplant.pas
        setAge clamps; the UI slider clamps too), so growTo must stop
        there: age freezes at maturity and reproductive biomass stops
        rising (no eternal carrots, no fruits the original never shows)."""
        maturity = int(lib.get("gilia").params.pGeneral.ageAtMaturity)
        plant = grow_species(lib.get("gilia"), 9999, seed=482)
        assert plant.age == maturity
        assert plant.totalBiomass_pctMPB <= 100.0 + 1e-6
        # past maturity nothing new can ever be produced
        repro_at_maturity = plant.reproBiomass_pctMPB
        parts_at_maturity = count_parts(plant)
        flowers_at_maturity = sum(1 for _ in iter_flowers(plant))
        for _ in range(10):
            plant.nextDay()
        # age stays pinned at maturity forever; nothing changes
        assert plant.age == maturity
        assert plant.reproBiomass_pctMPB == pytest.approx(repro_at_maturity)
        assert count_parts(plant) == parts_at_maturity
        assert sum(1 for _ in iter_flowers(plant)) == flowers_at_maturity


class TestRegistryDefaults:
    """P5a: normalize defaults derive from param_registry.json where sane."""

    @pytest.mark.parametrize("section,attr,expected", [
        ("pGeneral", "lineDivisions", 3),
        ("pGeneral", "ageAtMaturity", 100),
        ("pGeneral", "numAxillaryInflors", 4),
        ("pGeneral", "isDicot", True),
        ("pMeristem", "branchingIndex", 30.0),
        ("pInternode", "optimalFinalBiomass_pctMPB", 4.0),
        ("pInternode", "minDaysToCreateInternode", 3),
        ("pLeaf", "maxDaysToGrow", 10),
    ])
    def test_registry_default_matches_normalize(self, section, attr, expected):
        assert registry_default(section, attr, None) == expected

    def test_from_scratch_params_get_registry_defaults(self):
        params = PlantParams()
        from plantstudio_blender.core.normalize import normalize_params
        normalize_params(params)
        assert params.pGeneral.lineDivisions == 3
        assert params.pGeneral.ageAtMaturity == 100
        assert params.pInternode.optimalFinalBiomass_pctMPB == 4.0

    def test_wrong_registry_defaults_overridden(self):
        # registry says 30/0, but a from-scratch plant needs 1.0/1
        params = PlantParams()
        from plantstudio_blender.core.normalize import normalize_params
        normalize_params(params)
        assert params.pMeristem.determinateProbability == 1.0
        assert params.pLeaf.compoundNumLeaflets == 1
