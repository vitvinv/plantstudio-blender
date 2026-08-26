"""Normalize parsed species params into the attribute names the simulation uses.

The .pla parser sets attributes using the exact access strings from the
PlantStudio registry (mixed case, e.g. 'OptimalFinalBiomass_pctMPB').
The simulation code uses snake_case names. This module maps between them
and fills defaults for parameters absent from a species file.
"""

import os
import json

from .math3d import SCurve  # noqa: F401 (kept for clarity)


def _load_registry_defaults():
    """Registry access string -> parsed default, loaded once.

    Keyed by (section, attr) lowercased so the snake_case attr names the
    simulation uses resolve against the registry's mixed-case access names.
    Only plain 'pSection.attr' accesses participate (flower rows and TDO
    embedded blocks are handled separately).
    """
    lookup = {}
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "param_registry.json")
    try:
        with open(path, encoding="utf-8") as f:
            registry = json.load(f)
    except (OSError, ValueError):
        return lookup
    for entry in registry:
        access = entry.get("access", "")
        if "." not in access or "[" in access:
            continue
        section, _, attr = access.partition(".")
        if "." in attr:
            continue  # e.g. pLeaf.leafTdoParams.scaleAtFullSize — not here
        if entry.get("id") == "header":
            continue
        lookup[(section.lower(), attr.lower())] = (entry["type"], entry.get("default"))
    return lookup


_REGISTRY_DEFAULTS = _load_registry_defaults()


def _parse_registry_default(ftype, raw):
    """Parse a registry default string into a Python value."""
    if raw is None:
        return None
    text = str(raw).strip()
    if ftype == 4:  # boolean
        return text.lower() in ("true", "yes", "1", "t")
    if ftype == 3:  # color
        from .pla_parser import parse_color
        return parse_color(text)
    if ftype == 2 or ftype == 8:  # smallint / longint
        try:
            return int(float(text.split()[0]))
        except (ValueError, IndexError):
            return text
    if ftype == 1:  # float
        try:
            return float(text.split()[0])
        except (ValueError, IndexError):
            return text
    if ftype == 6:  # enum
        try:
            return int(float(text.split()[0]))
        except (ValueError, IndexError):
            return text
    return text


def registry_default(section, attr, fallback):
    """Registry default for (section, attr), or fallback when absent.

    section: 'pGeneral' / 'pMeristem' / 'pInternode' / 'pLeaf' etc.
    attr: the snake_case attr name the simulation reads.
    """
    parsed = _REGISTRY_DEFAULTS.get((section.lower(), attr.lower()))
    if parsed is None:
        return fallback
    ftype, raw = parsed
    value = _parse_registry_default(ftype, raw)
    if value is None:
        return fallback
    return value


def _get(obj, *names, default=None):
    for n in names:
        if obj is not None and hasattr(obj, n):
            return getattr(obj, n)
    return default


def _ensure(obj, name, value):
    if not hasattr(obj, name):
        setattr(obj, name, value)
    return getattr(obj, name)


def normalize_general(params):
    g = params.pGeneral
    _ensure(g, "lineDivisions",
            int(_get(g, "LineDivisions", default=registry_default("pGeneral", "lineDivisions", 3))))
    _ensure(g, "randomSway",
            float(_get(g, "randomSway", default=registry_default("pGeneral", "randomSway", 0.0))))
    _ensure(g, "ageAtMaturity",
            float(_get(g, "ageAtMaturity", default=registry_default("pGeneral", "ageAtMaturity", 100))))
    _ensure(g, "ageAtWhichFloweringStarts",
            float(_get(g, "ageAtWhichFloweringStarts",
                       default=registry_default("pGeneral", "ageAtWhichFloweringStarts", 60))))
    _ensure(g, "fractionReproductiveAllocationAtMaturity_frn",
            float(_get(g, "fractionReproductiveAllocationAtMaturity_frn",
                       default=registry_default("pGeneral",
                                                "fractionReproductiveAllocationAtMaturity_frn", 0.6))))
    _ensure(g, "maleFlowersAreSeparate",
            bool(_get(g, "MaleFlowersAreSeparate",
                      default=registry_default("pGeneral", "maleFlowersAreSeparate", False))))
    _ensure(g, "isDicot",
            bool(_get(g, "IsDicot", default=registry_default("pGeneral", "isDicot", True))))
    _ensure(g, "numApicalInflors",
            int(_get(g, "NumApicalInflors",
                     default=registry_default("pGeneral", "numApicalInflors", 0))))
    _ensure(g, "numAxillaryInflors",
            int(_get(g, "NumAxillaryInflors",
                     default=registry_default("pGeneral", "numAxillaryInflors", 4))))
    _ensure(g, "phyllotacticRotationAngle",
            float(_get(g, "phyllotacticRotationAngle",
                       default=registry_default("pGeneral", "phyllotacticRotationAngle", 137.5))))
    _ensure(g, "startingSeedForRandomNumberGenerator",
            int(_get(g, "startingSeedForRandomNumberGenerator",
                     default=registry_default("pGeneral",
                                              "startingSeedForRandomNumberGenerator", 1234))))
    # growth curve: 4-value string -> SCurve
    if not hasattr(g, "growthSCurve") or not isinstance(getattr(g, "growthSCurve"), SCurve):
        raw = _get(g, "growthSCurve", default="0.25 0.1 0.65 0.85")
        g.growthSCurve = _parse_scurve(raw)


