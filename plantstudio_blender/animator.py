"""PlantStudio-Blender growth animation and mesh refresh.

A plant's age is its own `ps_day` custom property — animate it with
keyframes or drivers, whatever you already use. `ps_pct` (0-100% of the
plant's full-growth day, ps_maturity) mirrors ps_day, so either can be
keyed or driven; see reconcile_growth(). Refresh paths:
- frame_change_post: rebuilds plants whose ps_day/ps_pct moved (scrub/play;
  Blender evaluates keyed/driven properties before this handler runs)
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


def reconcile_growth(obj):
    """Sync the day/pct pair, then rebuild if either moved.

    ps_day (days) and ps_pct (percent of full growth) both describe the
    plant's age; users edit or keyframe/drive either one. The last-built
    state (ps_built_day) is the anchor: whichever property moved away from
    it wins. A ps_pct move recomputes ps_day (so a driver on ps_pct wins
    over ps_day); a ps_day move just re-mirrors ps_pct. Then rebuild the
    mesh when the age changed. Returns the rebuilt object or None.
    """
    from .core.growth import PCT_PROP, pct_for_days, days_for_pct
    day = max(0, int(obj.get("ps_day", 0)))
    seed = int(obj.get("ps_seed", -1))
    maturity = int(obj.get("ps_maturity", 0) or 0)
    if maturity <= 0:  # legacy object: no pct mirror, days-only staleness
        if (int(obj.get("ps_built_day", -2)) != day
                or seed != int(obj.get("ps_built_seed", -2))):
            return rebuild_plant_at_day(obj)
        return None
    built_day = int(obj.get("ps_built_day", -2))
    if built_day < 0:  # knob edit / never built: just rebuild (old behavior)
        return rebuild_plant_at_day(obj)
    pct = float(obj.get(PCT_PROP, pct_for_days(day, maturity)))
    anchor = pct_for_days(built_day, maturity)
    d_pct = abs(pct - anchor)                           # ps_pct moved
    d_day = abs(pct_for_days(day, maturity) - anchor)   # ps_day moved
    if d_pct > 0.05 and d_pct >= d_day:
        # ps_pct moved (driver/keyframe/slider) — it wins over ps_day
        obj["ps_day"] = day = days_for_pct(pct, maturity)
        if day == built_day:
            # slider wiggle inside the built day: same mesh, snap the %
            # back to its canonical value so it can't sit off-mirror
            obj[PCT_PROP] = anchor
            return None
    else:
        # ps_day moved (or nothing moved) — mirror it into ps_pct
        obj[PCT_PROP] = pct_for_days(day, maturity)
    if (int(obj.get("ps_built_day", -2)) != day
            or seed != int(obj.get("ps_built_seed", -2))):
        return rebuild_plant_at_day(obj)
    return None


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
        maturity = int(obj.get("ps_maturity", 0) or 0)
        knobs = SimpleNamespace()
        load_knobs_from_params(base, knobs)   # full wizard defaults
        load_knobs_from_obj(obj, knobs)       # this plant's stored overrides
        params = apply_knobs_to_params(base, knobs)
        plant = create_plant(params, seed=seed, tdo_library=tdo_lib)
        plant.growTo(day)
    except Exception:
        _poison.add(obj.name)
        raise
    from .core.growth import PCT_PROP, pct_for_days
    rebuild_plant_mesh(obj, plant)
    obj["ps_day"] = plant.age
    # maturity from the simulated plant (also upgrades pre-ps_pct objects)
    obj["ps_maturity"] = int(getattr(plant.pGeneral, "ageAtMaturity", 100) or 100)
    obj[PCT_PROP] = pct_for_days(plant.age, obj["ps_maturity"])
    obj["ps_built_day"] = plant.age
    obj["ps_built_seed"] = seed
    _poison.discard(obj.name)
    return obj


def refresh_stale_plants():
    """Rebuild every plant whose age, growth-%, or knobs were edited."""
    for obj in _plants():
        if obj.name in _poison:
            continue
        try:
            reconcile_growth(obj)
        except Exception:
            pass  # already poisoned; frame-change path will retry/report


@_persistent
def _frame_change_rebuild(scene=None, depsgraph=None):
    """Playback/scrub: follow keyed or driver-driven ps_day/ps_pct/ps_seed.

    No fcurve reading: Blender evaluates all animation (5.x slotted actions,
    drivers) into the property BEFORE frame_change_post fires, so comparing
    against what the mesh was built at covers every animation method.
    """
    if bpy.app.background:
        return
    try:
        rendering = bpy.app.is_job_running("RENDER")
    except AttributeError:  # older Blender / bpy-stubbed tests
        rendering = False
    for obj in _plants():
        if obj.name in _poison:
            continue
        if rendering and obj.hide_render:
            continue  # invisible to the render: skip per-frame re-simulation
        try:
            reconcile_growth(obj)
        except Exception:
            pass  # already poisoned; timer/depsgraph paths will report it
