"""PlantStudio-Blender realtime wizard — step-based plant editing.

Wizard steps (matching the original PlantStudio wizard):
  0. Meristems
  1. Internodes
  2. Leaves
  3. Compound leaves
  4. Inflorescence placement
  5. Inflorescence drawing   (active only if placement enabled)
  6. Flowers                 (active only if placement enabled)
  7. Fruits                  (active only if placement enabled)

Always-live: every knob change sets a dirty flag; a lightweight timer
(bpy.app.timers) rebuilds the selected plant's mesh in place. Per-plant
parameters are stored on each object (ps_knobs JSON).
"""

import json
import copy
import bpy
from bpy.types import PropertyGroup
from bpy.props import (FloatProperty, IntProperty, BoolProperty,
                       EnumProperty, FloatVectorProperty)

from .scene_bridge import COLLECTION_NAME

# ── knob definitions:
# (prop name, param path, label, min, max, default, step)
# steps: 0=Meristems 1=Internodes 2=Leaves 3=Compound leaves
#        4=Inflor placement 5=Inflor drawing 6=Flowers 7=Fruits

KNOB_DEFS = [
    # ── Step 0: Meristems ──
    ("knob_branch_index", "pMeristem.branchingIndex", "Branching index", 0, 100, 30, 0),
    ("knob_branch_dist", "pMeristem.branchingDistance", "Branching distance", 0, 10, 3, 0),
    ("knob_branch_angle", "pMeristem.branchingAngle", "Branch angle", 0, 180, 30, 0),
    ("knob_determinate", "pMeristem.determinateProbability", "Determinate prob.", 0.0, 1.0, 1.0, 0),
    ("knob_symp", "pMeristem.branchingIsSympodial", "Sympodial branching", 0, 1, 0, 0),
    ("knob_secondary", "pMeristem.secondaryBranchingIsAllowed", "Secondary branching", 0, 1, 0, 0),
    # ── Step 1: Internodes ──
    ("knob_internode_len", "pInternode.lengthAtOptimalFinalBiomassAndExpansion_mm", "Internode length", 0, 200, 60, 1),
    ("knob_internode_wid", "pInternode.widthAtOptimalFinalBiomassAndExpansion_mm", "Internode width", 0.1, 20, 3, 1),
    ("knob_internode_biomass", "pInternode.optimalFinalBiomass_pctMPB", "Internode biomass", 0.001, 20, 4, 1),
    ("knob_curve", "pInternode.curvingIndex", "Curving index", 0, 100, 30, 1),
    ("knob_first_curve", "pInternode.firstInternodeCurvingIndex", "First internode curve", 0, 100, 10, 1),
    ("knob_internode_days", "pInternode.minDaysToCreateInternode", "Internode days", 1, 50, 3, 1),
    # ── Step 2: Leaves ──
    ("knob_petiole_len", "pLeaf.petioleLengthAtOptimalBiomass_mm", "Petiole length", 0, 200, 30, 2),
    ("knob_petiole_wid", "pLeaf.petioleWidthAtOptimalBiomass_mm", "Petiole width", 0.1, 20, 1, 2),
    ("knob_petiole_angle", "pLeaf.petioleAngle", "Petiole angle", 0, 180, 40, 2),
    ("knob_leaf_biomass", "pLeaf.optimalBiomass_pctMPB", "Leaf biomass", 0.001, 30, 5, 2),
    ("knob_leaf_scale", "pLeaf.leafTdoParams.scaleAtFullSize", "Leaf size", 0.001, 200, 20, 2),
    ("knob_leaf_days", "pLeaf.maxDaysToGrow", "Leaf grow days", 1, 50, 10, 2),
    # ── Step 3: Compound leaves ──
    ("knob_leaflets", "pLeaf.compoundNumLeaflets", "Leaflets", 1, 30, 1, 3),
    ("knob_pinnate", "pLeaf.compoundPinnateOrPalmate", "Pinnate/Palmate", 0, 1, 0, 3),
    ("knob_rachis", "pLeaf.compoundRachisToPetioleRatio", "Rachis:petiole ratio", 0, 100, 30, 3),
    # ── Step 4: Inflorescence placement ──
    ("knob_flower_start", "pGeneral.ageAtWhichFloweringStarts", "Flowering starts", 0, 500, 60, 4),
    ("knob_num_apical", "pGeneral.numApicalInflors", "Apical inflorescences", 0, 20, 0, 4),
    ("knob_num_axillary", "pGeneral.numAxillaryInflors", "Axillary inflorescences", 0, 50, 0, 4),
    ("knob_repro_alloc", "pGeneral.fractionReproductiveAllocationAtMaturity_frn", "Repro allocation", 0.0, 1.0, 0.6, 4),
    # ── Step 5: Inflorescence drawing ──
    ("knob_stalk_len", "pInflor[kGenderFemale].TerminalStalkLength_mm", "Stalk length", 0, 200, 20, 5),
    ("knob_flr_main", "pInflor[kGenderFemale].numFlowersOnMainBranch", "Flowers on main branch", 1, 60, 4, 5),
    ("knob_flr_branch", "pInflor[kGenderFemale].numFlowersPerBranch", "Flowers per branch", 0, 30, 1, 5),
    ("knob_flr_branches", "pInflor[kGenderFemale].numBranches", "Secondary branches", 0, 10, 2, 5),
    ("knob_flr_days", "pInflor[kGenderFemale].daysToAllFlowersCreated", "Days to all flowers", 1, 50, 10, 5),
    # ── Step 6: Flowers ──
    ("knob_petals", "pFlower[kGenderFemale].tdoParams[kFirstPetals].repetitions", "Petals per flower", 1, 20, 5, 6),
    ("knob_petal_scale", "pFlower[kGenderFemale].tdoParams[kFirstPetals].scaleAtFullSize", "Petal size", 1, 200, 10, 6),
    ("knob_petal_angle", "pFlower[kGenderFemale].tdoParams[kFirstPetals].pullBackAngle", "Petal angle", -128, 128, 0, 6),
    ("knob_flower_biomass", "pFlower[kGenderFemale].optimalBiomass_pctMPB", "Flower biomass", 0.001, 20, 1, 6),
    # ── Step 7: Fruits ──
    ("knob_fruit_biomass", "pFlower[kGenderFemale].minFractionOfOptimalBiomassToCreateFruit_frn", "Fruit threshold", 0.1, 1.0, 0.8, 7),
    ("knob_fruit_days", "pFlower[kGenderFemale].minDaysBeforeSettingFruit", "Days to fruit", 1, 500, 3, 7),
]

