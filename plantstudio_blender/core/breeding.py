"""Plant breeder — port of PdPlant.inherit + PdBreedingStrategy.

Pure Python (no bpy). Breeds an offspring params object from one or two
parent params objects:

- numeric params (float / smallint): blend by the section's parent weight,
  then Gaussian-mutate with stdDev = 0.5 * value * strength% (12-draw
  randomNormalWithStdDev), then clamp to the registry lo/hi bounds.
- non-numeric params (boolean / enum / SCurve float / 3D object / color when
  color blending is off): copied whole from the parent picked by the
  strategy's getNonNumericalParametersFrom rule (6 rules, ubrstrat.pas).
- color params: blend + mutate (stdDev reduced 10x vs other params) when the
  strategy mutates colors, else non-numeric copy.
- longint / header params: skipped (the random seed "shouldn't really be
  bred" — original comment).

The breeding RNG is a separate PdRandom the caller owns, so breeding is
deterministic (same parents + strategy + seed = identical offspring).
"""

import copy
import json
import os

from .normalize import normalize_params, _parse_registry_default
from .pla_parser import registry_by_id, _canonical_tdo_attr
from .rng import PdRandom, _intround

# non-numeric pick rules (ubrstrat.pas.py)
kFromFirstPlant = 0
kFromSecondPlant = 1
kFromProbabilityBasedOnWeightsForSection = 2
kFromPlantWithGreaterWeightForSectionIfEqualFirstPlant = 3
kFromPlantWithGreaterWeightForSectionIfEqualSecondPlant = 4
kFromPlantWithGreaterWeightForSectionIfEqualChooseRandomly = 5

kMaxBreedingSections = 30
kMediumMutation = 60   # udomain.pas.py defaults (low=20, medium=60, high=100)
kLowMutation = 20
COLOR_MASK = 0xFFFFFF  # Delphi TColorRef range

_SECTIONS = None
_BY_ID = None


def load_sections():
    """Ordered breeding sections from the bundled breeding_sections.json."""
    global _SECTIONS, _BY_ID
    if _SECTIONS is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "breeding_sections.json")
        with open(path, encoding="utf-8") as f:
            _SECTIONS = json.load(f)
        assert len(_SECTIONS) <= kMaxBreedingSections
        _BY_ID = registry_by_id()
    return _SECTIONS


class PdBreedingStrategy:
    """Per-section mutation strengths and parent weights (ubrstrat.pas.py)."""

    def __init__(self, medium=True):
        self.mutationStrengths = [0] * kMaxBreedingSections
        self.firstPlantWeights = [50] * kMaxBreedingSections
        self.getNonNumericalParametersFrom = \
            kFromPlantWithGreaterWeightForSectionIfEqualChooseRandomly
        self.mutateAndBlendColorValues = True
        # stored for .strat compatibility; choosing TDOs randomly from the
        # library is deferred (offspring inherit the chosen parent's objects)
        self.chooseTdosRandomlyFromCurrentLibrary = True
        if medium:
            # Breeding Room default: medium variation everywhere (ugener)
            self.mutationStrengths = [kMediumMutation] * kMaxBreedingSections

    def to_dict(self):
        return {
            "mutationStrengths": self.mutationStrengths,
            "firstPlantWeights": self.firstPlantWeights,
            "getNonNumericalParametersFrom": self.getNonNumericalParametersFrom,
            "mutateAndBlendColorValues": self.mutateAndBlendColorValues,
            "chooseTdosRandomlyFromCurrentLibrary":
                self.chooseTdosRandomlyFromCurrentLibrary,
        }

    @classmethod
    def from_dict(cls, data):
        strategy = cls(medium=False)
        if not data:
            return strategy
        for key in ("mutationStrengths", "firstPlantWeights"):
            values = [int(v) for v in (data.get(key) or [])[:kMaxBreedingSections]]
            getattr(strategy, key)[:len(values)] = values
        strategy.getNonNumericalParametersFrom = int(
            data.get("getNonNumericalParametersFrom",
                     strategy.getNonNumericalParametersFrom))
        strategy.mutateAndBlendColorValues = bool(
            data.get("mutateAndBlendColorValues", True))
        strategy.chooseTdosRandomlyFromCurrentLibrary = bool(
            data.get("chooseTdosRandomlyFromCurrentLibrary", True))
        return strategy


