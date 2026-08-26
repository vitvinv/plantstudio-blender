"""PdPlant port — the whole plant: growth, biomass allocation, traversal."""

from .rng import PdRandom
from . import math3d as umath
from .meristem import (PdMeristem, kArrangementAlternate,
                       kActivityNextDay, kActivityDemandVegetative,
                       kActivityDemandReproductive, kActivityGrowVegetative,
                       kActivityGrowReproductive, kActivityStartReproduction,
                       kActivityVegetativeBiomassThatCanBeRemoved,
                       kActivityRemoveVegetativeBiomass,
                       kActivityReproductiveBiomassThatCanBeRemoved,
                       kActivityRemoveReproductiveBiomass)
from .traverser import PdTraverser


def cancelOutOppositeAmounts(add, remove):
    if add > 0 and remove > 0:
        if add > remove:
            add -= remove
            remove = 0.0
        else:
            remove -= add
            add = 0.0
    return add, remove


class PdPlant:
    def __init__(self, params, seed=None, maxPartsPerPlant=20000):
        self.params = params
        self.pGeneral = params.pGeneral
        self.pMeristem = params.pMeristem
        self.pInternode = params.pInternode
        self.pLeaf = params.pLeaf
        self.pSeedlingLeaf = params.pSeedlingLeaf
        self.pAxillaryBud = params.pAxillaryBud
        # flowers normalized as dicts with snake_case keys; pFlower and
        # pInflor are SEPARATE sections in the original (flower's own
        # parameters vs the inflorescence's), so keep them separate.
        self.pFlower = {
            0: params.flowers.get("kGenderFemale", {}),
            1: params.flowers.get("kGenderMale", {}),
        }
        self.pInflor = {
            0: params.inflors.get("kGenderFemale", {}),
            1: params.inflors.get("kGenderMale", {}),
        }
        name = getattr(params, "name", "plant")
        # If the plant will produce inflorescences but has no flower section
        # in its .pla data, that's a data problem — surface it instead of
        # silently substituting defaults.
        num_ap = int(getattr(params.pGeneral, "numApicalInflors", 0) or 0)
        num_ax = int(getattr(params.pGeneral, "numAxillaryInflors", 0) or 0)
        if (num_ap > 0 or num_ax > 0):
            if not self.pFlower[0]:
                from .tdo_parser import AssetError
                raise AssetError(
                    f"species '{name}' is configured to produce inflorescences "
                    f"(numApicalInflors={num_ap}, numAxillaryInflors={num_ax}) "
                    f"but has no kGenderFemale flower section in its .pla data")
        if not self.pFlower[0]:
            self.pFlower[0] = _default_flower_params()
        if not self.pFlower[1]:
            self.pFlower[1] = _default_flower_params()
        if not self.pInflor[0]:
            self.pInflor[0] = _default_inflor_params()
        if not self.pInflor[1]:
            self.pInflor[1] = _default_inflor_params()

        self.name = getattr(params, "name", "plant")
        self.maxPartsPerPlant = maxPartsPerPlant
        self.partsCreated = 0

        # RNG: deterministic from species seed or explicit override
        self.randomNumberGenerator = PdRandom()
        if seed is None:
            seed = getattr(self.pGeneral, "startingSeedForRandomNumberGenerator", 1234)
        self.randomNumberGenerator.setSeed(int(seed))
        self.seed = int(seed)

        # growth state
        self.age = 0
        self.totalBiomass_pctMPB = 0.0
        self.shootBiomass_pctMPB = 0.0
        self.reproBiomass_pctMPB = 0.0
        self.changeInShootBiomassToday_pctMPB = 0.0
        self.changeInReproBiomassToday_pctMPB = 0.0
        self.unallocatedNewVegetativeBiomass_pctMPB = 0.0
        self.unallocatedNewReproductiveBiomass_pctMPB = 0.0
        self.unremovedDeadVegetativeBiomass_pctMPB = 0.0
        self.unremovedDeadReproductiveBiomass_pctMPB = 0.0
        self.floweringHasStarted = False
        self.ageAtWhichFloweringStarted = 0
        self.firstPhytomer = None
        self.needToRecalculateColors = True
        self.turtle = None
        self.tdoLibrary = None
        self.ageOfYoungestPhytomer = 0
        self._apicalMeristemCount = 0
        self._axillaryMeristemCount = 0
        # reproductive meristem counters (maintained by meristem setters)
        self.numApicalActiveReproductiveMeristemsOrInflorescences = 0
        self.numAxillaryActiveReproductiveMeristemsOrInflorescences = 0
        self.numApicalInactiveReproductiveMeristems = 0
        self.numAxillaryInactiveReproductiveMeristems = 0

    # ── growth ──

    def nextDay(self):
        fractionToMaturity = umath.safedivExcept(self.age, self.pGeneral.ageAtMaturity, 0)
        newTotal = umath.max(0.0, umath.min(100.0,
                            100.0 * umath.scurve(fractionToMaturity,
                                                 self.pGeneral.growthSCurve.c1,
                                                 self.pGeneral.growthSCurve.c2)))
        changeTotal = newTotal - self.totalBiomass_pctMPB
        self.totalBiomass_pctMPB = newTotal

        if self.floweringHasStarted:
            fractionRepro = umath.max(0.0, self.pGeneral.fractionReproductiveAllocationAtMaturity_frn *
                                      umath.safedivExcept(
                                          self.age - self.ageAtWhichFloweringStarted,
                                          self.pGeneral.ageAtMaturity - self.ageAtWhichFloweringStarted, 0))
            newRepro = fractionRepro * self.totalBiomass_pctMPB
            self.changeInReproBiomassToday_pctMPB = newRepro - self.reproBiomass_pctMPB
            self.reproBiomass_pctMPB = newRepro
            newShoot = self.totalBiomass_pctMPB - self.reproBiomass_pctMPB
            self.changeInShootBiomassToday_pctMPB = newShoot - self.shootBiomass_pctMPB
            self.shootBiomass_pctMPB = newShoot
        else:
            self.changeInReproBiomassToday_pctMPB = 0.0
            self.changeInShootBiomassToday_pctMPB = changeTotal
            self.shootBiomass_pctMPB = self.totalBiomass_pctMPB

        traverser = PdTraverser(self)
        if self.firstPhytomer is None:
            firstMeristem = PdMeristem(self)
            firstMeristem.initializeWithPlant()
            self.firstPhytomer = firstMeristem.createFirstPhytomer()
            if self.firstPhytomer is None:
                return
            self.firstPhytomer.setAsFirstPhytomer()
            self.changeInShootBiomassToday_pctMPB -= firstMeristem.optimalInitialPhytomerBiomass_pctMPB()

        if not self.floweringHasStarted and self.age >= self.pGeneral.ageAtWhichFloweringStarts:
            self.floweringHasStarted = True
            self.ageAtWhichFloweringStarted = self.age
            traverser.traverseWholePlant(kActivityStartReproduction)

        self._allocateOrRemoveBiomassWithTraverser(traverser)
        if self.firstPhytomer is not None:
            traverser.ageOfYoungestPhytomer = 2**31 - 1
        else:
            traverser.ageOfYoungestPhytomer = 0
        traverser.traverseWholePlant(kActivityNextDay)
        self.ageOfYoungestPhytomer = traverser.ageOfYoungestPhytomer
        self.age += 1
        self.needToRecalculateColors = True

    def reset(self):
        """Discard simulated parts and restore the initial deterministic state."""
        self.age = 0
        self.firstPhytomer = None
        self.partsCreated = 0
        self.totalBiomass_pctMPB = 0.0
        self.shootBiomass_pctMPB = 0.0
        self.reproBiomass_pctMPB = 0.0
        self.changeInShootBiomassToday_pctMPB = 0.0
        self.changeInReproBiomassToday_pctMPB = 0.0
        self.unallocatedNewVegetativeBiomass_pctMPB = 0.0
        self.unallocatedNewReproductiveBiomass_pctMPB = 0.0
        self.unremovedDeadVegetativeBiomass_pctMPB = 0.0
        self.unremovedDeadReproductiveBiomass_pctMPB = 0.0
        self.floweringHasStarted = False
        self.ageAtWhichFloweringStarted = 0
        self.ageOfYoungestPhytomer = 0
        self.needToRecalculateColors = True
        self._apicalMeristemCount = 0
        self._axillaryMeristemCount = 0
        self.numApicalActiveReproductiveMeristemsOrInflorescences = 0
        self.numAxillaryActiveReproductiveMeristemsOrInflorescences = 0
        self.numApicalInactiveReproductiveMeristems = 0
        self.numAxillaryInactiveReproductiveMeristems = 0
        # Drawing and growth both consume the same deterministic stream.
        self.randomNumberGenerator.setSeed(self.seed)

    def setAge(self, newAge):
        """Set age by rebuilding the plant, matching PlantStudio semantics."""
        maturity = int(getattr(self.pGeneral, "ageAtMaturity", newAge))
        target = max(0, min(maturity, int(newAge)))
        self.reset()
        while self.age < target:
            self.nextDay()
        return self

    def growTo(self, day):
        if day < self.age:
            return self.setAge(day)
        while self.age < day:
            self.nextDay()
        return self

    # ── biomass allocation ──

    def _allocateOrRemoveBiomassWithTraverser(self, traverser):
        if self.firstPhytomer is None:
            return
        if self.changeInShootBiomassToday_pctMPB > 0:
            shootAddition = self.changeInShootBiomassToday_pctMPB + self.unallocatedNewVegetativeBiomass_pctMPB
            self.unallocatedNewVegetativeBiomass_pctMPB = 0.0
            shootReduction = 0.0
        else:
            shootReduction = self.changeInShootBiomassToday_pctMPB + self.unremovedDeadVegetativeBiomass_pctMPB
            self.unremovedDeadVegetativeBiomass_pctMPB = 0.0
            shootAddition = 0.0
        if self.changeInReproBiomassToday_pctMPB > 0:
            reproAddition = self.changeInReproBiomassToday_pctMPB + self.unallocatedNewReproductiveBiomass_pctMPB
            self.unallocatedNewReproductiveBiomass_pctMPB = 0.0
            reproReduction = 0.0
        else:
            reproReduction = self.changeInReproBiomassToday_pctMPB + self.unremovedDeadReproductiveBiomass_pctMPB
            self.unremovedDeadReproductiveBiomass_pctMPB = 0.0
            reproAddition = 0.0

        shootAddition, shootReduction = cancelOutOppositeAmounts(shootAddition, shootReduction)
        reproAddition, reproReduction = cancelOutOppositeAmounts(reproAddition, reproReduction)

        if shootAddition > 0.0:
            self.unallocatedNewVegetativeBiomass_pctMPB = self._allocateOrRemoveParticularBiomass(
                shootAddition, self.unallocatedNewVegetativeBiomass_pctMPB,
                kActivityDemandVegetative, kActivityGrowVegetative, traverser)
        if reproAddition > 0.0:
            self.unallocatedNewReproductiveBiomass_pctMPB = self._allocateOrRemoveParticularBiomass(
                reproAddition, self.unallocatedNewReproductiveBiomass_pctMPB,
                kActivityDemandReproductive, kActivityGrowReproductive, traverser)

    def _allocateOrRemoveParticularBiomass(self, biomass, undistributed, askingMode, tellingMode, traverser):
        traverser.traverseWholePlant(askingMode)
        totalDemand = traverser.total
        if totalDemand > 0.0:
            if biomass > totalDemand:
                undistributed = biomass - totalDemand
                traverser.fractionOfPotentialBiomass = 1.0
            else:
                traverser.fractionOfPotentialBiomass = umath.safedivExcept(biomass, totalDemand, 0)
            traverser.traverseWholePlant(tellingMode)
        else:
            undistributed = undistributed + biomass
        return undistributed

    # ── helpers ──

    def mainStemNodeCount(self):
        count = 0
        node = self.firstPhytomer
        while node is not None:
            count += 1
            node = node.nextPlantPart if node.nextPlantPart is not None and node.nextPlantPart.isPhytomer() else None
        return count

    def countMeristems(self):
        self._apicalMeristemCount = 0
        self._axillaryMeristemCount = 0
        traverser = PdTraverser(self)

        def count_part(part):
            if part.getName() == "meristem":
                if part.isApical:
                    self._apicalMeristemCount += 1
                else:
                    self._axillaryMeristemCount += 1

        if self.firstPhytomer is not None:
            stack = [self.firstPhytomer]
            seen = set()
            while stack:
                part = stack.pop()
                if part is None or id(part) in seen:
                    continue
                seen.add(id(part))
                count_part(part)
                stack.append(part.leftBranchPlantPart)
                stack.append(part.rightBranchPlantPart)
                stack.append(part.nextPlantPart)
                stack.append(part.leftLeaf)
                stack.append(part.rightLeaf)
                if hasattr(part, "flowers"):
                    stack.extend(part.flowers)

    def draw(self, turtle):
        self.turtle = turtle
        from .meristem import kActivityDraw
        if self.firstPhytomer is not None:
            traverser = PdTraverser(self)
            traverser.traverseWholePlant(kActivityDraw)


def _default_inflor_params():
    """Fallback inflorescence params when a species has no flower section."""
    class _P:
        optimalBiomass_pctMPB = 1.0
        minFractionOfOptimalBiomassToCreateInflorescence_frn = 0.5
        minFractionOfOptimalBiomassToMakeFlowers_frn = 0.5
        minDaysToCreateInflorescence = 3
        maxDaysToCreateInflorescenceIfOverMinFraction = 10
        minDaysToGrow = 3
        maxDaysToGrow = 10
        numFlowersOnMainBranch = 1
        numFlowersPerBranch = 1
        numBranches = 0
        daysToAllFlowersCreated = 10
    return _P()


def _default_flower_params():
    """Fallback flower params (pFlower) when a species has no flower section."""
    class _P:
        optimalBiomass_pctMPB = 1.0
        minFractionOfOptimalBiomassToOpenFlower_frn = 0.5
        minFractionOfOptimalBiomassToCreateFruit_frn = 0.8
        minDaysToGrow = 3
        maxDaysToGrowIfOverMinFraction = 30
        minDaysToOpenFlower = 3
        minDaysBeforeSettingFruit = 3
    return _P()