STEP_NAMES = [
    "Meristems", "Internodes", "Leaves", "Compound leaves",
    "Inflorescence placement", "Inflorescence drawing", "Flowers", "Fruits",
]

# ── P4: shape-picker knobs (TDO name per part) ──
# (prop name, param path, label, step)
# Paths resolve via _set_param_by_path to the part's object3D name string.
SHAPE_KNOB_DEFS = [
    ("knob_bud_shape", "pAxillaryBud.object3D", "Axillary bud shape", 0),
    ("knob_leaf_shape", "pLeaf.leafTdoParams.object3D", "Leaf shape", 2),
    ("knob_stipule_shape", "pLeaf.stipuleTdoParams.object3D", "Stipule shape", 2),
    ("knob_petal_shape", "pFlower[kGenderFemale].tdoParams[kFirstPetals].object3D", "Petal shape", 6),
    ("knob_fruit_shape", "pFruit.tdoParams.object3D", "Fruit shape", 7),
]

# (prop name, param path, label, step) — colors stored as 0-255 tuple in params
COLOR_KNOB_DEFS = [
    ("knob_fruit_unripe_color", "pFruit.tdoParams.alternateFaceColor", "Unripe fruit color", 7),
]

DEFAULT_TDO_NAME = "Default 3D object"