def normalize_meristem(params):
    m = params.pMeristem
    _ensure(m, "branchingAndLeafArrangement",
            int(_get(m, "branchingAndLeafArrangement",
                     default=registry_default("pMeristem", "branchingAndLeafArrangement", 0))))
    _ensure(m, "branchingIndex",
            float(_get(m, "BranchingIndex",
                       default=registry_default("pMeristem", "branchingIndex", 30.0))))
    _ensure(m, "branchingDistance",
            float(_get(m, "BranchingDistance",
                       default=registry_default("pMeristem", "branchingDistance", 3.0))))
    _ensure(m, "secondaryBranchingIsAllowed",
            bool(_get(m, "secondaryBranchingIsAllowed",
                      default=registry_default("pMeristem", "secondaryBranchingIsAllowed", False))))
    _ensure(m, "branchingIsSympodial",
            bool(_get(m, "BranchingIsSympodial",
                      default=registry_default("pMeristem", "branchingIsSympodial", False))))
    _ensure(m, "branchingAngle",
            float(_get(m, "branchingAngle",
                       default=registry_default("pMeristem", "branchingAngle", 30.0))))
    _ensure(m, "determinateProbability",
            # registry default (30) is a leftover data quirk; a from-scratch
            # plant must default to fully determinate (1.0)
            float(_get(m, "DeterminateProbability", default=1.0)))


def normalize_internode(params):
    i = params.pInternode
    _ensure(i, "faceColor", _get(i, "FaceColor", default=(50, 100, 50)))
    _ensure(i, "firstInternodeCurvingIndex",
            float(_get(i, "firstInternodeCurvingIndex",
                       default=registry_default("pInternode", "firstInternodeCurvingIndex", 10.0))))
    _ensure(i, "curvingIndex",
            float(_get(i, "curvingIndex", default=registry_default("pInternode", "curvingIndex", 30.0))))
    _ensure(i, "lengthAtOptimalFinalBiomassAndExpansion_mm",
            float(_get(i, "LengthAtOptimalFinalBiomassAndExpansion_mm",
                       default=registry_default("pInternode",
                                                "lengthAtOptimalFinalBiomassAndExpansion_mm", 60.0))))
    _ensure(i, "widthAtOptimalFinalBiomassAndExpansion_mm",
            float(_get(i, "WidthAtOptimalFinalBiomassAndExpansion_mm",
                       default=registry_default("pInternode",
                                                "widthAtOptimalFinalBiomassAndExpansion_mm", 3.0))))
    _ensure(i, "optimalFinalBiomass_pctMPB",
            float(_get(i, "OptimalFinalBiomass_pctMPB",
                       default=registry_default("pInternode", "optimalFinalBiomass_pctMPB", 4.0))))
    _ensure(i, "minDaysToCreateInternode",
            int(_get(i, "MinDaysToCreateInternode",
                     default=registry_default("pInternode", "minDaysToCreateInternode", 3))))
    _ensure(i, "maxDaysToCreateInternodeIfOverMinFraction",
            int(_get(i, "MaxDaysToCreateInternodeIfOverMinFraction",
                     default=registry_default("pInternode",
                                              "maxDaysToCreateInternodeIfOverMinFraction", 10))))
    _ensure(i, "minFractionOfOptimalInitialBiomassToCreateInternode_frn",
            float(_get(i, "MinFractionOfOptimalInitialBiomassToCreateInternode_frn",
                       default=registry_default("pInternode",
                                                "minFractionOfOptimalInitialBiomassToCreateInternode_frn", 0.2))))
    _ensure(i, "canRecoverFromStuntingDuringCreation",
            bool(_get(i, "CanRecoverFromStuntingDuringCreation",
                      default=registry_default("pInternode",
                                               "canRecoverFromStuntingDuringCreation", True))))
    _ensure(i, "minDaysToAccumulateBiomass",
            int(_get(i, "MinDaysToAccumulateBiomass",
                     default=registry_default("pInternode", "minDaysToAccumulateBiomass", 3))))
    _ensure(i, "maxDaysToAccumulateBiomass",
            int(_get(i, "MaxDaysToAccumulateBiomass",
                     default=registry_default("pInternode", "maxDaysToAccumulateBiomass", 10))))
    _ensure(i, "lengthMultiplierDueToBolting",
            float(_get(i, "LengthMultiplierDueToBolting",
                       default=registry_default("pInternode", "lengthMultiplierDueToBolting", 0.0))))
    _ensure(i, "minDaysToBolt",
            int(_get(i, "MinDaysToBolt", default=registry_default("pInternode", "minDaysToBolt", 10))))
    # biomass accretion multipliers (not in .pla; source defaults to 1)
    _ensure(i, "lengthMultiplierDueToBiomassAccretion", 1.0)
    _ensure(i, "widthMultiplierDueToBiomassAccretion", 1.0)