def _pick_parent(breeder, strategy, section_index):
    """kFrom* rule -> True for parent A / False for parent B (uplant:1999)."""
    rng = breeder.breeding_rng
    rule = strategy.getNonNumericalParametersFrom
    weights = strategy.firstPlantWeights[section_index]
    if rule == kFromFirstPlant:
        return True
    if rule == kFromSecondPlant:
        return False
    if rule == kFromProbabilityBasedOnWeightsForSection:
        return rng.zeroToOne() < weights / 100.0
    if rule == kFromPlantWithGreaterWeightForSectionIfEqualFirstPlant:
        return weights >= 50
    if rule == kFromPlantWithGreaterWeightForSectionIfEqualSecondPlant:
        return weights > 50
    if rule == kFromPlantWithGreaterWeightForSectionIfEqualChooseRandomly:
        if weights > 50:
            return True
        if weights < 50:
            return False
        return rng.zeroToOne() <= 0.5
    return True


class _Breeder:
    """Carries the shared breeding RNG through one inherit() pass."""

    def __init__(self, strategy, rng):
        self.strategy = strategy
        self.breeding_rng = rng


def _tdo_container(params, access):
    """Params container holding the TDO params named by access (or None)."""
    parts = access.split(".")
    base, first = parts[0], parts[1]
    if base.startswith("pFlower[") or base.startswith("pInflor["):
        gender = base[base.find("[") + 1:base.find("]")]
        d = (params.flowers if base.startswith("pFlower")
             else params.inflors).setdefault(gender, {})
        if first.startswith("tdoParams["):
            row = first[first.find("[") + 1:first.find("]")]
            return d.setdefault("tdoParams", {}).setdefault(row, None) or \
                _new_tdo_row(d, row)
        if first == "bractTdoParams":
            from .pla_parser import TdoParamsCompat
            return d.setdefault("bractTdoParams", TdoParamsCompat())
        return None
    if first in ("tdoParams", "leafTdoParams", "stipuleTdoParams",
                 "seedlingTdoParams"):
        if base == "pAxillaryBud" and first == "tdoParams":
            return params.pAxillaryBud
        if first == "tdoParams":
            obj = getattr(params, base, None)
            if obj is None:
                return None
            if not hasattr(obj, "tdoParams"):
                from .params import TdoParams
                obj.tdoParams = TdoParams()
            return obj.tdoParams
        container = getattr(params, first, None)
        if container is None:
            from .params import TdoParams
            container = TdoParams()
            setattr(params, first, container)
        return container
    return None


def _new_tdo_row(flower_dict, row):
    from .pla_parser import TdoParamsCompat
    row_obj = TdoParamsCompat()
    flower_dict.setdefault("tdoParams", {})[row] = row_obj
    return row_obj


def _plain_container(params, access):
    """(container, attr) for a plain 'pSection.attr' access, or None."""
    parts = access.split(".")
    if len(parts) != 2:
        return None  # plant-level state (age/rotations) — never bred
    section = getattr(params, parts[0], None)
    if section is None:
        return None
    return section, parts[1]


def _read_attr(container, attr, is_dict):
    if is_dict:
        if attr in container:
            return container[attr]
        lower = attr[:1].lower() + attr[1:]
        return container.get(lower)
    if hasattr(container, attr):
        return getattr(container, attr)
    lower = attr[:1].lower() + attr[1:]
    return getattr(container, lower, None)


def _write_attr(container, attr, value, is_dict):
    # the simulation reads snake_case (lowercase-first) aliases which
    # normalize creates next to the registry's mixed-case names; keep any
    # existing alias in sync or the write is silently ignored
    if is_dict:
        container[attr] = value
        alias = attr[:1].lower() + attr[1:]
        if alias != attr and alias in container:
            container[alias] = value
    else:
        setattr(container, attr, value)
        alias = attr[:1].lower() + attr[1:]
        if alias != attr and hasattr(container, alias):
            setattr(container, alias, value)