def _tdo_name_items(self, context):
    """EnumProperty items: every named 3D object in the TDO library."""
    try:
        from .operators import get_library
        _, tdo_lib = get_library()
        names = sorted(tdo_lib.names()) if tdo_lib else []
    except Exception:
        names = []
    if not names:
        names = [DEFAULT_TDO_NAME]
    return [(n, n, "") for n in names]


def _tdo_enum_names():
    """Set of identifiers the shape enums currently accept."""
    try:
        return {item[0] for item in _tdo_name_items(None, None)}
    except Exception:
        return {DEFAULT_TDO_NAME}


def _tdo_default_index():
    """Integer default for function-backed shape enums (Blender 5 requirement).

    When an EnumProperty uses an items callback, Blender requires the default
    to be an integer index (string identifiers are rejected at registration).
    The item's identifier is the TDO name string, so reading the knob still
    yields the name; only the default must be the matching index.
    """
    try:
        items = _tdo_name_items(None, None)
    except Exception:
        return 0
    for i, item in enumerate(items):
        if item[0] == DEFAULT_TDO_NAME:
            return i
    return 0


def knobs_for_step(step):
    result = [k for k in KNOB_DEFS if k[6] == step]
    result += [k for k in SHAPE_KNOB_DEFS if k[3] == step]
    result += [k for k in COLOR_KNOB_DEFS if k[3] == step]
    return result


KNOB_INDEX = {d[0]: i for i, d in enumerate(KNOB_DEFS)}

# ── knob classification (P2a: draw-only knobs skip re-simulation) ──
# Growth-affecting knobs change the plant's structure/biomass during growTo()
# and therefore require a full create_plant + growTo. Draw-only knobs only
# affect geometry/material emitted at draw time and can reuse a cached plant.
GROWTH_KNOBS = {
    "knob_branch_index", "knob_branch_dist", "knob_determinate", "knob_symp",
    "knob_secondary", "knob_curve", "knob_first_curve",
    "knob_internode_biomass", "knob_internode_days",
    "knob_leaf_biomass", "knob_leaf_days",
    "knob_flower_start", "knob_num_apical", "knob_num_axillary",
    "knob_repro_alloc", "knob_flr_main", "knob_flr_branch",
    "knob_flr_branches", "knob_flr_days",
    "knob_flower_biomass", "knob_fruit_days", "knob_fruit_biomass",
}
DRAW_ONLY_KNOBS = {d[0] for d in KNOB_DEFS} - GROWTH_KNOBS

_loading = False      # guard: programmatic knob sets must not trigger rebuild
_rebuild_busy = False
_timer_handle = None
# P2a: last-grown plant + the fingerprint of growth-affecting state it
# was simulated with, so draw-only knob changes can skip growTo().
_cached_plant = None
_cached_fingerprint = None


def placement_enabled(knobs):
    """Steps 5-7 activate only if inflorescence placement is configured."""
    return int(knobs.knob_num_apical) > 0 or int(knobs.knob_num_axillary) > 0


def _knob_update(self, context):
    """Knob changed by the user — save to the selected plant, rebuild live.

    P2d: only mark dirty when an actual value changed since the last rebuild
    (float epsilon comparison), so spurious update callbacks don't waste
    rebuilds."""
    global _loading
    if _loading:
        return
    coll = bpy.data.collections.get(COLLECTION_NAME)
    if coll is None or not (0 <= self.selected_index < len(coll.objects)):
        return
    obj = coll.objects[self.selected_index]
    if _knobs_match_last_applied(obj, self):
        return
    self.dirty = True
    try:
        save_knobs_to_obj(obj, self)
    except Exception:
        pass
    _ensure_timer()


def _knobs_match_last_applied(obj, knobs):
    """True when every knob + day matches what was last rebuilt onto obj."""
    stored = obj.get("ps_knobs")
    if not stored:
        return False
    try:
        prev = json.loads(stored)
    except Exception:
        return False
    day = obj.get("ps_day")
    if day is not None and float(day) != float(knobs.knob_day):
        return False
    for pn, *_ in KNOB_DEFS:
        if pn in prev and abs(float(prev[pn]) - float(getattr(knobs, pn))) > 1e-6:
            return False
    for pn, *_ in SHAPE_KNOB_DEFS:
        if pn in prev and str(prev[pn]) != str(getattr(knobs, pn)):
            return False
    for pn, *_ in COLOR_KNOB_DEFS:
        if pn in prev:
            cur = [float(c) for c in getattr(knobs, pn)]
            prev_c = [float(c) for c in prev[pn]]
            if max(abs(a - b) for a, b in zip(prev_c, cur)) > 1e-6:
                return False
    return True