def normalize_leaf(params):
    lf = params.pLeaf
    _ensure(lf, "faceColor", _get(lf, "FaceColor", default=(50, 250, 50)))
    _ensure(lf, "backfaceColor", _get(lf, "BackfaceColor", default=(50, 150, 50)))
    _ensure(lf, "petioleColor", _get(lf, "PetioleColor", default=(50, 100, 50)))
    _ensure(lf, "petioleAngle",
            float(_get(lf, "PetioleAngle", default=registry_default("pLeaf", "petioleAngle", 40.0))))
    _ensure(lf, "petioleLengthAtOptimalBiomass_mm",
            float(_get(lf, "PetioleLengthAtOptimalBiomass_mm",
                       default=registry_default("pLeaf", "petioleLengthAtOptimalBiomass_mm", 30.0))))
    _ensure(lf, "petioleWidthAtOptimalBiomass_mm",
            float(_get(lf, "PetioleWidthAtOptimalBiomass_mm",
                       default=registry_default("pLeaf", "petioleWidthAtOptimalBiomass_mm", 1.0))))
    _ensure(lf, "petioleTaperIndex",
            int(_get(lf, "petioleTaperIndex", default=registry_default("pLeaf", "petioleTaperIndex", 100))))
    _ensure(lf, "compoundNumLeaflets",
            # registry default (0) would render leaves with no leaflets;
            # a from-scratch plant must have at least one leaflet
            int(_get(lf, "CompoundNumLeaflets", default=1)))
    _ensure(lf, "compoundPinnateOrPalmate",
            int(_get(lf, "CompoundPinnateOrPalmate",
                     default=registry_default("pLeaf", "compoundPinnateOrPalmate", 0))))
    _ensure(lf, "compoundPinnateLeafletArrangement",
            int(_get(lf, "compoundPinnateLeafletArrangement",
                     default=registry_default("pLeaf", "compoundPinnateLeafletArrangement", 0))))
    _ensure(lf, "compoundRachisToPetioleRatio",
            float(_get(lf, "CompoundRachisToPetioleRatio",
                       default=registry_default("pLeaf", "compoundRachisToPetioleRatio", 30.0))))
    _ensure(lf, "compoundCurveAngleAtStart",
            float(_get(lf, "compoundCurveAngleAtStart",
                       default=registry_default("pLeaf", "compoundCurveAngleAtStart", 0.0))))
    _ensure(lf, "compoundCurveAngleAtFullSize",
            float(_get(lf, "compoundCurveAngleAtFullSize",
                       default=registry_default("pLeaf", "compoundCurveAngleAtFullSize", 4.0))))
    _ensure(lf, "optimalBiomass_pctMPB",
            float(_get(lf, "optimalBiomass_pctMPB",
                       default=registry_default("pLeaf", "optimalBiomass_pctMPB", 5.0))))
    _ensure(lf, "optimalFractionOfOptimalBiomassAtCreation_frn",
            float(_get(lf, "optimalFractionOfOptimalBiomassAtCreation_frn",
                       default=registry_default("pLeaf",
                                                "optimalFractionOfOptimalBiomassAtCreation_frn", 0.2))))
    _ensure(lf, "minDaysToGrow",
            int(_get(lf, "minDaysToGrow", default=registry_default("pLeaf", "minDaysToGrow", 3))))
    _ensure(lf, "maxDaysToGrow",
            int(_get(lf, "MaxDaysToGrow", default=registry_default("pLeaf", "maxDaysToGrow", 10))))
    if not hasattr(lf, "sCurveParams") or not isinstance(getattr(lf, "sCurveParams"), SCurve):
        lf.sCurveParams = _parse_scurve(_get(lf, "sCurveParams", default="0.25 0.1 0.65 0.85"))


