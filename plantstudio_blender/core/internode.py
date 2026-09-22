"""PdInternode / PdPhytomer port — the stem segment between leaves."""

from . import math3d as umath
from .meristem import (PdPlantPart, kPartTypePhytomer, kArrangementOpposite,
                       kActivityFree, kActivityDraw, kActivityNextDay,
                       kActivityDemandVegetative, kActivityDemandReproductive,
                       kActivityGrowVegetative, kActivityGrowReproductive,
                       kActivityStartReproduction,
                       kActivityVegetativeBiomassThatCanBeRemoved,
                       kActivityRemoveVegetativeBiomass,
                       kActivityReproductiveBiomassThatCanBeRemoved,
                       kActivityRemoveReproductiveBiomass)
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
        self.initialize(plant)
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
        # PdPlant.create hard-codes these to 2.0 (uplant.pas: internodes
        # gain width and height twice), so optimal initial = final / 4
        lenMult = getattr(p, "lengthMultiplierDueToBiomassAccretion", 2.0)
        widMult = getattr(p, "widthMultiplierDueToBiomassAccretion", 2.0)
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
        """Port of PdInternode.checkIfSeedlingLeavesHaveAbscissed
        (uintern.pas): seedling leaves on the first phytomer fall off once
        the stem has grown nodesOnStemWhenFallsOff nodes past them, but not
        before the plant is a quarter of the way to maturity."""
        if not self.isFirstPhytomer:
            return
        if self.plant.pMeristem.branchingIsSympodial:
            if self.age < 10:
                return
        else:
            if self.distanceFromApicalMeristem() <= \
                    int(self.plant.pSeedlingLeaf.nodesOnStemWhenFallsOff):
                return
        if umath.safedivExcept(self.plant.age,
                               self.plant.pGeneral.ageAtMaturity, 0) < 0.25:
            return
        for leaf in (self.leftLeaf, self.rightLeaf):
            if leaf is not None:
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
        """Port of PdInternode.calculateInternodeAngle (uintern.py:293):
        angle = 64/100 * randomNormalPercent(curvingIndex) in 256-degree
        turtle units, then sway is baked in (angleWithSway). Consumes RNG
        whenever the curving index is nonzero."""
        p = self.plant.pInternode
        if self.isFirstPhytomer:
            ci = getattr(p, "firstInternodeCurvingIndex", 0.0)
        else:
            ci = getattr(p, "curvingIndex", 0.0)
        if ci == 0:
            self.internodeAngle = 0
        else:
            self.internodeAngle = 64.0 / 100.0 * \
                self.plant.randomNumberGenerator.randomNormalPercent(ci)
        sway = getattr(self.plant.pGeneral, "randomSway", 0.0)
        if sway != 0:
            self.internodeAngle = self.internodeAngle + \
                ((self.randomSwayIndex - 0.5) * sway)

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
        """Port of PdInternode.firstPhytomerOnBranch (uintern.pas): walk down
        only while the phytomer below links back via nextPlantPart (same
        branch); returns None when this phytomer starts its own branch."""
        result = self
        while result is not None:
            attached = result.phytomerAttachedTo
            if attached is not None and attached.nextPlantPart is result:
                result = attached
            else:
                break
        if result is self:
            return None
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
        """Port of PdInternode.traverseActivity (uintern.pas).

        The internode is a first-class biomass participant: it demands
        vegetative biomass over its first maxDaysToAccumulateBiomass days
        (with stunting recovery), grows into it, and offers/removes biomass
        for streaming. Leaves are recursed into for every non-draw mode.
        """
        if mode != kActivityDraw:
            if self.leftLeaf is not None:
                self.leftLeaf.traverseActivity(mode, traverser)
            if self.rightLeaf is not None:
                self.rightLeaf.traverseActivity(mode, traverser)
        if self.hasFallenOff and mode != kActivityFree:
            return
        if mode == kActivityNextDay:
            self.nextDay()
            if self.age < traverser.ageOfYoungestPhytomer:
                traverser.ageOfYoungestPhytomer = self.age
        elif mode == kActivityDemandVegetative:
            p = self.plant.pInternode
            if self.age > p.maxDaysToAccumulateBiomass:
                self.biomassDemand_pctMPB = 0.0
                return
            if getattr(p, "canRecoverFromStuntingDuringCreation", True):
                targetBiomass = p.optimalFinalBiomass_pctMPB
            else:
                targetBiomass = p.optimalFinalBiomass_pctMPB * \
                    self.fractionOfOptimalInitialBiomassAtCreation_frn
            self.biomassDemand_pctMPB = umath.linearGrowthResult(
                self.liveBiomass_pctMPB, targetBiomass,
                p.minDaysToAccumulateBiomass)
            traverser.total += self.biomassDemand_pctMPB
        elif mode == kActivityDemandReproductive:
            pass
        elif mode == kActivityGrowVegetative:
            p = self.plant.pInternode
            if self.age > p.maxDaysToAccumulateBiomass:
                return
            self.newBiomassForDay_pctMPB = max(
                0.0, self.biomassDemand_pctMPB *
                traverser.fractionOfPotentialBiomass)
            self.liveBiomass_pctMPB += self.newBiomassForDay_pctMPB
        elif mode == kActivityGrowReproductive:
            pass
        elif mode == kActivityStartReproduction:
            pass
        elif mode == kActivityDraw:
            self.draw()
        elif mode == kActivityFree:
            pass
        elif mode == kActivityVegetativeBiomassThatCanBeRemoved:
            traverser.total += self.liveBiomass_pctMPB
        elif mode == kActivityRemoveVegetativeBiomass:
            biomassToRemove = self.liveBiomass_pctMPB * \
                traverser.fractionOfPotentialBiomass
            self.liveBiomass_pctMPB -= biomassToRemove
            self.deadBiomass_pctMPB += biomassToRemove
        elif mode in (kActivityReproductiveBiomassThatCanBeRemoved,
                      kActivityRemoveReproductiveBiomass):
            pass
        # other modes (statistics, picking, export counting) are not used
        # by the headless census and are ignored

    def draw(self):
        from .draw import draw_internode, draw_leaf
        draw_internode(self)
        if self.leftLeaf is not None and not self.leftLeaf.hasFallenOff:
            from .meristem import kDirectionLeft
            draw_leaf(self.leftLeaf, kDirectionLeft)
        if self.rightLeaf is not None and not self.rightLeaf.hasFallenOff:
            from .meristem import kDirectionRight
            draw_leaf(self.rightLeaf, kDirectionRight)