def get_value(params, entry):
    """Read a registry entry's value from params (None if absent).

    Falls back to the registry default when the parsed attribute was never
    set (normalize filled only the snake_case alias)."""
    access = entry["access"]
    if "[" in access:
        parts = access.split(".")
        base = parts[0]
        gender = base[base.find("[") + 1:base.find("]")]
        d = (params.flowers if base.startswith("pFlower")
             else params.inflors).setdefault(gender, {})
        first = parts[1]
        if first.startswith("tdoParams[") or first == "bractTdoParams":
            container = _tdo_container(params, access)
            if container is None:
                return None if entry["type"] == 5 else _default_for(entry)
            attr = _canonical_tdo_attr(parts[2] if len(parts) > 2 else "object3D")
            return _read_attr(container, attr, isinstance(container, dict))
        return _read_attr(d, first, True)
    if _is_tdo_container_access(access):
        container = _tdo_container(params, access)
        if container is None:
            return None if entry["type"] == 5 else _default_for(entry)
        attr = _canonical_tdo_attr(access.split(".")[-1])
        return _read_attr(container, attr, isinstance(container, dict))
    resolved = _plain_container(params, access)
    if resolved is None:
        return _default_for(entry)
    container, attr = resolved
    value = _read_attr(container, attr, isinstance(container, dict))
    if value is None:
        return _default_for(entry)
    return value


def _is_tdo_container_access(access):
    second = access.split(".")[1] if "." in access else ""
    return second in ("tdoParams", "leafTdoParams", "stipuleTdoParams",
                      "seedlingTdoParams")


def _default_for(entry):
    value = _parse_registry_default(entry["type"], entry.get("default"))
    return None if value is None else value


def set_value(params, entry, value):
    """Write a value into params at the entry's access position."""
    access = entry["access"]
    ftype = entry["type"]
    if ftype == 3 and value is not None:
        value = tuple(value)  # colors are stored as (r, g, b) tuples
    if "[" in access:
        parts = access.split(".")
        base = parts[0]
        gender = base[base.find("[") + 1:base.find("]")]
        d = (params.flowers if base.startswith("pFlower")
             else params.inflors).setdefault(gender, {})
        first = parts[1]
        if first.startswith("tdoParams[") or first == "bractTdoParams":
            container = _tdo_container(params, access)
            attr = _canonical_tdo_attr(parts[2] if len(parts) > 2 else "object3D")
            _write_tdo_value(container, attr, ftype, value)
        else:
            _write_attr(d, first, value, True)
        return
    if _is_tdo_container_access(access):
        container = _tdo_container(params, access)
        attr = _canonical_tdo_attr(access.split(".")[-1])
        _write_tdo_value(container, attr, ftype, value)
        return
    resolved = _plain_container(params, access)
    if resolved is None:
        return
    container, attr = resolved
    _write_attr(container, attr, value, isinstance(container, dict))


def _write_tdo_value(container, attr, ftype, value):
    if container is None:
        return
    if attr == "object3D" and ftype == 5:
        # TDO references are shared, never deep-copied (same as wizard knobs)
        if isinstance(container, dict):
            container["object3D"] = value
        else:
            container.object3D = value
        return
    if ftype == 3:  # color stored as (r, g, b)
        value = tuple(value) if not isinstance(value, tuple) else value
    _write_attr(container, attr, value, isinstance(container, dict))


def _pack_color(color):
    r, g, b = color[:3]
    return float((int(r) & 0xFF) | ((int(g) & 0xFF) << 8) | ((int(b) & 0xFF) << 16))


def _unpack_color(value):
    value = int(round(max(0.0, min(float(COLOR_MASK), value))))
    # ponytail: clamp instead of Delphi DWORD wraparound — a wrap can only
    # come from an extreme mutation draw and would just invert channels
    return (value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF)


