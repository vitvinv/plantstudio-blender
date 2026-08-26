"""Parse PlantStudio .pla plant species files.

Format:
    [species name] start PlantStudio plant <v2.0>
    ; comment
    Param Name [kFieldID] =value
      start 3D object
      Name=...
      Point=0 0 0
      Triangle=1 2 3
      end 3D object
    [next species] start PlantStudio plant <v2.0>
"""

import os
import json
from .tdo_parser import Tdo

_FIELD_TYPES = {
    1: "float", 2: "smallint", 3: "color", 4: "boolean",
    5: "tdo", 6: "enum", 8: "longint",
}

_registry = None


def load_registry():
    """Load the parameter registry (fieldID -> access string)."""
    global _registry
    if _registry is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "param_registry.json")
        with open(path, encoding="utf-8") as f:
            _registry = json.load(f)
    return _registry


def registry_by_id():
    reg = {}
    for entry in load_registry():
        if entry["id"] != "header":
            reg[entry["id"]] = entry
    return reg


def parse_bool(value):
    return value.strip().lower() in ("true", "yes", "1", "t")


def parse_color(value):
    """Parse a PlantStudio color into (r, g, b) 0-255.

    Two formats appear in .pla files:
      - packed Delphi TColor integer (or numeric string): 0x00BBGGRR
        e.g. 32768 -> (0,128,0)
      - explicit 'r g b' text (e.g. '0 200 200')
    """
    if isinstance(value, str):
        value = value.strip()
    if isinstance(value, (int, float)):
        v = int(value)
        return ((v & 0x0000FF), (v & 0x00FF00) >> 8, (v & 0xFF0000) >> 16)
    if isinstance(value, str) and value and value[0].isdigit() and " " not in value:
        try:
            v = int(float(value))
            return ((v & 0x0000FF), (v & 0x00FF00) >> 8, (v & 0xFF0000) >> 16)
        except ValueError:
            pass
    parts = str(value).split()
    try:
        return (int(float(parts[0])), int(float(parts[1])), int(float(parts[2])))
    except (ValueError, IndexError):
        raise ValueError(
            f"cannot parse color from {value!r}: expected a packed TColor "
            f"integer (0x00BBGGRR) or 'r g b' text")


