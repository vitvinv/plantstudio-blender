"""PlantStudio-Blender growth animation and mesh refresh.

A plant's age is its own `ps_day` custom property — animate it with
keyframes or drivers, whatever you already use. Refresh paths:
- frame_change_post: rebuilds plants whose ps_day moved (scrub/play; Blender
  evaluates keyed/driven properties before this handler runs)
- depsgraph_update_post -> debounced timer: rebuilds plants whose ps_day
  was edited directly, and the active plant after wizard knob edits
"""

import bpy

from .scene_bridge import is_plant as _is_plant, plants as _plants

try:
    _persistent = bpy.app.handlers.persistent
except AttributeError:
    _persistent = lambda fn: fn  # bpy-stubbed tests import this module headless

# plants whose rebuild raised: skip until their data changes, so one bad
# plant can't retry-crash every frame
_poison = set()


def _active_plant():
    view_layer = bpy.context.view_layer
    obj = view_layer.objects.active if view_layer else None
    return obj if _is_plant(obj) else None


def stale_plants():
    """Plants whose age or seed no longer matches the last built mesh."""
    return [o for o in _plants()
            if o.name not in _poison
            and (int(o.get("ps_day", -1)) != int(o.get("ps_built_day", -2))
                 or int(o.get("ps_seed", -1)) != int(o.get("ps_built_seed", -2)))]


def rebuild_plant_at_day(obj):
    """Rebuild a plant object's mesh in place at its current ps_day.

    Re-simulates from the object's saved wizard knobs (ps_knobs) and seed;
    preserves transform, name and object reference. growTo clamps the day
    at ageAtMaturity (matches the original PlantStudio). Returns the object
    or None when obj is not a rebuildable plant.
    """
    # ponytail: full re-simulation on every refresh (the old draw-only
    # fingerprint cache belonged to the global-slider model); add a cache
    # back if dragging knobs feels slow.
    if not _is_plant(obj):
        return None
    from types import SimpleNamespace
    from .operators import _get_species, get_library
    from .core.factory import create_plant
    from .scene_bridge import rebuild_plant_mesh
    from .wizard import (load_knobs_from_params, load_knobs_from_obj,
                         apply_knobs_to_params)

    try:
        lib, tdo_lib = get_library()
        # ps_species may be a display name (saved presets, Create button) —
        # anything that isn't a library species falls back to default params
        base = _get_species(obj.get("ps_base_species") or obj["ps_species"])
        seed = int(obj["ps_seed"])
        day = max(0, int(obj.get("ps_day", 0)))
        knobs = SimpleNamespace()
        load_knobs_from_params(base, knobs)   # full wizard defaults
        load_knobs_from_obj(obj, knobs)       # this plant's stored overrides
        params = apply_knobs_to_params(base, knobs)
        plant = create_plant(params, seed=seed, tdo_library=tdo_lib)
        plant.growTo(day)
    except Exception:
        _poison.add(obj.name)
        raise
    rebuild_plant_mesh(obj, plant)
    obj["ps_day"] = plant.age
    obj["ps_built_day"] = plant.age
    obj["ps_built_seed"] = seed
    _poison.discard(obj.name)
    return obj


def refresh_stale_plants():
    """Rebuild every plant whose age moved or whose knobs were edited."""
    for obj in stale_plants():
        rebuild_plant_at_day(obj)


@_persistent
def _frame_change_rebuild(scene=None, depsgraph=None):
    """Playback/scrub: follow keyed or driver-driven ps_day/ps_seed values.

    No fcurve reading: Blender evaluates all animation (5.x slotted actions,
    drivers) into the property BEFORE frame_change_post fires, so comparing
    ps_day/ps_seed against what the mesh was built at covers every animation
    method.
    """
    if bpy.app.background:
        return
    for obj in _plants():
        day = int(obj.get("ps_day", 0))
        seed = int(obj.get("ps_seed", 0))
        stale = (day != int(obj.get("ps_built_day", -2))
                 or seed != int(obj.get("ps_built_seed", -2)))
        if stale and obj.name not in _poison:
            try:
                rebuild_plant_at_day(obj)
            except Exception:
                pass  # already poisoned; timer/depsgraph paths will report it