def _tdo_name(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return getattr(value, "name", None) or None


def breed(params_a, params_b, strategy, rng):
    """One inherit() pass: returns new params; never mutates the parents."""
    offspring = copy.deepcopy(params_a)
    breeder = _Breeder(strategy, rng)
    for section_index, section in enumerate(load_sections()):
        for field_id in section["fields"]:
            entry = _BY_ID.get(field_id)
            if entry is None:
                continue  # header rows (fieldID 'header') — skipped, same as
                # the original's kFieldHeader check
            _breed_field(breeder, offspring, params_a, params_b, entry,
                         section_index)
    normalize_params(offspring)
    return offspring


def _breed_field(breeder, offspring, params_a, params_b, entry, section_index):
    strategy = breeder.strategy
    rng = breeder.breeding_rng
    ftype = entry["type"]
    if ftype == 8 or ftype == 7:
        return  # longint (seed) and headers are never bred
    a_value = get_value(params_a, entry)

    if ftype == 2 or (ftype == 1 and entry.get("transfer") != 2):
        # numeric blend + mutate (uplant.pas.py smallint / plain float)
        if params_b is None:
            new_value = float(a_value)
        else:
            b_value = float(get_value(params_b, entry))
            if float(a_value) == b_value:
                new_value = float(a_value)
            else:
                weight = strategy.firstPlantWeights[section_index] / 100.0
                new_value = float(a_value) * weight + b_value * (1.0 - weight)
                if ftype == 2:
                    new_value = _intround(new_value)
        strength = strategy.mutationStrengths[section_index]
        std_dev = 0.5 * new_value * strength / 100.0
        new_value = rng.randomNormalWithStdDev(new_value, std_dev)
        new_value = min(entry["hi"], max(entry["lo"], new_value))
        if ftype == 2:
            new_value = _intround(new_value)
        set_value(offspring, entry, new_value)
        return

    if ftype == 3 and strategy.mutateAndBlendColorValues:
        first_color = _pack_color(a_value)
        result = first_color
        if params_b is not None:
            second_color = _pack_color(get_value(params_b, entry))
            weight = strategy.firstPlantWeights[section_index] / 100.0
            result = first_color * weight + second_color * (1.0 - weight)
        strength = strategy.mutationStrengths[section_index]
        mutation = strength if strength > 0 else kLowMutation
        std_frac = mutation / 100.0 * 0.1  # colors mutate at 10% of normal
        result = rng.randomNormalWithStdDev(result, result * std_frac)
        set_value(offspring, entry, _unpack_color(result))
        return

    # non-numeric: boolean / enum / SCurve float / 3D object / unblended color
    if params_b is None:
        return  # offspring is parent A's deepcopy already
    from_first = _pick_parent(breeder, strategy, section_index)
    if from_first:
        return  # keep parent A's value
    b_value = get_value(params_b, entry)
    if b_value is None:
        return
    if ftype == 5:
        b_value = _tdo_name(b_value)
        if b_value is None:
            return
    if ftype == 3:
        b_value = tuple(b_value)
    set_value(offspring, entry, b_value)


# ── custom-params serialization ({access: value} dicts) ──

def _canonical_value(entry, value):
    ftype = entry["type"]
    if value is None:
        return None
    if ftype == 5:
        if isinstance(value, str):
            return value  # library object name (the knob roundtrip format)
        # embedded geometry: serialize it exactly, so a rebuilt plant draws
        # the species' own object even when the library's same-name object
        # differs (the audit-2026-11-01 lesson: 9 embedded names collide)
        from .tdo_parser import Tdo
        if isinstance(value, Tdo):
            return {"tdo_name": value.name or "",
                    "points": [[float(x), float(y), float(z)]
                               for x, y, z in value.points],
                    "triangles": [[int(i), int(j), int(k)]
                                  for i, j, k in value.triangles]}
        return _tdo_name(value)
    if ftype == 3:
        return [int(c) for c in tuple(value)[:3]]
    if ftype == 1 and entry.get("transfer") == 2:  # SCurve instance
        return [float(value.x1), float(value.y1),
                float(value.x2), float(value.y2)]
    if ftype == 4:
        return bool(value)
    if ftype == 6:
        return int(value)
    if isinstance(value, (int, float)):
        return float(value)
    return value


def params_to_dict(params):
    """All registered parameter values as {access: value} (JSON-safe).

    Plant-level state entries (age/rotations/position — accesses without a
    'p' section prefix) are excluded: they are plant state, not breedable
    parameters (the original restores the age after breeding anyway)."""
    result = {}
    for entry in registry_by_id().values():
        if not entry["access"].startswith("p"):
            continue
        value = _canonical_value(entry, get_value(params, entry))
        if value is not None:
            result[entry["access"]] = value
    return result


def params_from_dict(data):
    """Rebuild params from a {access: value} dict (defaults underneath)."""
    from .defaults import make_default_params
    params = make_default_params()
    by_access = {e["access"]: e for e in registry_by_id().values()}
    for access, value in (data or {}).items():
        entry = by_access.get(access)
        if entry is None:
            continue
        if isinstance(value, dict) and "tdo_name" in value:
            # embedded geometry carried exactly (names can contain commas,
            # so the .pla-style compact text format is not usable here)
            from .tdo_parser import Tdo
            value = Tdo(value.get("tdo_name", ""),
                        [tuple(p) for p in value.get("points", [])],
                        [tuple(t) for t in value.get("triangles", [])])
        set_value(params, entry, value)
    normalize_params(params)
    return params