def normalize_seedling(params):
    sl = params.pSeedlingLeaf
    # Natural PlantStudio behavior: seedling leaves fall off after N nodes
    _ensure(sl, "nodesOnStemWhenFallsOff", int(_get(sl, "NodesOnStemWhenFallsOff", default=3)))
    _ensure(sl, "scaleAtFullSize", float(_get(sl, "ScaleAtFullSize", default=20.0)))
    # Seedling TDO params live at the params root (params.seedlingTdoParams).
    # The .pla stores them under 'pSeedlingLeaf.leafTdoParams.*', which the
    # parser routes here.
    tdo = getattr(params, "seedlingTdoParams", None)
    if tdo is None:
        from .params import TdoParams
        tdo = TdoParams()
        params.seedlingTdoParams = tdo
    for attr, default in (("scaleAtFullSize", 20.0),
                          ("xRotationBeforeDraw", 0.0),
                          ("yRotationBeforeDraw", 0.0),
                          ("zRotationBeforeDraw", 0.0),
                          ("repetitions", 1),
                          ("radiallyArranged", True)):
        if not hasattr(tdo, attr):
            setattr(tdo, attr, default)
    if not hasattr(tdo, "faceColor") or not getattr(tdo, "faceColor"):
        tdo.faceColor = (50, 200, 50)
    if not hasattr(tdo, "backfaceColor") or not getattr(tdo, "backfaceColor"):
        tdo.backfaceColor = (50, 150, 50)


def normalize_flowers(params):
    """Normalize pFlower[kGender]* params (the flower's OWN parameters).

    These are separate from pInflor (inflorescence) params in the original
    model; keeping them in separate dicts is what lets the flower's
    OptimalBiomass_pctMPB survive un-shadowed by the inflorescence's
    optimalBiomass_pctMPB.
    """
    for gender in ("kGenderFemale", "kGenderMale"):
        d = params.flowers.setdefault(gender, {})
        # lowercase aliases for mixed-case parsed keys (IsTerminal etc.)
        for key, val in list(d.items()):
            lk = key[:1].lower() + key[1:]
            if lk != key and lk not in d:
                d[lk] = val
        defaults = {
            "optimalBiomass_pctMPB": 1.0,
            "minFractionOfOptimalBiomassToOpenFlower_frn": 0.5,
            "minFractionOfOptimalBiomassToCreateFruit_frn": 0.8,
            "minDaysToGrow": 3,
            "maxDaysToGrowIfOverMinFraction": 30,
            "minDaysToOpenFlower": 3,
            "minDaysBeforeSettingFruit": 3,
        }
        for key, val in defaults.items():
            if key not in d:
                d[key] = val
        # fill defaults for flower TDO rows (petals, sepals, etc.)
        # TdoParamsCompat defaults to scaleAtFullSize=0 — override with
        # meaningful values so flowers are visible.
        tdo_params = d.get("tdoParams", None)
        if tdo_params is None:
            tdo_params = {}
            d["tdoParams"] = tdo_params
        row_keys = ["kFirstPetals", "kSecondPetals", "kThirdPetals",
                    "kFourthPetals", "kFifthPetals", "kPistils",
                    "kStamens", "kSepals", "kBud"]
        for row in row_keys:
            if row not in tdo_params:
                # Use the same container type the parser creates so later
                # set_param/wizard writes (which expect attribute access)
                # work on any row, not just ones present in the .pla.
                from .pla_parser import TdoParamsCompat
                tdo_params[row] = TdoParamsCompat()
            tdo_obj = tdo_params[row]
            # Zero-scale rows are intentionally disabled in the data (the
            # original skips them at draw time) — do NOT inject a scale.
            # Only default the color so rows that draw always have one.
            if isinstance(tdo_obj, dict):
                tdo_obj.setdefault("faceColor", (200, 200, 60))
            else:
                if not hasattr(tdo_obj, "faceColor") or not getattr(tdo_obj, "faceColor"):
                    setattr(tdo_obj, "faceColor", (200, 200, 60))