def _on_select(self, context):
    """Plant list selection changed — load that plant's stored knobs."""
    global _loading
    if _loading:
        return
    _loading = True
    try:
        coll = bpy.data.collections.get(COLLECTION_NAME)
        if coll is not None and 0 <= self.selected_index < len(coll.objects):
            obj = coll.objects[self.selected_index]
            load_knobs_from_obj(obj, self)
            self.knob_day = int(obj.get("ps_day", 60))
    finally:
        _loading = False


class PSWizardKnobs(PropertyGroup):
    """Knob values for the selected plant."""

    selected_index: IntProperty(name="Selected plant", default=-1, update=_on_select)
    dirty: BoolProperty(name="Dirty", default=False)
    wizard_step: IntProperty(name="Wizard step", default=0, min=0, max=7)
    knob_day: IntProperty(name="Age (days)", default=60, min=0, max=3650, update=_knob_update)

    knob_branch_index: FloatProperty(name="Branching index", min=0, max=100, default=30, update=_knob_update)
    knob_branch_dist: FloatProperty(name="Branching distance", min=0, max=10, default=3, update=_knob_update)
    knob_branch_angle: FloatProperty(name="Branch angle", min=0, max=180, default=30, update=_knob_update)
    knob_determinate: FloatProperty(name="Determinate prob.", min=0.0, max=1.0, default=1.0, update=_knob_update)
    knob_symp: FloatProperty(name="Sympodial branching", min=0, max=1, default=0, update=_knob_update)
    knob_secondary: FloatProperty(name="Secondary branching", min=0, max=1, default=0, update=_knob_update)
    knob_internode_len: FloatProperty(name="Internode length", min=0, max=200, default=60, update=_knob_update)
    knob_internode_wid: FloatProperty(name="Internode width", min=0.1, max=20, default=3, update=_knob_update)
    knob_internode_biomass: FloatProperty(name="Internode biomass", min=0.001, max=20, default=4, update=_knob_update)
    knob_curve: FloatProperty(name="Curving index", min=0, max=100, default=30, update=_knob_update)
    knob_first_curve: FloatProperty(name="First internode curve", min=0, max=100, default=10, update=_knob_update)
    knob_internode_days: FloatProperty(name="Internode days", min=1, max=50, default=3, update=_knob_update)
    knob_petiole_len: FloatProperty(name="Petiole length", min=0, max=200, default=30, update=_knob_update)
    knob_petiole_wid: FloatProperty(name="Petiole width", min=0.1, max=20, default=1, update=_knob_update)
    knob_petiole_angle: FloatProperty(name="Petiole angle", min=0, max=180, default=40, update=_knob_update)
    knob_leaf_biomass: FloatProperty(name="Leaf biomass", min=0.001, max=30, default=5, update=_knob_update)
    knob_leaf_scale: FloatProperty(name="Leaf size", min=0.001, max=200, default=20, update=_knob_update)
    knob_leaf_days: FloatProperty(name="Leaf grow days", min=1, max=50, default=10, update=_knob_update)
    knob_leaflets: FloatProperty(name="Leaflets", min=1, max=30, default=1, update=_knob_update)
    knob_pinnate: FloatProperty(name="Pinnate/Palmate", min=0, max=1, default=0, update=_knob_update)
    knob_rachis: FloatProperty(name="Rachis:petiole ratio", min=0, max=100, default=30, update=_knob_update)
    knob_flower_start: FloatProperty(name="Flowering starts", min=0, max=500, default=60, update=_knob_update)
    knob_num_apical: FloatProperty(name="Apical inflorescences", min=0, max=20, default=0, update=_knob_update)
    knob_num_axillary: FloatProperty(name="Axillary inflorescences", min=0, max=50, default=0, update=_knob_update)
    knob_repro_alloc: FloatProperty(name="Repro allocation", min=0.0, max=1.0, default=0.6, update=_knob_update)
    knob_stalk_len: FloatProperty(name="Stalk length", min=0, max=200, default=20, update=_knob_update)
    knob_flr_main: FloatProperty(name="Flowers on main branch", min=1, max=60, default=4, update=_knob_update)
    knob_flr_branch: FloatProperty(name="Flowers per branch", min=0, max=30, default=1, update=_knob_update)
    knob_flr_branches: FloatProperty(name="Secondary branches", min=0, max=10, default=2, update=_knob_update)
    knob_flr_days: FloatProperty(name="Days to all flowers", min=1, max=50, default=10, update=_knob_update)
    knob_petals: FloatProperty(name="Petals per flower", min=1, max=20, default=5, update=_knob_update)
    knob_petal_scale: FloatProperty(name="Petal size", min=1, max=200, default=10, update=_knob_update)
    knob_petal_angle: FloatProperty(name="Petal angle", min=-128, max=128, default=0, update=_knob_update)
    knob_flower_biomass: FloatProperty(name="Flower biomass", min=0.001, max=20, default=1, update=_knob_update)
    knob_fruit_biomass: FloatProperty(name="Fruit threshold", min=0.1, max=1.0, default=0.8, update=_knob_update)
    knob_fruit_days: FloatProperty(name="Days to fruit", min=1, max=500, default=3, update=_knob_update)

    # ── P4: shape pickers (TDO names) + unripe fruit color ──
    knob_bud_shape: EnumProperty(name="Axillary bud shape", items=_tdo_name_items,
                                 default=_tdo_default_index(), update=_knob_update)
    knob_leaf_shape: EnumProperty(name="Leaf shape", items=_tdo_name_items,
                                  default=_tdo_default_index(), update=_knob_update)
    knob_stipule_shape: EnumProperty(name="Stipule shape", items=_tdo_name_items,
                                     default=_tdo_default_index(), update=_knob_update)
    knob_petal_shape: EnumProperty(name="Petal shape", items=_tdo_name_items,
                                   default=_tdo_default_index(), update=_knob_update)
    knob_fruit_shape: EnumProperty(name="Fruit shape", items=_tdo_name_items,
                                   default=_tdo_default_index(), update=_knob_update)
    knob_fruit_unripe_color: FloatVectorProperty(
        name="Unripe fruit color", subtype='COLOR', size=3, min=0.0, max=1.0,
        default=(0.2, 0.6, 0.3), update=_knob_update)


