"""Headless checks for the wizard live-rebuild timer registration.

Regression: bpy.app.timers.register() returns None, so storing it as a
handle made the "already running" guard a no-op, and without
persistent=True a file load removed the timer — after that, manual
ps_day/ps_pct slider edits never rebuilt anything for the rest of the
session (frame-change still worked on scrub, so the freeze looked random).
"""

import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class _FakeTimers:
    def __init__(self):
        self.registered = {}

    def register(self, fn, **kwargs):
        if fn in self.registered:
            raise ValueError("already registered")
        self.registered[fn] = types.SimpleNamespace(**kwargs)
        return None

    def unregister(self, fn):
        self.registered.pop(fn, None)

    def is_registered(self, fn):
        return fn in self.registered


@pytest.fixture(scope="module")
def wizard():
    """Import wizard headless if needed, then patch its bpy with a controlled
    fake-timers stub. Earlier test modules may leave their own bpy stub
    cached in sys.modules — never rely on whatever it happens to contain."""
    installed = {}
    if "plantstudio_blender.wizard" not in sys.modules and "bpy" not in sys.modules:
        bpy_mod = types.ModuleType("bpy")
        bpy_types = types.ModuleType("bpy.types")
        bpy_types.PropertyGroup = type("PropertyGroup", (), {})
        bpy_props = types.ModuleType("bpy.props")
        for n in ("FloatProperty", "IntProperty", "BoolProperty",
                  "EnumProperty", "FloatVectorProperty"):
            setattr(bpy_props, n, lambda **kw: None)
        bpy_mod.types = bpy_types
        bpy_mod.props = bpy_props
        bpy_mod.app = types.SimpleNamespace(
            background=False, handlers=types.SimpleNamespace(),
            timers=_FakeTimers())
        installed = {"bpy": bpy_mod, "bpy.types": bpy_types,
                     "bpy.props": bpy_props,
                     "bmesh": types.ModuleType("bmesh"),
                     "mathutils": types.ModuleType("mathutils")}
        for name, mod in installed.items():
            sys.modules[name] = mod
    import plantstudio_blender.wizard as w
    fake_bpy = types.SimpleNamespace(
        app=types.SimpleNamespace(background=False,
                                  handlers=types.SimpleNamespace(),
                                  timers=_FakeTimers()),
        # _timer_cb reads bpy.context.scene.ps_wizard_knobs before rebuilding
        context=types.SimpleNamespace(
            scene=types.SimpleNamespace(ps_wizard_knobs=object())))
    orig_bpy = w.bpy
    w.bpy = fake_bpy
    try:
        yield w
    finally:
        w.bpy = orig_bpy
        for name in installed:
            sys.modules.pop(name, None)


def test_dead_timer_is_restarted(wizard):
    """After a file load the timer is gone; _ensure_timer must restart it."""
    w = wizard
    w._cancel_timer()
    assert not w.bpy.app.timers.is_registered(w._timer_cb)
    w._ensure_timer()
    assert w.bpy.app.timers.is_registered(w._timer_cb)
    w._cancel_timer()
    assert not w.bpy.app.timers.is_registered(w._timer_cb)


def test_ensure_timer_never_duplicates(wizard):
    w = wizard
    w._cancel_timer()
    w._ensure_timer()
    w._ensure_timer()
    w._ensure_timer()
    assert len(w.bpy.app.timers.registered) == 1
    w._cancel_timer()


def test_timer_registered_persistent(wizard):
    """persistent=True keeps the poll alive across file loads."""
    w = wizard
    w._ensure_timer()
    entry = w.bpy.app.timers.registered[w._timer_cb]
    assert entry.persistent is True
    w._cancel_timer()


def test_timer_cb_polls_and_rebuilds(wizard):
    """The callback keeps itself registered (0.1s) and calls refresh."""
    w = wizard
    calls = []

    class _Mod:
        def refresh_stale_plants(self):
            calls.append(1)

    orig = sys.modules.get("plantstudio_blender.animator")
    sys.modules["plantstudio_blender.animator"] = _Mod()
    try:
        w._rebuild_busy = False
        assert w._timer_cb() == 0.1
        assert calls == [1]
        w._rebuild_busy = True
        assert w._timer_cb() == 0.1  # busy: reschedule without rebuilding
        assert calls == [1]
        w._rebuild_busy = False
    finally:
        if orig is not None:
            sys.modules["plantstudio_blender.animator"] = orig
        else:
            sys.modules.pop("plantstudio_blender.animator", None)
