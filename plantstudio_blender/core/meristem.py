"""PlantStudio growth simulation core.

Faithful Python 3 port of the meristem-based plant model:
meristems accumulate photosynthate biomass; when thresholds are met
they create phytomers (internode + leaf + buds); axillary buds branch
probabilistically; flowering converts meristems to inflorescences.

Determinism: every random draw goes through a single PdRandom instance
seeded from the species' kGeneralStartingSeedForRandomNumberGenerator.
The order of random calls mirrors the original source.
"""

from .rng import PdRandom
from . import math3d as umath
from .math3d import SCurve  # noqa: F401 (re-exported for compatibility)

# arrangement constants (from uplant.py)
kArrangementAlternate = 0
kArrangementOpposite = 1
kDirectionLeft = 0
kDirectionRight = 1
kGenderFemale = 0
kGenderMale = 1

# part types
kPartTypePhytomer = 1
kPartTypeMeristem = 2
kPartTypeLeaf = 3
kPartTypeInflorescence = 4
kPartTypeFlowerFruit = 5

# traversal modes
kActivityNone = 0
kActivityNextDay = 1
kActivityDemandVegetative = 2
kActivityDemandReproductive = 3
kActivityGrowVegetative = 4
kActivityGrowReproductive = 5
kActivityStartReproduction = 6
kActivityDraw = 7
kActivityFree = 8
kActivityVegetativeBiomassThatCanBeRemoved = 9
kActivityRemoveVegetativeBiomass = 10
kActivityReproductiveBiomassThatCanBeRemoved = 11
kActivityRemoveReproductiveBiomass = 12

# traversal directions
kTraverseLeft = 0
kTraverseRight = 1
kTraverseNext = 2
kTraverseDone = 3
kTraverseNone = 4


class PdPlantPart:
    def __init__(self, plant):
        self.plant = plant
        self.partID = 0
        self.phytomerAttachedTo = None
        self.nextPlantPart = None
        self.leftBranchPlantPart = None
        self.rightBranchPlantPart = None
        self.leftLeaf = None
        self.rightLeaf = None
        self.liveBiomass_pctMPB = 0.0
        self.deadBiomass_pctMPB = 0.0
        self.biomassDemand_pctMPB = 0.0
        self.newBiomassForDay_pctMPB = 0.0
        self.isActive = False
        self.isApical = False
        self.isReproductive = False
        self.isFirstPhytomer = False
        self.hasFallenOff = False
        self.age = 0
        self.gender = kGenderFemale
        self.traversingDirection = kTraverseNone

    def partType(self):
        raise NotImplementedError

    def getName(self):
        return "part"

    def isPhytomer(self):
        return False

    def nextDay(self):
        self.age += 1
        if self.plant.needToRecalculateColors:
            pass

    # ── biomass helpers ──

    def traverseActivity(self, mode, traverser):
        if mode == kActivityNextDay:
            self.nextDay()
        elif mode == kActivityDemandVegetative:
            pass
        elif mode == kActivityDemandReproductive:
            pass
        elif mode == kActivityGrowVegetative:
            pass
        elif mode == kActivityGrowReproductive:
            pass
        elif mode == kActivityStartReproduction:
            self.startReproduction()
        elif mode == kActivityVegetativeBiomassThatCanBeRemoved:
            pass
        elif mode == kActivityRemoveVegetativeBiomass:
            pass
        elif mode == kActivityReproductiveBiomassThatCanBeRemoved:
            pass
        elif mode == kActivityRemoveReproductiveBiomass:
            pass
        elif mode == kActivityDraw:
            self.draw()

    def startReproduction(self):
        pass