# ── knob <-> params ──

def _is_tdo_container(obj):
    """Duck-type a TDO params container (dict or object with object3D)."""
    if isinstance(obj, dict):
        return "object3D" in obj
    return hasattr(obj, "object3D")


def _set_param_by_path(params, path, value):
    """Set a param via dotted path, incl. pFlower[kGender].tdoParams[kRow]."""
    parts = path.split(".")
    obj = params
    # resolve pFlower[kGenderFemale] / pInflor[kGenderFemale] -> dict
    head = parts[0]
    if head.startswith("pFlower[") or head.startswith("pInflor["):
        gender = head[head.find("[") + 1:head.find("]")]
        if head.startswith("pFlower"):
            obj = params.flowers.setdefault(gender, {})
        else:
            obj = params.inflors.setdefault(gender, {})
        rest = parts[1:]
        # tdoParams[kFirstPetals].scaleAtFullSize
        if rest and rest[0].startswith("tdoParams["):
            row = rest[0][rest[0].find("[") + 1:rest[0].find("]")]
            tdo = obj.setdefault("tdoParams", {}).setdefault(row, {})
            attr = rest[1] if len(rest) > 1 else "object3D"
            _set_tdo_attr(tdo, attr, value)
            return
        if len(rest) == 1:
            obj[rest[0]] = float(value)
        return
    # leafTdoParams.scaleAtFullSize style paths
    section = getattr(params, head, None)
    if section is None:
        raise KeyError(
            f"cannot apply wizard knob: section '{head}' missing from "
            f"plant params (knob path '{path}')")
    for i, part in enumerate(parts[1:]):
        if part in ("leafTdoParams", "stipuleTdoParams", "seedlingTdoParams", "tdoParams"):
            # TDO containers live on the params ROOT, not on the section
            tdo = getattr(params, part, None)
            if tdo is None:
                tdo = getattr(section, part, None)
            if tdo is not None and i + 1 < len(parts) - 1:
                attr = parts[i + 2]
                _set_tdo_attr(tdo, attr, value)
                return
            if tdo is not None:
                _set_tdo_attr(tdo, parts[i + 1], value)
                return
            raise KeyError(
                f"cannot apply wizard knob: '{part}' missing on section "
                f"'{head}' (knob path '{path}')")
        else:
            if i == len(parts) - 2:
                if _is_tdo_container(section):
                    _set_tdo_attr(section, part, value)
                else:
                    setattr(section, part, float(value))
                return
            section = getattr(section, part, None)
            if section is None:
                raise KeyError(
                    f"cannot apply wizard knob: '{part}' missing on section "
                    f"'{head}' (knob path '{path}')")


