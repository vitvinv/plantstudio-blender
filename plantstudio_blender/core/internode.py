"""PdInternode / PdPhytomer port — the stem segment between leaves."""

from . import math3d as umath
from .meristem import (PdPlantPart, kPartTypePhytomer, kArrangementOpposite,
                       kActivityFree, kActivityDraw, kActivityNextDay)
from .leaf import PdLeaf


class PdInternode(PdPlantPart):
    def __init__(self, plant=None):
        super().__init__(plant)
        self.isFirstPhytomer = False
        self.lengthExpansion = 1.0
        self.widthExpansion = 1.0
        self.boltingExpansion = 1.0
        self.fractionOfOptimalInitialBiomassAtCreation_frn = 1.0
        self.internodeColor = None
        # drawing state
        self.internodeAngle = 0.0
        self.distanceFromApicalMeristem_val = 0.0
        self.distanceFromFirstPhytomer_val = 0.0

    def partType(self):
        return kPartTypePhytomer

    def getName(self):
        return "internode"

    def isPhytomer(self):
        return True

    def newWithPlantFractionOfInitialOptimalSize(self, plant, aFraction):
        self.plant = plant
        self.isFirstPhytomer = False
        self.calculateInternodeAngle()
        self.lengthExpansion = 1.0
        self.widthExpansion = 1.0
        self.boltingExpansion = 1.0
        self.fractionOfOptimalInitialBiomassAtCreation_frn = aFraction
        self.liveBiomass_pctMPB = aFraction * PdInternode.optimalInitialBiomass_pctMPB(self.plant)
        self.deadBiomass_pctMPB = 0.0
        self.internodeColor = getattr(self.plant.pInternode, "faceColor", None)
        self.leftLeaf = PdLeaf().newWithPlantFractionOfOptimalSize(self.plant, aFraction)
        if self.plant.pMeristem.branchingAndLeafArrangement == kArrangementOpposite:
            self.rightLeaf = PdLeaf().newWithPlantFractionOfOptimalSize(self.plant, aFraction)
        return self

    def makeSecondSeedlingLeaf(self, aFraction):
        if self.rightLeaf is None:
            self.rightLeaf = PdLeaf().newWithPlantFractionOfOptimalSize(self.plant, aFraction)
        if self.rightLeaf is not None:
            self.rightLeaf.isSeedlingLeaf = True

    def setAsFirstPhytomer(self):
        self.isFirstPhytomer = True
        if self.leftLeaf is not None:
            self.leftLeaf.isSeedlingLeaf = True
        if self.rightLeaf is not None:
            self.rightLeaf.isSeedlingLeaf = True
        self.calculateInternodeAngle()

    @staticmethod
    def optimalInitialBiomass_pctMPB(plant):
        p = plant.pInternode
        lenMult = getattr(p, "lengthMultiplierDueToBiomassAccretion", 1.0)
        widMult = getattr(p, "widthMultiplierDueToBiomassAccretion", 1.0)
        return umath.safedivExcept(p.optimalFinalBiomass_pctMPB, lenMult * widMult, 0)

    # ── growth ──

    def nextDay(self):
        super().nextDay()
        if self.liveBiomass_pctMPB > 0:
            try:
                te = umath.max(0.0, umath.min(500.0,
                    umath.safedivExcept(self.liveBiomass_pctMPB - self.newBiomassForDay_pctMPB,
                                         self.liveBiomass_pctMPB, 0) * self.lengthExpansion
                    + umath.safedivExcept(self.newBiomassForDay_pctMPB,
                                          self.liveBiomass_pctMPB, 0) * 1.0))
                self.lengthExpansion = te
            except Exception:
                pass
            try:
                te = umath.max(0.0, umath.min(50.0,
                    umath.safedivExcept(self.liveBiomass_pctMPB - self.newBiomassForDay_pctMPB,
                                         self.liveBiomass_pctMPB, 0) * self.widthExpansion
                    + umath.safedivExcept(self.newBiomassForDay_pctMPB,
                                          self.liveBiomass_pctMPB, 0) * 1.0))
                self.widthExpansion = te
            except Exception:
                pass
            if self.plant.floweringHasStarted:
                self.boltingExpansion = umath.linearGrowthWithFactor(
                    self.boltingExpansion,
                    self.plant.pInternode.lengthMultiplierDueToBolting,
                    self.plant.pInternode.minDaysToBolt, 1.0)
        self.checkIfSeedlingLeavesHaveAbscissed()
        self.calculateDistanceFromFirstPhytomer()

    def checkIfSeedlingLeavesHaveAbscissed(self):
        # Natural PlantStudio behavior: seedling leaves fall off after
        # NodesOnStemWhenFallsOff nodes (e.g. grass seedling leaves die).
        for leaf in (self.leftLeaf, self.rightLeaf):
            if leaf is not None and leaf.isSeedlingLeaf:
                nodes = int(self.plant.pSeedlingLeaf.nodesOnStemWhenFallsOff)
                if self.plant.mainStemNodeCount() > nodes:
                    leaf.hasFallenOff = True

    # ── geometry helpers ──

    def totalBiomass_pctMPB(self):
        return self.liveBiomass_pctMPB + self.deadBiomass_pctMPB

    def propFullLength(self):
        """Fraction of full length (0..1): biomass fraction * expansions."""
        p = self.plant.pInternode
        optimal = getattr(p, "optimalFinalBiomass_pctMPB", 0.0)
        return umath.safedivExcept(self.totalBiomass_pctMPB() * self.lengthExpansion
                                   * self.boltingExpansion, optimal, 0)

    def propFullWidth(self):
        """Fraction of full width (0..1): biomass fraction * expansion."""
        p = self.plant.pInternode
        optimal = getattr(p, "optimalFinalBiomass_pctMPB", 0.0)
        return umath.safedivExcept(self.totalBiomass_pctMPB() * self.widthExpansion,
                                   optimal, 0)

    def calculateInternodeAngle(self):
        # angle from vertical based on curving index (simplified)
        p = self.plant.pInternode
        if self.isFirstPhytomer:
            ci = getattr(p, "firstInternodeCurvingIndex", 0.0)
        else:
            ci = getattr(p, "curvingIndex", 0.0)
        self.internodeAngle = (ci / 100.0) * 90.0

    def distanceFromApicalMeristem(self):
        """Count phytomers along the apex until reaching an apical meristem
        or inflorescence (port of the original on-demand computation)."""
        result = 0
        if self.nextPlantPart is not None and self.nextPlantPart.isPhytomer():
            aPhytomer = self.nextPlantPart
        else:
            aPhytomer = None
        while aPhytomer is not None:
            result += 1
            if aPhytomer.nextPlantPart is not None and aPhytomer.nextPlantPart.isPhytomer():
                aPhytomer = aPhytomer.nextPlantPart
            else:
                aPhytomer = None
        return result

    def calculateDistanceFromFirstPhytomer(self):
        if self.phytomerAttachedTo is not None:
            self.distanceFromFirstPhytomer_val = self.phytomerAttachedTo.distanceFromFirstPhytomer_val + 1
        else:
            self.distanceFromFirstPhytomer_val = 0

    def distanceFromFirstPhytomer(self):
        return self.distanceFromFirstPhytomer_val

    def firstPhytomerOnBranch(self):
        result = self
        while result is not None and result.phytomerAttachedTo is not None:
            result = result.phytomerAttachedTo
        return result

    def mainStemNodeCount(self):
        count = 0
        node = self.plant.firstPhytomer
        while node is not None:
            count += 1
            node = node.nextPlantPart
            if node is not None and node.isPhytomer():
                pass
            else:
                break
        return count

    def traverseActivity(self, mode, traverser):
        if mode == kActivityNextDay:
            self.nextDay()
        elif mode == kActivityDraw:
            self.draw()
        elif mode == kActivityFree:
            pass
        else:
            # leaves handled separately
            if self.leftLeaf is not None and not self.leftLeaf.hasFallenOff:
                self.leftLeaf.traverseActivity(mode, traverser)
            if self.rightLeaf is not None and not self.rightLeaf.hasFallenOff:
                self.rightLeaf.traverseActivity(mode, traverser)

    def draw(self):
        from .draw import draw_internode, draw_leaf
        draw_internode(self)
        if self.leftLeaf is not None and not self.leftLeaf.hasFallenOff:
            from .meristem import kDirectionLeft
            draw_leaf(self.leftLeaf, kDirectionLeft)
        if self.rightLeaf is not None and not self.rightLeaf.hasFallenOff:
            from .meristem import kDirectionRight
            draw_leaf(self.rightLeaf, kDirectionRight)