def normalize_inflors(params):
    """Normalize pInflor[kGender]* params (inflorescence-level parameters)."""
    for gender in ("kGenderFemale", "kGenderMale"):
        d = params.inflors.setdefault(gender, {})
        # lowercase aliases for mixed-case parsed keys
        for key, val in list(d.items()):
            lk = key[:1].lower() + key[1:]
            if lk != key and lk not in d:
                d[lk] = val
        defaults = {
            "optimalBiomass_pctMPB": 1.0,
            "minFractionOfOptimalBiomassToCreateInflorescence_frn": 0.5,
            "minFractionOfOptimalBiomassToMakeFlowers_frn": 0.5,
            "minDaysToCreateInflorescence": 3,
            "maxDaysToCreateInflorescenceIfOverMinFraction": 10,
            "minDaysToGrow": 3,
            "maxDaysToGrow": 10,
            "numFlowersOnMainBranch": 1,
            "numFlowersPerBranch": 1,
            "numBranches": 0,
            "daysToAllFlowersCreated": 10,
        }
        for key, val in defaults.items():
            if key not in d:
                d[key] = val


def normalize_fruit(params):
    """Ensure pFruit has a tdoParams container and ripening defaults.

    Missing fruit data (object3D/scale/color) is NOT an error here — it
    surfaces as AssetError at draw time if a fruit is actually drawn.
    """
    f = params.pFruit
    if not hasattr(f, "tdoParams"):
        from .params import TdoParams
        f.tdoParams = TdoParams()
    _ensure(f, "optimalBiomass_pctMPB",
            float(_get(f, "optimalBiomass_pctMPB", default=5.0)))
    _ensure(f, "minDaysToGrow",
            int(_get(f, "MinDaysToGrow", default=7)))
    _ensure(f, "maxDaysToGrow",
            int(_get(f, "MaxDaysToGrow", default=20)))
    if not hasattr(f, "sCurveParams") or not isinstance(getattr(f, "sCurveParams"), SCurve):
        f.sCurveParams = _parse_scurve(_get(f, "sCurveParams",
                                              default="0.25 0.1 0.65 0.85"))
    _ensure(f, "daysToRipen", float(_get(f, "DaysToRipen", default=5)))


def normalize_params(params):
    """Apply all normalizations so a species is simulation-ready."""
    normalize_general(params)
    normalize_meristem(params)
    normalize_internode(params)
    normalize_leaf(params)
    normalize_seedling(params)
    normalize_flowers(params)
    normalize_inflors(params)
    normalize_fruit(params)
    # leaf tdo params accessors used by drawing
    name = getattr(params, "name", "unknown species")
    for container in ("leafTdoParams", "stipuleTdoParams", "seedlingTdoParams", "pAxillaryBud"):
        tdo = getattr(params, container, None)
        if tdo is not None:
            # Broken object3D references ("Default", "Default tdo") are NOT
            # rewritten here — they surface as AssetError at draw time when
            # resolve_tdo() is called for that specific plant part.
            for attr in ("scaleAtFullSize", "xRotationBeforeDraw",
                         "yRotationBeforeDraw", "zRotationBeforeDraw",
                         "faceColor", "backfaceColor", "repetitions", "radiallyArranged"):
                if not hasattr(tdo, attr):
                    setattr(tdo, attr, 0.0 if "Rotation" in attr or "Scale" in attr
                            else (1 if attr == "repetitions" else
                                  (True if attr == "radiallyArranged" else
                                   ((50, 200, 50) if "Color" in attr else 0.0))))
    return params


def _parse_scurve(raw):
    if isinstance(raw, SCurve):
        return raw
    if isinstance(raw, (list, tuple)) and len(raw) >= 4:
        return SCurve(float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
    parts = str(raw).split()
    if len(parts) >= 4:
        try:
            return SCurve(float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))
        except ValueError:
            pass
    return SCurve()
