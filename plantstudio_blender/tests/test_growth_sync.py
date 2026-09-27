"""Headless checks for the growth-% mirror (ps_pct <-> ps_day sync)."""

import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from plantstudio_blender.core.growth import (PCT_SCALE, PCT_PROP, pct_for_days,
                                              days_for_pct)


@pytest.fixture(scope="module")
def animator():
    """animator imports bpy (and scene_bridge: bmesh/mathutils) — stub them
    like test_shape_roundtrip does so the pure reconcile logic is testable."""
    if "bpy" in sys.modules:
        import plantstudio_blender.animator as anim
        yield anim
        return
    bpy_mod = types.ModuleType("bpy")
    bpy_mod.app = types.SimpleNamespace(
        background=False,
        handlers=types.SimpleNamespace(),  # no .persistent -> fallback lambda
        timers=types.SimpleNamespace(register=lambda f: None,
                                     unregister=lambda h: None),
    )
    installed = {"bpy": bpy_mod,
                 "bmesh": types.ModuleType("bmesh"),
                 "mathutils": types.ModuleType("mathutils")}
    for name, mod in installed.items():
        sys.modules[name] = mod
    try:
        import plantstudio_blender.animator as anim
        yield anim
    finally:
        for name in installed:
            sys.modules.pop(name, None)


class _Obj:
    """Stand-in for a bpy plant object's ID-property dict."""

    def __init__(self, **props):
        self.props = dict(props)

    def get(self, key, default=None):
        return self.props.get(key, default)

    def __getitem__(self, key):
        return self.props[key]

    def __setitem__(self, key, value):
        self.props[key] = value


def test_pct_round_trip():
    """days -> pct -> days is exact at PCT_SCALE granularity; pct -> pct is
    exact, so mirroring never drifts."""
    for maturity in (1, 60, 100, 120, 500):
        for day in range(0, maturity + 1):
            pct = pct_for_days(day, maturity)
            assert 0.0 <= pct <= 100.0
            assert abs(days_for_pct(pct, maturity) - day) <= 1, \
                (maturity, day, pct, days_for_pct(pct, maturity))
            # converting back is stable: no ping-pong drift between edits
            assert pct_for_days(days_for_pct(pct, maturity), maturity) == pct
            # percent is quantized to whole 1/PCT_SCALE*100 steps
            assert abs(pct * PCT_SCALE / 100.0
                       - round(pct * PCT_SCALE / 100.0)) < 1e-9


def test_pct_edges():
    assert pct_for_days(0, 100) == 0.0
    assert pct_for_days(100, 100) == 100.0
    assert days_for_pct(0.0, 100) == 0
    assert days_for_pct(100.0, 100) == 100
    assert days_for_pct(250.0, 100) == 100   # driver overshoot clamps
    assert pct_for_days(999, 100) == 100.0   # past maturity clamps
    assert pct_for_days(5, 0) == 0.0         # degenerate maturity
    assert days_for_pct(50, 0) == 0


def test_reconcile_pct_moves_days(animator):
    """A driver on ps_pct wins: ps_day is recomputed from the moved pct."""
    calls = []

    def fake_rebuild(obj):
        calls.append(obj)
        return obj

    orig = animator.rebuild_plant_at_day
    animator.rebuild_plant_at_day = fake_rebuild
    try:
        obj = _Obj(ps_day=60, ps_maturity=120, ps_built_day=60,
                   ps_built_seed=5, ps_seed=5)
        obj[PCT_PROP] = 50.0  # matches day 60
        obj[PCT_PROP] = 50.0            # matches day 60
        assert animator.reconcile_growth(obj) is None  # nothing stale
        assert obj["ps_day"] == 60

        obj[PCT_PROP] = 25.0            # driver moved pct -> day 30
        assert animator.reconcile_growth(obj) is obj
        assert obj["ps_day"] == 30
        assert calls == [obj]
    finally:
        animator.rebuild_plant_at_day = orig


def test_reconcile_day_moves_pct_and_clamps(animator):
    """Direct ps_day edit mirrors into pct; day past maturity clamps on
    rebuild and pct follows."""
    def fake_rebuild(obj):
        # mimic rebuild_plant_at_day: growTo clamps to maturity
        obj["ps_day"] = min(obj["ps_day"], obj["ps_maturity"])
        obj["ps_built_day"] = obj["ps_day"]
        obj[PCT_PROP] = pct_for_days(obj["ps_day"], obj["ps_maturity"])
        return obj

    orig = animator.rebuild_plant_at_day
    animator.rebuild_plant_at_day = fake_rebuild
    try:
        obj = _Obj(ps_day=30, ps_maturity=60, ps_built_day=30,
                   ps_built_seed=1, ps_seed=1)
        obj[PCT_PROP] = 50.0
        obj["ps_day"] = 45              # user dials days; pct lags stale
        assert animator.reconcile_growth(obj) is obj
        assert obj["ps_day"] == 45
        # pct is the interval representative of day 45 and maps back to it
        assert obj[PCT_PROP] == pct_for_days(45, 60)
        assert days_for_pct(obj[PCT_PROP], 60) == 45

        obj["ps_day"] = 999             # clamped to maturity on rebuild
        animator.reconcile_growth(obj)
        assert obj["ps_day"] == 60
        assert obj[PCT_PROP] == 100.0
        assert obj["ps_built_day"] == 60
    finally:
        animator.rebuild_plant_at_day = orig


def test_reconcile_legacy_object_keeps_rebuilding(animator):
    """Pre-ps_pct plants still rebuild on stale day/seed (no pct mirror)."""
    seen = []

    def fake_rebuild(obj):
        seen.append(obj)
        return obj

    orig = animator.rebuild_plant_at_day
    animator.rebuild_plant_at_day = fake_rebuild
    try:
        legacy = _Obj(ps_day=60, ps_built_day=30, ps_built_seed=1, ps_seed=1)
        assert animator.reconcile_growth(legacy) is legacy
        assert seen == [legacy]

        fresh = _Obj(ps_day=30, ps_built_day=30, ps_built_seed=1, ps_seed=1)
        assert animator.reconcile_growth(fresh) is None
    finally:
        animator.rebuild_plant_at_day = orig
