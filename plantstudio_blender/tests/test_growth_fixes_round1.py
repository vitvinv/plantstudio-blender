"""Regression tests for the Round 1 (Bushes and shrubs) growth fixes.

Each test pins a port fidelity fix against the original Delphi source
behavior, so a future refactor can't silently regress it:

- biomass accretion multipliers are 2.0 (PdPlant.create hard-codes them;
  internode optimalInitialBiomass = optimalFinal / 4)
- PdInternode.firstPhytomerOnBranch stays within the branch (walks only
  while phytomerAttachedTo.nextPlantPart links back) and returns None for a
  phytomer that starts its own branch
- biomass removal (streaming) modes move live biomass to dead on internode
  and leaf, and the leaf offers its live biomass for removal
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from plantstudio_blender.core.internode import PdInternode
from plantstudio_blender.core.leaf import PdLeaf
from plantstudio_blender.core.meristem import (
    PdMeristem,
    kActivityRemoveVegetativeBiomass,
    kActivityVegetativeBiomassThatCanBeRemoved,
)
from plantstudio_blender.core.normalize import normalize_params
from plantstudio_blender.core.params import PlantParams


class _InternodeParams:
    optimalFinalBiomass_pctMPB = 1.0
    lengthMultiplierDueToBiomassAccretion = 2.0
    widthMultiplierDueToBiomassAccretion = 2.0


class _LeafParams:
    optimalBiomass_pctMPB = 1.0
    optimalFractionOfOptimalBiomassAtCreation_frn = 0.2


class _FakePlant:
    params = None
    pInternode = _InternodeParams()
    pLeaf = _LeafParams()


def test_accretion_multipliers_default_to_two():
    """uplant.pas PdPlant.create: internodes hard-coded to gain width and
    height twice (2.0 each), so optimalInitialBiomass = final / 4."""
    params = PlantParams()
    normalize_params(params)
    assert params.pInternode.lengthMultiplierDueToBiomassAccretion == pytest.approx(2.0)
    assert params.pInternode.widthMultiplierDueToBiomassAccretion == pytest.approx(2.0)
    # optimal initial for a part with optimalFinal == 1.0 must be 0.25
    assert PdInternode.optimalInitialBiomass_pctMPB(_FakePlant()) == pytest.approx(0.25)


def test_first_phytomer_on_branch_main_stem_returns_first():
    # main stem: P1 - P2 - P3
    p1 = PdInternode(None)
    p2 = PdInternode(None)
    p3 = PdInternode(None)
    p2.phytomerAttachedTo = p1
    p1.nextPlantPart = p2
    p3.phytomerAttachedTo = p2
    p2.nextPlantPart = p3
    assert p3.firstPhytomerOnBranch() is p1
    assert p2.firstPhytomerOnBranch() is p1
    # the first phytomer itself starts no branch
    assert p1.firstPhytomerOnBranch() is None


def test_first_phytomer_on_branch_branch_phytomer_is_bounded():
    """A phytomer on a branch stops the walk at its branch base, NOT at the
    plant's first phytomer — this gates secondary branching."""
    # main stem: P1 - P2 (P1 is the plant's first phytomer)
    p1 = PdInternode(None)
    p2 = PdInternode(None)
    p2.phytomerAttachedTo = p1
    p1.nextPlantPart = p2
    # branch off P2: N1, N2
    n1 = PdInternode(None)
    n1.phytomerAttachedTo = p2   # branch base attaches to the parent phytomer
    p2.leftBranchPlantPart = n1  # branch pointer, NOT nextPlantPart
    n2 = PdInternode(None)
    n2.phytomerAttachedTo = n1
    n1.nextPlantPart = n2
    # walking from N2 must stop at N1 (the branch base), not cross to P1
    assert n2.firstPhytomerOnBranch() is n1
    # the branch base itself starts the branch
    assert n1.firstPhytomerOnBranch() is None
    # a meristem sitting on N2 is therefore secondary (gate blocks);
    # one on P2 is not
    assert n2.firstPhytomerOnBranch() is not p1
    assert p2.firstPhytomerOnBranch() is p1


def test_remove_biomass_moves_live_to_dead():
    class _Traverser:
        fractionOfPotentialBiomass = 0.5

    part = PdInternode(None)
    part.liveBiomass_pctMPB = 1.0
    part.deadBiomass_pctMPB = 0.0
    part.traverseActivity(kActivityRemoveVegetativeBiomass, _Traverser())
    assert part.liveBiomass_pctMPB == pytest.approx(0.5)
    assert part.deadBiomass_pctMPB == pytest.approx(0.5)

    leaf = PdLeaf(None)
    leaf.liveBiomass_pctMPB = 1.0
    leaf.traverseActivity(kActivityRemoveVegetativeBiomass, _Traverser())
    assert leaf.liveBiomass_pctMPB == pytest.approx(0.5)
    assert leaf.deadBiomass_pctMPB == pytest.approx(0.5)


def test_leaf_offers_biomass_for_removal():
    class _Traverser:
        fractionOfPotentialBiomass = 1.0
        total = 0.0

    leaf = PdLeaf(None)
    leaf.liveBiomass_pctMPB = 0.75
    traverser = _Traverser()
    leaf.traverseActivity(kActivityVegetativeBiomassThatCanBeRemoved, traverser)
    assert traverser.total == pytest.approx(0.75)