def set_param(params, access, ftype, value, tdo=None):
    """
    Apply a parsed value to the params object using the access string.
    access like 'pGeneral.LineDivisions', 'pLeaf.leafTdoParams.FaceColor',
    'pFlower[kGenderFemale].tdoParams[kFirstPetals].FaceColor'.
    """
    if not access:
        return
    parts = access.split(".")
    base = parts[0]

    if base.startswith("pFlower") or base.startswith("pInflor"):
        gender_key = base[base.find("[") + 1:base.find("]")]
        # pFlower[kGenderFemale].* and pInflor[kGenderFemale].* are SEPARATE
        # parameter sections in the original (flower vs inflorescence). Keep
        # them in separate dicts so their shared key names (e.g. the flower's
        # OptimalBiomass_pctMPB vs the inflorescence's optimalBiomass_pctMPB)
        # cannot collide.
        if base.startswith("pFlower"):
            obj = params.flowers.setdefault(gender_key, {})
        else:
            obj = params.inflors.setdefault(gender_key, {})
        rest = parts[1:]
        if len(rest) >= 2 and rest[0].startswith("tdoParams"):
            part_key = rest[0][rest[0].find("[") + 1:rest[0].find("]")]
            tdo_obj = obj.setdefault("tdoParams", {}).setdefault(part_key, TdoParamsCompat())
            _set_tdo_attr(tdo_obj, rest[1], ftype, value, tdo)
            return
        if len(rest) >= 2 and rest[0] == "bractTdoParams":
            tdo_obj = obj.setdefault("bractTdoParams", TdoParamsCompat())
            _set_tdo_attr(tdo_obj, rest[1], ftype, value, tdo)
            return
        if len(rest) == 1:
            _set_dict_attr(obj, rest[0], ftype, value)
        return

    # resolve base object
    if base == "pAxillaryBud":
        obj = params.pAxillaryBud
    elif base == "pLeaf":
        obj = params.pLeaf
    elif base == "pSeedlingLeaf":
        obj = params.pSeedlingLeaf
    elif base in ("age", "basePoint_mm", "drawingScale_PixelsPerMm", "hidden",
                  "selectedWhenLastSaved", "xRotation", "yRotation", "zRotation"):
        # plant-level state params from the .pla header — store on pGeneral
        # (not part of the species parameters the simulation uses)
        obj = params.pGeneral
        if len(parts) > 1:
            attr = parts[1]
        else:
            attr = base
        _set_attr(obj, attr, ftype, value)
        return
    else:
        obj = getattr(params, base, None)
        if obj is None:
            raise ValueError(
                f"cannot apply parameter '{access}': unknown section '{base}' "
                f"in the plant params (the .pla references a section that "
                f"does not exist)")

    # walk remaining path; recognize tdo params containers
    rest = parts[1:]
    if len(rest) == 0:
        return
    first = rest[0]

    # tdo params containers are attributes on the PlantParams root
    # (e.g. params.leafTdoParams, params.stipuleTdoParams, params.pAxillaryBud)
    if first in ("tdoParams", "leafTdoParams", "stipuleTdoParams", "seedlingTdoParams"):
        container = None
        if first == "tdoParams":
            # bare tdoParams belongs to the base section itself:
            #   pAxillaryBud.tdoParams.X -> params.pAxillaryBud
            #   pFruit.tdoParams.X       -> params.pFruit.tdoParams
            #   pRoot.tdoParams.X        -> params.pRoot.tdoParams
            if base == "pAxillaryBud":
                container = params.pAxillaryBud
            elif base == "pFruit":
                container = _ensure_tdo_container(params.pFruit)
            elif base == "pRoot":
                container = _ensure_tdo_container(params.pRoot)
            elif base == "pInflorescence":
                container = _ensure_tdo_container(params.pInflorescence)
            else:
                container = getattr(params, "pAxillaryBud", None)
        elif base == "pSeedlingLeaf" and first == "leafTdoParams":
            # pSeedlingLeaf.leafTdoParams.X lives in the root
            # seedlingTdoParams container (the addon's param model puts
            # seedling TDO params at the params root, NOT on pLeaf)
            container = getattr(params, "seedlingTdoParams", None)
            if container is None:
                from .params import TdoParams
                params.seedlingTdoParams = TdoParams()
                container = params.seedlingTdoParams
        elif base == "pLeaf" and first == "stipuleTdoParams":
            container = getattr(params, "stipuleTdoParams", None)
        elif base == "pLeaf" and first == "leafTdoParams":
            container = getattr(params, "leafTdoParams", None)
        else:
            container = getattr(params, first, None)
        if container is None:
            raise ValueError(
                f"cannot apply parameter '{access}': TDO container "
                f"'{first}' not found on section '{base}'")
        _set_tdo_attr(container, rest[1] if len(rest) > 1 else "object3D", ftype, value, tdo)
        return
    if first.startswith("tdoParams[") or first.startswith("leafTdoParams[") \
            or first.startswith("stipuleTdoParams["):
        container_attr = first.split("[")[0]
        key = first[first.find("[") + 1:first.find("]")]
        container = getattr(params, container_attr, None)
        if container is None:
            raise ValueError(
                f"cannot apply parameter '{access}': TDO container "
                f"'{container_attr}' not found")
        tdo_obj = container.setdefault(key, TdoParamsCompat())
        _set_tdo_attr(tdo_obj, rest[1] if len(rest) > 1 else "object3D", ftype, value, tdo)
        return

    # regular attribute path (e.g. pGeneral.ageAtMaturity)
    _set_attr(obj, first, ftype, value)


class TdoParamsCompat:
    """Minimal tdo params container for flower parts."""
    def __init__(self):
        self.object3D = None
        self.scaleAtFullSize = 0.0
        self.xRotationBeforeDraw = 0.0
        self.yRotationBeforeDraw = 0.0
        self.zRotationBeforeDraw = 0.0
        self.faceColor = None
        self.backfaceColor = None
        self.repetitions = 1
        self.radiallyArranged = True
        self.pullBackAngle = 0.0


def _ensure_tdo_container(obj):
    """Attach a TdoParams container to a ParamObject if missing, return it."""
    if not hasattr(obj, "tdoParams"):
        from .params import TdoParams
        obj.tdoParams = TdoParams()
    return obj.tdoParams


_TDO_ATTR_CANONICAL = {
    "object3d": "object3D",
    "facecolor": "faceColor",
    "backfacecolor": "backfaceColor",
    "alternatefacecolor": "alternateFaceColor",
    "alternatebackfacecolor": "alternateBackfaceColor",
    "scaleatfullsize": "scaleAtFullSize",
    "xrotationbeforedraw": "xRotationBeforeDraw",
    "yrotationbeforedraw": "yRotationBeforeDraw",
    "zrotationbeforedraw": "zRotationBeforeDraw",
    "repetitions": "repetitions",
    "radiallyarranged": "radiallyArranged",
    "pullbackangle": "pullBackAngle",
    "pullbackanglerange": "pullBackAngleRange",
}


def _canonical_tdo_attr(attr):
    """Map mixed-case registry attribute names to canonical lowercase names.

    The original parameter registry is inconsistent ('ScaleAtFullSize' for
    flower petals vs 'scaleAtFullSize' everywhere else); the code reads the
    lowercase names, so normalize before storing.
    """
    return _TDO_ATTR_CANONICAL.get(str(attr).lower(), str(attr))