def _set_tdo_attr(tdo, attr, value):
    """Set an attribute on a tdo params dict or object."""
    if attr in ("FaceColor", "faceColor", "BackfaceColor", "backfaceColor",
                "alternateFaceColor", "alternateBackfaceColor"):
        if isinstance(tdo, dict):
            tdo[attr] = value
        else:
            setattr(tdo, attr, value)
        return
    if attr in ("object3D", "object3d"):
        if isinstance(tdo, dict):
            tdo["object3D"] = value
        else:
            setattr(tdo, "object3D", value)
        return
    if isinstance(tdo, dict):
        tdo[attr] = float(value)
    else:
        setattr(tdo, attr, float(value))


def _color_knob_to_params(color01):
    """Convert a UI color (0-1 floats) to a params color (0-255 tuple)."""
    return tuple(round(float(c) * 255) for c in color01)


def _color_params_to_knob(color255):
    """Convert a params color (0-255 tuple) to a UI color (0-1 floats)."""
    return tuple(float(c) / 255.0 for c in color255)


def apply_knobs_to_params(species, knobs):
    """Return a deep copy of species params with knob values applied."""
    from .core.normalize import normalize_params
    if hasattr(species, "params"):
        params = copy.deepcopy(species.params)
    else:
        params = copy.deepcopy(species)
    normalize_params(params)
    for prop_name, path, _label, _lo, _hi, _default, _step in KNOB_DEFS:
        _set_param_by_path(params, path, getattr(knobs, prop_name))
    for prop_name, path, _label, _step in SHAPE_KNOB_DEFS:
        _set_param_by_path(params, path, str(getattr(knobs, prop_name)))
    for prop_name, path, _label, _step in COLOR_KNOB_DEFS:
        _set_param_by_path(params, path, _color_knob_to_params(getattr(knobs, prop_name)))
    return params


def _tdo_name_of(value, fallback=DEFAULT_TDO_NAME):
    """Return the TDO library name for an object3D value."""
    if value is None:
        return fallback
    if isinstance(value, str):
        return value
    name = getattr(value, "name", None)
    return name if name else fallback


