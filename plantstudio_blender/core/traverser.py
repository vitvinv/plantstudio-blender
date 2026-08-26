"""PdTraverser port — walk the phytomer tree applying activities."""

from .meristem import (kActivityDraw, kActivityFree, kTraverseLeft, kTraverseRight,
                       kTraverseNext, kTraverseDone, kTraverseNone)


class PdTraverser:
    def __init__(self, plant):
        self.plant = plant
        self.total = 0.0
        self.fractionOfPotentialBiomass = 0.0
        self.ageOfYoungestPhytomer = 0
        self.mode = 0
        self.finished = False
        self.currentPhytomer = None
        self.totalPlantParts = 0

    def beginTraversal(self, aMode):
        self.mode = aMode
        self.currentPhytomer = self.plant.firstPhytomer
        self.total = 0.0
        self.finished = False
        self.totalPlantParts = 0
        if self.currentPhytomer is not None:
            self.currentPhytomer.traversingDirection = kTraverseLeft
            self.currentPhytomer.traverseActivity(aMode, self)
            self.currentPhytomer.traversingDirection = kTraverseLeft

    def traverseWholePlant(self, aMode):
        self.beginTraversal(aMode)
        self._traversePlant(0)

    def _traversePlant(self, traversalCount):
        if self.currentPhytomer is None:
            return
        phytomer = self.currentPhytomer
        i = 0
        while i <= traversalCount:
            if self.finished:
                return
            if phytomer.traversingDirection == kTraverseLeft:
                phytomer.traversingDirection += 1
                if phytomer.leftBranchPlantPart is not None:
                    if self.mode == kActivityDraw:
                        self.plant.turtle.push()
                    part = phytomer.leftBranchPlantPart
                    part.traverseActivity(self.mode, self)
                    if part.isPhytomer():
                        phytomer = part
                        phytomer.traversingDirection = kTraverseLeft
                    elif self.mode == kActivityDraw:
                        self.plant.turtle.pop()
            elif phytomer.traversingDirection == kTraverseRight:
                phytomer.traversingDirection += 1
                if phytomer.rightBranchPlantPart is not None:
                    if self.mode == kActivityDraw:
                        self.plant.turtle.push()
                    part = phytomer.rightBranchPlantPart
                    part.traverseActivity(self.mode, self)
                    if part.isPhytomer():
                        phytomer = part
                        phytomer.traversingDirection = kTraverseLeft
                    elif self.mode == kActivityDraw:
                        self.plant.turtle.pop()
            elif phytomer.traversingDirection == kTraverseNext:
                phytomer.traversingDirection += 1
                if phytomer.nextPlantPart is not None:
                    if self.mode == kActivityDraw:
                        self.plant.turtle.push()
                        self.plant.turtle.rotateX(
                            self.plant.pGeneral.phyllotacticRotationAngle * 256 / 360)
                    part = phytomer.nextPlantPart
                    part.traverseActivity(self.mode, self)
                    if part.isPhytomer():
                        phytomer = part
                        phytomer.traversingDirection = kTraverseLeft
                    elif self.mode == kActivityDraw:
                        self.plant.turtle.pop()
            elif phytomer.traversingDirection == kTraverseDone:
                phytomer.traversingDirection = kTraverseNone
                lastPhytomer = phytomer
                phytomer = phytomer.phytomerAttachedTo
                if self.mode == kActivityFree:
                    if phytomer is not None:
                        if phytomer.traversingDirection == kTraverseLeft + 1:
                            phytomer.leftBranchPlantPart = None
                        elif phytomer.traversingDirection == kTraverseRight + 1:
                            phytomer.rightBranchPlantPart = None
                        elif phytomer.traversingDirection == kTraverseNext + 1:
                            phytomer.nextPlantPart = None
                if phytomer is None:
                    break
                if self.mode == kActivityDraw:
                    self.plant.turtle.pop()
            elif phytomer.traversingDirection == kTraverseNone:
                raise RuntimeError("kTraverseNone encountered in traversePlant")
            if traversalCount != 0:
                i += 1