class PdMeristem(PdPlantPart):
    def __init__(self, plant):
        super().__init__(plant)
        self.isApical = True
        self.daysCreatingThisPlantPart = 0

    def partType(self):
        return kPartTypeMeristem

    def getName(self):
        return "meristem"

    def initializeWithPlant(self):
        self.isApical = True
        self.liveBiomass_pctMPB = 0.0
        self.deadBiomass_pctMPB = 0.0
        self.biomassDemand_pctMPB = 0.0
        self.daysCreatingThisPlantPart = 0
        self.isActive = False
        self.isReproductive = False
        self.gender = kGenderFemale
        if self.plant.floweringHasStarted and \
                (self.plant.randomNumberGenerator.zeroToOne() <= self.plant.pMeristem.determinateProbability):
            self.setIfReproductive(True)

    def nextDay(self):
        super().nextDay()
        if self.isActive:
            self.daysCreatingThisPlantPart += 1
            if not self.isReproductive:
                self.accumulateOrCreatePhytomer()
            else:
                self.accumulateOrCreateInflorescence()
        else:
            if not self.isApical and not self.isReproductive and self.contemplateBranching():
                self.setIfActive(True)

    # ── branching ──

    def contemplateBranching(self):
        pMeristem = self.plant.pMeristem
        if pMeristem.branchingIndex == 0:
            return False
        if not pMeristem.secondaryBranchingIsAllowed:
            firstOnBranch = self.phytomerAttachedTo.firstPhytomerOnBranch()
            if firstOnBranch is not self.plant.firstPhytomer:
                return False
        if pMeristem.branchingIndex == 100:
            return True
        if self.phytomerAttachedTo.distanceFromApicalMeristem() < pMeristem.branchingDistance:
            if pMeristem.branchingDistance == 0:
                decisionPercent = pMeristem.branchingIndex
            else:
                decisionPercent = pMeristem.branchingIndex * umath.min(1.0, umath.max(0.0,
                    umath.safedivExcept(self.phytomerAttachedTo.distanceFromApicalMeristem(),
                                        pMeristem.branchingDistance, 0)))
        else:
            decisionPercent = pMeristem.branchingIndex
        return self.plant.randomNumberGenerator.randomPercent() < decisionPercent

    # ── phytomer creation ──

    def optimalInitialPhytomerBiomass_pctMPB(self):
        from .internode import PdInternode
        from .leaf import PdLeaf
        result = PdInternode.optimalInitialBiomass_pctMPB(self.plant) + \
            PdLeaf.optimalInitialBiomass_pctMPB(self.plant)
        if self.plant.pMeristem.branchingAndLeafArrangement == kArrangementOpposite:
            result += PdLeaf.optimalInitialBiomass_pctMPB(self.plant)
        return result

    def accumulateOrCreatePhytomer(self):
        optimal = self.optimalInitialPhytomerBiomass_pctMPB()
        shouldCreate = False
        if self.liveBiomass_pctMPB >= optimal:
            shouldCreate = True
        else:
            minNeeded = optimal * self.plant.pInternode.minFractionOfOptimalInitialBiomassToCreateInternode_frn
            if self.liveBiomass_pctMPB >= minNeeded and \
                    self.daysCreatingThisPlantPart >= self.plant.pInternode.maxDaysToCreateInternodeIfOverMinFraction:
                shouldCreate = True
        if shouldCreate:
            fraction = umath.safedivExcept(self.liveBiomass_pctMPB, optimal, 0)
            self.createPhytomer(fraction)
            self.liveBiomass_pctMPB = 0.0
            self.daysCreatingThisPlantPart = 0

    def accumulateOrCreateInflorescence(self):
        from .inflorescence import PdInflorescence
        if self.phytomerAttachedTo is None or self.phytomerAttachedTo.isFirstPhytomer or \
                not self.isReproductive or not self.isActive:
            return
        optimal = PdInflorescence.optimalInitialBiomass_pctMPB(self.plant, self.gender)
        shouldCreate = False
        if self.liveBiomass_pctMPB >= optimal:
            shouldCreate = True
        else:
            minNeeded = optimal * self.plant.pInternode.minFractionOfOptimalInitialBiomassToCreateInternode_frn
            p = self.plant.pInflor[self.gender]
            maxDays = p.get("maxDaysToCreateInflorescenceIfOverMinFraction", 10) \
                if isinstance(p, dict) else getattr(p, "maxDaysToCreateInflorescenceIfOverMinFraction", 10)
            if self.liveBiomass_pctMPB >= minNeeded and self.daysCreatingThisPlantPart >= maxDays:
                shouldCreate = True
        if shouldCreate:
            fraction = umath.safedivExcept(self.liveBiomass_pctMPB, optimal, 0)
            self.createInflorescence(fraction)
            self.liveBiomass_pctMPB = 0.0
            self.daysCreatingThisPlantPart = 0

    def createFirstPhytomer(self):
        self.createPhytomer(1.0)
        result = self.phytomerAttachedTo
        if self.plant.pGeneral.isDicot:
            result.makeSecondSeedlingLeaf(self.optimalInitialPhytomerBiomass_pctMPB())
        return result

    def createPhytomer(self, fractionOfFullSize):
        from .internode import PdInternode
        max_parts = self.plant.maxPartsPerPlant
        if self.plant.partsCreated > max_parts:
            return
        newPhytomer = PdInternode().newWithPlantFractionOfInitialOptimalSize(self.plant, fractionOfFullSize)
        newPhytomer.phytomerAttachedTo = self.phytomerAttachedTo
        if self.phytomerAttachedTo is not None:
            if self.isApical:
                self.phytomerAttachedTo.nextPlantPart = newPhytomer
                if self.plant.pMeristem.branchingIsSympodial:
                    self.setIfActive(False)
            else:
                if self.phytomerAttachedTo.leftBranchPlantPart is self:
                    self.phytomerAttachedTo.leftBranchPlantPart = newPhytomer
                elif self.phytomerAttachedTo.rightBranchPlantPart is self:
                    self.phytomerAttachedTo.rightBranchPlantPart = newPhytomer
                self.setIfApical(True)
            self.phytomerAttachedTo = newPhytomer
            self.phytomerAttachedTo.nextPlantPart = self
            self._createAxillaryMeristems()
        else:
            self.setIfApical(True)
            self.setIfActive(not self.plant.pMeristem.branchingIsSympodial)
            self.phytomerAttachedTo = newPhytomer
            self.phytomerAttachedTo.nextPlantPart = self
            if self.plant.pMeristem.branchingIsSympodial:
                self._createAxillaryMeristems(activateOne=True)

    def _createAxillaryMeristems(self, activateOne=False):
        if self.plant.pMeristem.branchingAndLeafArrangement == kArrangementAlternate:
            left = self.createAxillaryMeristem(kDirectionLeft)
            if self.plant.pMeristem.branchingIsSympodial or activateOne:
                left.setIfActive(True)
        else:
            left = self.createAxillaryMeristem(kDirectionLeft)
            right = self.createAxillaryMeristem(kDirectionRight)
            if self.plant.pMeristem.branchingIsSympodial or activateOne:
                if self.plant.randomNumberGenerator.zeroToOne() < 0.5:
                    left.setIfActive(True)
                else:
                    right.setIfActive(True)

    def createAxillaryMeristem(self, direction):
        newMeristem = PdMeristem(self.plant)
        newMeristem.initializeWithPlant()
        newMeristem.setIfApical(False)
        newMeristem.phytomerAttachedTo = self.phytomerAttachedTo
        if direction == kDirectionLeft:
            self.phytomerAttachedTo.leftBranchPlantPart = newMeristem
        else:
            self.phytomerAttachedTo.rightBranchPlantPart = newMeristem
        return newMeristem

    def createInflorescence(self, fractionOfOptimalSize):
        from .inflorescence import PdInflorescence
        max_parts = self.plant.maxPartsPerPlant
        if self.plant.partsCreated > max_parts:
            return
        newInflorescence = PdInflorescence()
        newInflorescence.initializeGenderApicalOrAxillary(self.plant, self.gender,
                                                          self.isApical, fractionOfOptimalSize)
        newInflorescence.meristemThatCreatedMe = self
        newInflorescence.phytomerAttachedTo = self.phytomerAttachedTo
        if self.isApical:
            self.phytomerAttachedTo.nextPlantPart = newInflorescence
        elif self.phytomerAttachedTo.leftBranchPlantPart is self:
            self.phytomerAttachedTo.leftBranchPlantPart = newInflorescence
        elif self.phytomerAttachedTo.rightBranchPlantPart is self:
            self.phytomerAttachedTo.rightBranchPlantPart = newInflorescence
        self.phytomerAttachedTo = None

    # ── traversal activities ──

    def traverseActivity(self, mode, traverser):
        if self.hasFallenOff and mode not in (kActivityFree,):
            return
        if mode == kActivityNextDay:
            self.nextDay()
        elif mode == kActivityDemandVegetative:
            if (not self.isActive) or (self.isReproductive):
                return
            if (not self.isApical) and self.phytomerAttachedTo is not None \
                    and self.phytomerAttachedTo.isFirstPhytomer \
                    and not self.plant.pMeristem.branchingIsSympodial:
                return
            from .internode import PdInternode
            from .leaf import PdLeaf
            optimal = PdInternode.optimalInitialBiomass_pctMPB(self.plant) + \
                PdLeaf.optimalInitialBiomass_pctMPB(self.plant)
            if self.plant.pMeristem.branchingAndLeafArrangement == kArrangementOpposite:
                optimal += PdLeaf.optimalInitialBiomass_pctMPB(self.plant)
            self.biomassDemand_pctMPB = umath.linearGrowthResult(
                self.liveBiomass_pctMPB, optimal,
                self.plant.pInternode.minDaysToCreateInternode)
            traverser.total += self.biomassDemand_pctMPB
        elif mode == kActivityDemandReproductive:
            from .inflorescence import PdInflorescence
            if (not self.isActive) or (not self.isReproductive):
                return
            if self.phytomerAttachedTo is not None and self.phytomerAttachedTo.isFirstPhytomer \
                    and not self.isApical:
                return
            p = self.plant.pInflor[self.gender]
            optimal = p.get("optimalBiomass_pctMPB", 1.0) if isinstance(p, dict) else \
                getattr(p, "optimalBiomass_pctMPB", 1.0)
            minDays = p.get("minDaysToCreateInflorescence", 3) if isinstance(p, dict) else \
                getattr(p, "minDaysToCreateInflorescence", 3)
            self.biomassDemand_pctMPB = umath.linearGrowthResult(
                self.liveBiomass_pctMPB, optimal, minDays)
            traverser.total += self.biomassDemand_pctMPB
        elif mode == kActivityGrowVegetative:
            if not self.isActive or self.isReproductive:
                return
            self.liveBiomass_pctMPB += self.biomassDemand_pctMPB * traverser.fractionOfPotentialBiomass
        elif mode == kActivityGrowReproductive:
            if not self.isActive or not self.isReproductive:
                return
            self.liveBiomass_pctMPB += self.biomassDemand_pctMPB * traverser.fractionOfPotentialBiomass
        elif mode == kActivityStartReproduction:
            self.startReproduction()
        elif mode == kActivityDraw:
            self.draw()
        elif mode == kActivityVegetativeBiomassThatCanBeRemoved:
            if not self.isActive or self.isReproductive:
                return
            traverser.total += self.liveBiomass_pctMPB
        elif mode == kActivityReproductiveBiomassThatCanBeRemoved:
            if not self.isActive or not self.isReproductive:
                return
            traverser.total += self.liveBiomass_pctMPB
        elif mode == kActivityRemoveVegetativeBiomass:
            if not self.isActive or self.isReproductive:
                return
            removed = self.liveBiomass_pctMPB * traverser.fractionOfPotentialBiomass
            self.liveBiomass_pctMPB -= removed
            self.deadBiomass_pctMPB += removed
        elif mode == kActivityRemoveReproductiveBiomass:
            if not self.isActive or not self.isReproductive:
                return
            removed = self.liveBiomass_pctMPB * traverser.fractionOfPotentialBiomass
            self.liveBiomass_pctMPB -= removed
            self.deadBiomass_pctMPB += removed

    def draw(self):
        from .draw import draw_meristem
        draw_meristem(self)

    # ── state setters (keep plant counters consistent) ──

    def setIfActive(self, active):
        if self.isActive == active:
            return
        self.isActive = active
        if self.isReproductive:
            if self.isApical:
                if self.isActive:
                    self.plant.numApicalActiveReproductiveMeristemsOrInflorescences += 1
                    self.plant.numApicalInactiveReproductiveMeristems -= 1
                else:
                    self.plant.numApicalInactiveReproductiveMeristems += 1
                    self.plant.numApicalActiveReproductiveMeristemsOrInflorescences -= 1
            else:
                if self.isActive:
                    self.plant.numAxillaryActiveReproductiveMeristemsOrInflorescences += 1
                    self.plant.numAxillaryInactiveReproductiveMeristems -= 1
                else:
                    self.plant.numAxillaryInactiveReproductiveMeristems += 1
                    self.plant.numAxillaryActiveReproductiveMeristemsOrInflorescences -= 1

    def setIfApical(self, apical):
        if self.isApical == apical:
            return
        self.isApical = apical
        if self.isReproductive:
            if self.isActive:
                if self.isApical:
                    self.plant.numApicalActiveReproductiveMeristemsOrInflorescences += 1
                    self.plant.numAxillaryActiveReproductiveMeristemsOrInflorescences -= 1
                else:
                    self.plant.numAxillaryActiveReproductiveMeristemsOrInflorescences += 1
                    self.plant.numApicalActiveReproductiveMeristemsOrInflorescences -= 1
            else:
                if self.isApical:
                    self.plant.numApicalInactiveReproductiveMeristems += 1
                    self.plant.numAxillaryInactiveReproductiveMeristems -= 1
                else:
                    self.plant.numAxillaryInactiveReproductiveMeristems += 1
                    self.plant.numApicalInactiveReproductiveMeristems -= 1

    def setIfReproductive(self, reproductive):
        if self.isReproductive == reproductive:
            return
        self.isReproductive = reproductive
        if self.isApical:
            if self.isActive:
                if self.isReproductive:
                    self.plant.numApicalActiveReproductiveMeristemsOrInflorescences += 1
                else:
                    self.plant.numApicalActiveReproductiveMeristemsOrInflorescences -= 1
            else:
                if self.isReproductive:
                    self.plant.numApicalInactiveReproductiveMeristems += 1
                else:
                    self.plant.numApicalInactiveReproductiveMeristems -= 1
        else:
            if self.isActive:
                if self.isReproductive:
                    self.plant.numAxillaryActiveReproductiveMeristemsOrInflorescences += 1
                else:
                    self.plant.numAxillaryActiveReproductiveMeristemsOrInflorescences -= 1
            else:
                if self.isReproductive:
                    self.plant.numAxillaryInactiveReproductiveMeristems += 1
                else:
                    self.plant.numAxillaryInactiveReproductiveMeristems -= 1

    def startReproduction(self):
        rng = self.plant.randomNumberGenerator
        if rng.zeroToOne() <= self.plant.pMeristem.determinateProbability:
            self.setIfReproductive(True)
        if not self.isReproductive:
            return
        self.setIfActive(False)
        self.gender = kGenderFemale
        if not self.plant.pGeneral.maleFlowersAreSeparate:
            if self.decideIfActiveHermaphroditic():
                self.gender = kGenderFemale
        else:
            if self.decideIfActiveMale():
                self.gender = kGenderMale
            if self.decideIfActiveFemale():
                self.gender = kGenderFemale
        if self.willCreateInflorescence():
            self.setIfActive(True)

    def decideIfActiveHermaphroditic(self):
        """Hermaphroditic flowers: female params; active if apical matches
        the female inflorescence's terminal setting."""
        return self.isApical == bool(
            self.plant.pInflor[kGenderFemale].get("isTerminal", True))

    def decideIfActiveMale(self):
        return self.isApical == bool(
            self.plant.pInflor[kGenderMale].get("isTerminal", False))

    def decideIfActiveFemale(self):
        return self.isApical == bool(
            self.plant.pInflor[kGenderFemale].get("isTerminal", True))

    def willCreateInflorescence(self):
        """Port of the original: probability based on inflorescences still
        needed vs meristems still available."""
        result = False
        if self.phytomerAttachedTo is not None and \
                self.phytomerAttachedTo.isFirstPhytomer and not self.isApical:
            return False
        if self.isApical:
            numExpected = int(self.plant.pGeneral.numApicalInflors)
            numAlready = self.plant.numApicalActiveReproductiveMeristemsOrInflorescences
            numInactive = max(1, self.plant.numApicalInactiveReproductiveMeristems)
            inflorProb = umath.safedivExcept(numExpected - numAlready, numInactive, 0)
        else:
            numExpected = int(self.plant.pGeneral.numAxillaryInflors)
            numAlready = self.plant.numAxillaryActiveReproductiveMeristemsOrInflorescences
            numInactive = max(1, self.plant.numAxillaryInactiveReproductiveMeristems)
            inflorProb = umath.safedivExcept(numExpected - numAlready, numInactive, 0)
        if numExpected <= 3:
            inflorProb = 1.0
        if self.plant.randomNumberGenerator.zeroToOne() < inflorProb:
            result = numAlready < numExpected
        return result