def load_knobs_from_params(species, knobs):
    """Set knob values from a species' params (programmatic — guarded).

    Knobs whose path is missing from the params reset to the wizard default
    so stale values from a previously selected plant never leak into the
    current one (and into saved presets)."""
    global _loading
    _loading = True
    try:
        from .core.normalize import normalize_params
        params = species.params if hasattr(species, "params") else species
        normalize_params(params)
        for prop_name, path, _label, _lo, _hi, _default, _step in KNOB_DEFS:
            val = _get_param_by_path(params, path)
            if val is None:
                val = _default
            try:
                setattr(knobs, prop_name, float(val))
            except (TypeError, ValueError):
                setattr(knobs, prop_name, float(_default))
        for prop_name, path, _label, _step in SHAPE_KNOB_DEFS:
            val = _get_param_by_path(params, path)
            name = _tdo_name_of(val)
            # Species .pla files embed their own TDOs whose names may not be
            # library items (e.g. "Default tdo", "Trial") — assigning such a
            # value to the shape enum raises. Fall back to the library default
            # so loading any species into the wizard never crashes.
            if name not in _tdo_enum_names():
                name = DEFAULT_TDO_NAME
            try:
                setattr(knobs, prop_name, name)
            except (TypeError, ValueError):
                setattr(knobs, prop_name, DEFAULT_TDO_NAME)
        for prop_name, path, _label, _step in COLOR_KNOB_DEFS:
            val = _get_param_by_path(params, path)
            if val is None:
                val = (0, 200, 100)
            try:
                setattr(knobs, prop_name, _color_params_to_knob(val))
            except (TypeError, ValueError):
                setattr(knobs, prop_name, (0.2, 0.8, 0.4))
    finally:
        _loading = False


def _get_param_by_path(params, path):
    parts = path.split(".")
    head = parts[0]
    if head.startswith("pFlower[") or head.startswith("pInflor["):
        gender = head[head.find("[") + 1:head.find("]")]
        if head.startswith("pFlower"):
            obj = params.flowers.get(gender, {})
        else:
            obj = params.inflors.get(gender, {})
        rest = parts[1:]
        if rest and rest[0].startswith("tdoParams["):
            row = rest[0][rest[0].find("[") + 1:rest[0].find("]")]
            tdo = obj.get("tdoParams", {}).get(row, {})
            attr = rest[1] if len(rest) > 1 else "object3D"
            return _get_tdo_attr(tdo, attr)
        if len(rest) == 1:
            return obj.get(rest[0])
        return None
    section = getattr(params, head, None)
    if section is None:
        return None
    for i, part in enumerate(parts[1:]):
        if part in ("leafTdoParams", "stipuleTdoParams", "seedlingTdoParams", "tdoParams"):
            # TDO containers live on the params ROOT, not on the section
            tdo = getattr(params, part, None)
            if tdo is None:
                tdo = getattr(section, part, None)
            if tdo is not None and i + 1 < len(parts) - 1:
                return _get_tdo_attr(tdo, parts[i + 2])
            if tdo is not None:
                return _get_tdo_attr(tdo, parts[i + 1])
            return None
        else:
            if i == len(parts) - 2:
                return getattr(section, part, None)
            section = getattr(section, part, None)
            if section is None:
                return None
    return None


def _get_tdo_attr(tdo, attr):
    if attr in ("FaceColor", "faceColor", "BackfaceColor", "backfaceColor",
                "alternateFaceColor", "alternateBackfaceColor"):
        if isinstance(tdo, dict):
            return tdo.get(attr)
        return getattr(tdo, attr, None)
    if attr in ("object3D", "object3d"):
        if isinstance(tdo, dict):
            return tdo.get("object3D")
        return getattr(tdo, "object3D", None)
    if isinstance(tdo, dict):
        return tdo.get(attr)
    return getattr(tdo, attr, None)


# ── per-plant knob storage ──

def _knobs_to_dict(knobs):
    d = {}
    for pn, *_ in KNOB_DEFS:
        d[pn] = float(getattr(knobs, pn))
    for pn, *_ in SHAPE_KNOB_DEFS:
        d[pn] = str(getattr(knobs, pn))
    for pn, *_ in COLOR_KNOB_DEFS:
        d[pn] = [float(c) for c in getattr(knobs, pn)]
    return d


def _dict_to_knobs(d, knobs):
    for pn, *_ in KNOB_DEFS:
        if pn in d:
            try:
                setattr(knobs, pn, float(d[pn]))
            except (TypeError, ValueError):
                pass
    for pn, *_ in SHAPE_KNOB_DEFS:
        if pn in d:
            try:
                setattr(knobs, pn, str(d[pn]))
            except (TypeError, ValueError):
                pass
    for pn, *_ in COLOR_KNOB_DEFS:
        if pn in d:
            try:
                setattr(knobs, pn, tuple(float(c) for c in d[pn]))
            except (TypeError, ValueError):
                pass