# ── Round 1 follow-up fixes (leaf sizes / sway) ─────────────────────────────


class _Rng:
    def __init__(self):
        self.draws = 0

    def zeroToOne(self):
        self.draws += 1
        return 0.25 + 0.001 * self.draws

    def randomNormal(self, mean):
        # mirrors PdRandom.randomNormal: 12 zeroToOne draws, std = mean/2
        total = 0.0
        for _ in range(12):
            total += self.zeroToOne()
        return (total - 6.0) * (mean / 2.0) + mean

    def randomNormalPercent(self, mean):
        return max(0, min(100, int(round(self.randomNormal(mean / 100.0)
                                         * 100.0))))


class _Plant:
    def __init__(self):
        self.partsCreated = 0
        self.randomNumberGenerator = _Rng()
        self.floweringHasStarted = False
        self.pMeristem = type("M", (), {
            "determinateProbability": 1.0,
            "branchingAndLeafArrangement": 0,
        })()
        from plantstudio_blender.core.params import PlantParams
        from plantstudio_blender.core.normalize import normalize_params
        self.params = PlantParams()
        normalize_params(self.params)
        self.pLeaf = self.params.pLeaf
        self.pInternode = self.params.pInternode
        self.pGeneral = type("G", (), {"randomSway": 0.0})()
        self.needToRecalculateColors = False


def test_part_creation_consumes_one_rng_draw_per_part():
    """upart.pas PdPlantPart.initialize: partsCreated += 1, partID assigned,
    and ONE zeroToOne() draw stored as randomSwayIndex — per part created.
    Round 4: phytomer creation ALSO consumes one randomNormalPercent (12
    zeroToOne draws) for the curving angle (uintern.py:293) — default
    curvingIndex 30 is nonzero, so meristem 1 + internode 1 + angle 12 +
    leaf 1 = 15 draws for 3 parts."""
    from plantstudio_blender.core.internode import PdInternode
    from plantstudio_blender.core.meristem import PdMeristem

    plant = _Plant()
    assert plant.partsCreated == 0
    meristem = PdMeristem(plant)
    meristem.initializeWithPlant()
    assert plant.partsCreated == 1
    assert meristem.partID == 1
    assert 0.0 <= meristem.randomSwayIndex < 1.0
    assert plant.randomNumberGenerator.draws == 1
    phytomer = PdInternode().newWithPlantFractionOfInitialOptimalSize(plant, 1.0)
    # the phytomer AND its leaf are parts: 2 initialize draws + 12 angle
    # draws from the nonzero default curvingIndex
    assert plant.partsCreated == 3
    assert phytomer.partID == 2
    assert phytomer.leftLeaf.partID == 3
    assert plant.randomNumberGenerator.draws == 15
    assert 0.0 <= phytomer.leftLeaf.randomSwayIndex < 1.0


def test_leaf_creation_prop_full_size_uncapped():
    """uleaf.initializeFractionOfOptimalSize: creation propFullSize is
    safedivExcept WITHOUT min(1, ...) — over-accumulated fractions give
    propFullSize > 1 until the first growth day re-caps it."""
    plant = _Plant()
    leaf = PdLeaf().newWithPlantFractionOfOptimalSize(plant, 4.0)
    # live = 4.0 * 0.2 = 0.8 optimalInitial; optimal = 5.0 → 0.16
    assert leaf.propFullSize == pytest.approx(
        leaf.liveBiomass_pctMPB / plant.pLeaf.optimalBiomass_pctMPB)
    # a leaf created above optimal biomass keeps propFullSize > 1
    big = PdLeaf().newWithPlantFractionOfOptimalSize(plant, 20.0)
    assert big.liveBiomass_pctMPB > plant.pLeaf.optimalBiomass_pctMPB
    assert big.propFullSize > 1.0


def test_compound_leaf_sway_indexes_drawn_at_creation():
    """uleaf.initializeFractionOfOptimalSize draws 50 zeroToOne values
    (kNumCompoundLeafRandomSwayIndexes = 49) when the leaf is compound."""
    plant = _Plant()
    plant.pLeaf.compoundNumLeaflets = 6
    leaf = PdLeaf().newWithPlantFractionOfOptimalSize(plant, 1.0)
    assert len(leaf.compoundLeafRandomSwayIndexes) == 50
    # 1 initialize draw + 50 compound sway draws = 51
    assert plant.randomNumberGenerator.draws == 51


def test_simple_leaf_draws_no_compound_sway_indexes():
    plant = _Plant()
    plant.pLeaf.compoundNumLeaflets = 1
    leaf = PdLeaf().newWithPlantFractionOfOptimalSize(plant, 1.0)
    assert leaf.compoundLeafRandomSwayIndexes == []
    assert plant.randomNumberGenerator.draws == 1  # only the initialize draw


def test_draw_uses_stored_prop_full_size():
    """draw._prop_full_size must return the stored field (set at creation,
    re-capped during grow), NOT liveBiomass — post-flowering streaming moves
    live biomass to dead without changing the drawn size."""
    from plantstudio_blender.core.draw import _prop_full_size

    leaf = PdLeaf(None)
    leaf.propFullSize = 0.9   # frozen at the last growth day
    leaf.liveBiomass_pctMPB = 0.3   # after streaming removed biomass
    assert _prop_full_size(leaf) == pytest.approx(0.9)


