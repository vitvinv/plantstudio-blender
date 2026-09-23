"""Validate TDO references in PlantStudio .pla files."""

import glob
import os

from plantstudio_blender.core.pla_parser import parse_pla_file
from plantstudio_blender.core.tdo_parser import TdoLibrary


def _iter_values(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from _iter_values(child)
    elif isinstance(value, (list, tuple, set)):
        for child in value:
            yield from _iter_values(child)
    else:
        yield value


def _iter_tdo_objects(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _iter_tdo_objects(child, path + (str(key),))
    elif hasattr(value, "__dict__"):
        for key, child in vars(value).items():
            if key == "object3D":
                yield path + (key,), child
            elif not key.startswith("_"):
                yield from _iter_tdo_objects(child, path + (key,))


def iter_tdo_refs(species):
    """Yield ``(species_name, path, reference)`` for named TDO references."""
    params = getattr(species, "params", species)
    species_name = getattr(species, "name", "unknown species")
    for path, ref in _iter_tdo_objects(params):
        if isinstance(ref, str):
            yield species_name, ".".join(path), ref


def validate_dir(data_dir, tdo_library, unresolved, mismatches,
                 allow_mismatch=None):
    """Validate parsed species and append issues to caller-owned lists."""
    allow_mismatch = set(allow_mismatch or ())
    for path in sorted(glob.glob(os.path.join(data_dir, "*.pla"))):
        try:
            species_list = parse_pla_file(path)
        except Exception as exc:
            unresolved.append((os.path.basename(path), "<parse>", str(exc)))
            continue
        for species in species_list:
            for species_name, ref_path, ref in iter_tdo_refs(species):
                if ref in allow_mismatch:
                    mismatches.append((species_name, ref_path, ref))
                    continue
                if tdo_library.get(ref) is None:
                    unresolved.append((species_name, ref_path, ref))


def validate_file(path, tdo_library, unresolved=None, mismatches=None,
                  allow_mismatch=None):
    """Validate one file and return ``(unresolved, mismatches)``."""
    unresolved = [] if unresolved is None else unresolved
    mismatches = [] if mismatches is None else mismatches
    data_dir = os.path.dirname(os.path.abspath(path))
    validate_dir(data_dir, tdo_library, unresolved, mismatches,
                 allow_mismatch=allow_mismatch)
    return unresolved, mismatches