def save_knobs_to_obj(obj, knobs):
    obj["ps_knobs"] = json.dumps(_knobs_to_dict(knobs))


def load_knobs_from_obj(obj, knobs):
    raw = obj.get("ps_knobs")
    if raw:
        try:
            _dict_to_knobs(json.loads(raw), knobs)
        except Exception:
            pass


# ── live rebuild timer ──

def _ensure_timer():
    global _timer_handle
    if _timer_handle is None:
        try:
            _timer_handle = bpy.app.timers.register(_timer_cb)
        except Exception:
            _timer_handle = None


def _cancel_timer():
    global _timer_handle
    if _timer_handle is not None:
        try:
            bpy.app.timers.unregister(_timer_handle)
        except Exception:
            pass
        _timer_handle = None


def _timer_cb():
    global _rebuild_busy
    if _rebuild_busy:
        return 0.1
    scene = bpy.context.scene
    knobs = scene.ps_wizard_knobs
    if knobs.dirty:
        knobs.dirty = False
        _rebuild_busy = True
        try:
            _rebuild_selected(scene)
        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            _rebuild_busy = False
    return 0.1


def _growth_fingerprint(base, knobs, day, seed):
    """Fingerprint of everything that affects simulation (not drawing)."""
    species = getattr(base, "name", "plant")
    return (species, int(day), int(seed)) + tuple(
        round(float(getattr(knobs, pn)), 9) for pn in sorted(GROWTH_KNOBS))


def _attach_params_to_plant(plant, params):
    """Point a PdPlant at a fresh params object (draw-only redraw path)."""
    plant.params = params
    plant.pGeneral = params.pGeneral
    plant.pMeristem = params.pMeristem
    plant.pInternode = params.pInternode
    plant.pLeaf = params.pLeaf
    plant.pSeedlingLeaf = params.pSeedlingLeaf
    plant.pAxillaryBud = params.pAxillaryBud
    plant.pFlower = {
        0: params.flowers.get("kGenderFemale", {}),
        1: params.flowers.get("kGenderMale", {}),
    }
    plant.pInflor = {
        0: params.inflors.get("kGenderFemale", {}),
        1: params.inflors.get("kGenderMale", {}),
    }
    return plant


def _rebuild_selected(scene, fast=False):
    """Rebuild the selected plant's mesh in place using current knobs.

    P2a: when only draw-only knobs changed (same species/seed/day/growth
    knobs), reuse the cached grown plant and only re-draw; a growth-affecting
    change re-simulates from scratch."""
    from .operators import _get_species, get_library
    global _cached_plant, _cached_fingerprint
    knobs = scene.ps_wizard_knobs
    coll = bpy.data.collections.get(COLLECTION_NAME)
    if coll is None or not (0 <= knobs.selected_index < len(coll.objects)):
        return
    obj = coll.objects[knobs.selected_index]
    _, tdo_lib = get_library()
    base = _get_species(obj.get("ps_base_species") or obj.get("ps_species", "plant"))
    params = apply_knobs_to_params(base, knobs)
    day = int(knobs.knob_day)
    seed = int(obj.get("ps_seed", 280))

    from .core.factory import create_plant
    from .scene_bridge import rebuild_plant_mesh
    fingerprint = _growth_fingerprint(base, knobs, day, seed)
    if (_cached_plant is not None and _cached_fingerprint == fingerprint):
        plant = _attach_params_to_plant(_cached_plant, params)
    else:
        plant = create_plant(params, seed=seed, tdo_library=tdo_lib)
        plant.growTo(day)
        _cached_plant = plant
        _cached_fingerprint = fingerprint
    rebuild_plant_mesh(obj, plant, fast=False)
    obj["ps_day"] = day
    save_knobs_to_obj(obj, knobs)