def _set_tdo_attr(tdo_obj, attr, ftype, value, tdo):
    attr = _canonical_tdo_attr(attr)
    if attr == "object3D":
        tdo_obj.object3D = tdo if tdo is not None else value
        return
    if attr == "faceColor":
        tdo_obj.faceColor = parse_color(value) if not isinstance(value, tuple) else value
        return
    if attr == "backfaceColor":
        tdo_obj.backfaceColor = parse_color(value) if not isinstance(value, tuple) else value
        return
    if attr == "alternateFaceColor":
        tdo_obj.alternateFaceColor = parse_color(value) if not isinstance(value, tuple) else value
        return
    if attr == "alternateBackfaceColor":
        tdo_obj.alternateBackfaceColor = parse_color(value) if not isinstance(value, tuple) else value
        return
    if attr == "repetitions":
        try:
            tdo_obj.repetitions = int(float(value))
        except (ValueError, TypeError):
            raise ValueError(
                f"invalid repetitions value {value!r} for tdo param '{attr}'")
        return
    if attr == "radiallyArranged":
        tdo_obj.radiallyArranged = parse_bool(value)
        return
    if attr == "pullBackAngle":
        try:
            tdo_obj.pullBackAngle = float(value)
        except (ValueError, TypeError):
            raise ValueError(
                f"invalid pullBackAngle value {value!r} for tdo param '{attr}'")
        return
    try:
        setattr(tdo_obj, attr, float(value))
    except (ValueError, TypeError):
        # multi-token values (e.g. s-curve '0.05 0.05 0.95 0.95') are
        # legitimately stored raw and parsed later by normalize
        setattr(tdo_obj, attr, value)


def _set_attr(obj, attr, ftype, value):
    if ftype == 4:  # boolean
        setattr(obj, attr, parse_bool(value))
    elif ftype == 3:  # color
        setattr(obj, attr, parse_color(value))
    elif ftype in (1, 2, 8):  # float / smallint / longint
        try:
            setattr(obj, attr, float(value))
        except ValueError:
            # multi-token values (s-curves, TDO refs) stored raw,
            # parsed later by normalize
            setattr(obj, attr, value)
    elif ftype == 6:  # enumerated list (numeric first token)
        try:
            setattr(obj, attr, int(float(value.split()[0])))
        except (ValueError, IndexError):
            setattr(obj, attr, value)
    else:
        setattr(obj, attr, value)


def _set_dict_attr(d, attr, ftype, value):
    """Like _set_attr but for dict-stored flower params."""
    if ftype == 4:
        d[attr] = parse_bool(value)
    elif ftype == 3:
        d[attr] = parse_color(value)
    elif ftype in (1, 2, 8):
        try:
            d[attr] = float(value)
        except ValueError:
            d[attr] = value
    elif ftype == 6:
        try:
            d[attr] = int(float(value.split()[0]))
        except (ValueError, IndexError):
            d[attr] = value
    else:
        d[attr] = value


class PlantSpecies:
    """A parsed plant species: name + params."""

    def __init__(self, name):
        self.name = name
        from .params import PlantParams
        self.params = PlantParams()

    def __repr__(self):
        return f"PlantSpecies({self.name!r})"


def parse_pla_file(path):
    """Parse a .pla file into a list of PlantSpecies."""
    from .params import PlantParams
    registry = registry_by_id()
    species_list = []
    current = None

    with open(path, encoding="latin-1") as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        i += 1
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and "start PlantStudio plant" in line:
            name = line[1:line.find("]")]
            current = PlantSpecies(name)
            species_list.append(current)
            continue
        if current is None:
            continue
        if "=" not in line or "[" not in line:
            continue
        # parameter line: Name [kFieldID] =value
        name_part = line[:line.find("[")]
        field_id = line[line.find("[") + 1:line.find("]")]
        eq = line.find("=")
        value = line[eq + 1:].strip()
        entry = registry.get(field_id)
        if entry is None:
            # unknown key: skip (but still consume embedded tdo block if any)
            if value.startswith("start 3D object"):
                while i < len(lines) and "end 3D object" not in lines[i]:
                    i += 1
                i += 1
            continue
        ftype = entry["type"]
        if ftype == 5:  # tdo — may be a name or an embedded block
            tdo = None
            if value.startswith("start 3D object"):
                # inline style: '=start 3D object' on the same line
                block = []
                while i < len(lines) and "end 3D object" not in lines[i]:
                    block.append(lines[i])
                    i += 1
                i += 1  # consume end 3D object
                tdos = _parse_tdo_block(block)
                tdo = tdos[0] if tdos else None
            elif i < len(lines) and lines[i].strip().startswith("start 3D object"):
                # standard PlantStudio format: '=Name' on the param line,
                # then '  start 3D object' ... '  end 3D object' on the
                # following lines. The embedded block carries the geometry.
                block = []
                while i < len(lines) and "end 3D object" not in lines[i]:
                    block.append(lines[i])
                    i += 1
                i += 1  # consume end 3D object
                tdos = _parse_tdo_block(block)
                tdo = tdos[0] if tdos else None
            set_param(current.params, entry["access"], ftype, value, tdo)
        else:
            set_param(current.params, entry["access"], ftype, value)

    return species_list


def _parse_tdo_block(block_lines):
    from .tdo_parser import parse_tdo_text
    return parse_tdo_text("".join(block_lines))
