"""PdLeaf port — leaf attached to an internode.

Faithful port of leaf growth: leaves demand biomass based on an age-based
S-curve toward optimalBiomass, then grow via kActivityGrowVegetative.
"""

from . import math3d as umath
from .meristem import (PdPlantPart, kPartTypeLeaf, kActivityFree, kActivityNextDay,
                       kActivityDemandVegetative, kActivityGrowVegetative)


class PdLeaf(PdPlantPart):
    def __init__(self, plant=None):
        super().__init__(plant)
        self.isSeedlingLeaf = False
        self.leafColor = None
        self.petioleColor = None
        self.propFullSize = 0.0

    def partType(self):
        return kPartTypeLeaf

    def getName(self):
        return "leaf"

    def newWithPlantFractionOfOptimalSize(self, plant, aFraction):
        self.plant = plant
        self.liveBiomass_pctMPB = aFraction * PdLeaf.optimalInitialBiomass_pctMPB(plant)
        self.deadBiomass_pctMPB = 0.0
        self.propFullSize = umath.min(1.0, umath.safedivExcept(
            self.liveBiomass_pctMPB, plant.pLeaf.optimalBiomass_pctMPB, 0))
        self.leafColor = getattr(plant.pLeaf, "faceColor", None)
        self.petioleColor = getattr(plant.pLeaf, "petioleColor", None)
        return self

    @staticmethod
    def optimalInitialBiomass_pctMPB(plant):
        return plant.pLeaf.optimalBiomass_pctMPB * \
            getattr(plant.pLeaf, "optimalFractionOfOptimalBiomassAtCreation_frn", 0.2)

    def nextDay(self):
        super().nextDay()

    def demandVegetative(self, traverser):
        pLeaf = self.plant.pLeaf
        maxDays = getattr(pLeaf, "maxDaysToGrow", 10)
        if self.age > maxDays:
            self.biomassDemand_pctMPB = 0.0
            return
        fractionOfMaxAge = umath.safedivExcept(self.age + 1, maxDays, 0.0)
        s = getattr(pLeaf, "sCurveParams", None)
        if s is None:
            propFullSizeWanted = umath.min(1.0, fractionOfMaxAge)
        else:
            propFullSizeWanted = umath.max(0.0, umath.min(
                1.0, umath.scurve(fractionOfMaxAge, s.c1, s.c2)))
        target = propFullSizeWanted * pLeaf.optimalBiomass_pctMPB
        minDays = getattr(pLeaf, "minDaysToGrow", 3)
        self.biomassDemand_pctMPB = umath.linearGrowthResult(
            self.liveBiomass_pctMPB, target, minDays)
        traverser.total += self.biomassDemand_pctMPB

    def growVegetative(self, traverser):
        pLeaf = self.plant.pLeaf
        if self.age > getattr(pLeaf, "maxDaysToGrow", 10):
            return
        newBiomass = self.biomassDemand_pctMPB * traverser.fractionOfPotentialBiomass
        self.liveBiomass_pctMPB += newBiomass
        self.propFullSize = umath.min(1.0, umath.safedivExcept(
            self.liveBiomass_pctMPB, pLeaf.optimalBiomass_pctMPB, 0))

    def traverseActivity(self, mode, traverser):
        if self.hasFallenOff and mode != kActivityFree:
            return
        if mode == kActivityNextDay:
            self.nextDay()
        elif mode == kActivityDemandVegetative:
            self.demandVegetative(traverser)
        elif mode == kActivityGrowVegetative:
            self.growVegetative(traverser)
        elif mode == kActivityFree:
            pass

    def draw(self):
        pass
