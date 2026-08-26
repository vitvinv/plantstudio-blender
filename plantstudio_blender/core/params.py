"""Parameter containers for PlantStudio plant species.

Mirrors the original pGeneral / pMeristem / pInternode / pLeaf /
pInflorescence / pFruit / pFlower / pTDO parameter objects.

Attributes are set generically by the .pla parser using the access
strings from the PlantStudio parameter registry (e.g. 'pGeneral.LineDivisions').
"""


class ParamObject:
    """Base class: a parameter object that accepts arbitrary attributes."""

    def __init__(self):
        pass

    def __repr__(self):
        attrs = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        return f"{type(self).__name__}({attrs})"


class TdoParams:
    """Parameters for drawing a 3D object (scale, rotations, colors)."""

    def __init__(self):
        self.object3D = None      # ParsedTdo or None
        self.scaleAtFullSize = 0.0
        self.xRotationBeforeDraw = 0.0
        self.yRotationBeforeDraw = 0.0
        self.zRotationBeforeDraw = 0.0
        self.faceColor = None     # (r, g, b) 0-255
        self.backfaceColor = None
        self.repetitions = 1      # number of radial sections
        self.radiallyArranged = True
        self.pullBackAngle = 0.0
        self.pullBackAngleRange = 0.0


class PlantParams:
    """All parameters for one plant species, organized by section."""

    def __init__(self):
        self.pGeneral = ParamObject()
        self.pMeristem = ParamObject()
        self.pInternode = ParamObject()
        self.pLeaf = ParamObject()
        self.pSeedlingLeaf = ParamObject()
        self.pInflorescence = ParamObject()
        self.pFruit = ParamObject()
        self.pRoot = ParamObject()
        # flower params keyed by gender (pFlower[kGenderFemale].*) — the
        # flower's own parameters (petal rows, optimal biomass, etc.)
        self.flowers = {}
        # inflorescence params keyed by gender (pInflor[kGenderFemale].*) —
        # the inflorescence's parameters (stalks, bracts, flower counts).
        # Kept SEPARATE from pFlower, matching the original model; merging
        # them caused the flower's OptimalBiomass_pctMPB to be shadowed by
        # the inflorescence's optimalBiomass_pctMPB.
        self.inflors = {}
        # 3D object params (bud, leaf, stipule, seedling, inflorescence, fruit)
        self.pAxillaryBud = TdoParams()
        self.pAxillaryBudParams = ParamObject()
        self.leafTdoParams = TdoParams()
        self.stipuleTdoParams = TdoParams()
        self.seedlingTdoParams = TdoParams()

    def section(self, name):
        """Return the parameter object for an access string prefix."""
        return getattr(self, name)
