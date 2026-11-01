"""Headless checks for the save_preset and export_plant_config operators.

Regression: PS_OT_save_preset.execute referenced an undefined `knobs` name
(NameError on every save) and had no test coverage — the crash surfaced in a
manual audit. These tests use the same bpy-stub pattern as test_scene_bridge.
"""

import json
import os
import sys
import types
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class _FakePlantObj:
    """Duck-typed plant object: MESH + ps_species + custom-prop mapping."""

    type = "MESH"

    def __init__(self, name, species="plant", seed=280, day=60, knobs=None):
        self.name = name
        self._props = {
            "ps_species": species,
            "ps_seed": seed,
            "ps_day": day,
            "ps_knobs": json.dumps(knobs or {}),
        }

    def __contains__(self, key):
        return key in self._props

    def get(self, key, default=None):
        return self._props.get(key, default)

    def __getitem__(self, key):
        return self._props[key]

    def __setitem__(self, key, value):
        self._props[key] = value


class _ReportingOp:
    """Collects self.report calls so tests can assert on them."""

    def __init__(self):
        self.reports = []

    def report(self, level, message):
        if isinstance(level, (set, frozenset, list, tuple)):
            level = next(iter(level), "")
        self.reports.append((level, message))

    def messages(self, level):
        return [m for lv, m in self.reports if lv == level]


@pytest.fixture(scope="module")
def ops():
    """Import operators headless: stub bpy/bmesh/mathutils unless real bpy
    (or another module's stub) is already present."""
    installed = {}
    if "bpy" not in sys.modules:
        bpy_mod = types.ModuleType("bpy")
        bpy_types = types.ModuleType("bpy.types")
        for n in ("Operator", "Panel", "PropertyGroup", "Menu"):
            setattr(bpy_types, n, type(n, (), {}))
        bpy_props = types.ModuleType("bpy.props")
        for n in ("FloatProperty", "IntProperty", "BoolProperty",
                  "EnumProperty", "FloatVectorProperty", "StringProperty",
                  "PointerProperty"):
            setattr(bpy_props, n, lambda **kw: None)
        bpy_mod.types = bpy_types
        bpy_mod.props = bpy_props
        bpy_mod.app = types.SimpleNamespace(
            background=False,
            handlers=types.SimpleNamespace(persistent=lambda fn: fn),
            timers=types.SimpleNamespace(
                register=lambda *a, **k: None,
                unregister=lambda *a, **k: None,
                is_registered=lambda f: False),
        )
        bpy_mod.utils = types.SimpleNamespace(register_class=lambda cls: None)
        installed = {"bpy": bpy_mod, "bpy.types": bpy_types,
                     "bpy.props": bpy_props,
                     "bmesh": types.ModuleType("bmesh"),
                     "mathutils": types.ModuleType("mathutils")}
        for name, mod in installed.items():
            sys.modules[name] = mod
    import plantstudio_blender.operators as real_ops
    yield real_ops
    if installed:
        for name in installed:
            sys.modules.pop(name, None)


@pytest.fixture
def save_op(ops, monkeypatch, tmp_path):
    """A PS_OT_save_preset wired to a fake plant + tmp presets dir."""
    knobs = {"knob_internode_len": 77.7}
    obj = _FakePlantObj("plant_280", knobs=knobs)

    class _Context:
        active_object = obj

    class _Context:
        active_object = obj

    class _Op(ops.PS_OT_save_preset, _ReportingOp):
        pass

    op = _Op()
    op.preset_name = "My Plant"
    op.category = "Test Cat"
    op.new_category = ""
    monkeypatch.setattr(ops, "USER_PRESETS_DIR", str(tmp_path))
    return op, _Context(), obj


def test_save_preset_writes_round_trippable_json(ops, save_op):
    op, context, _obj = save_op
    assert op.execute(context) == {'FINISHED'}
    path = os.path.join(ops.USER_PRESETS_DIR, "Test Cat", "My Plant.json")
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["name"] == "My Plant"
    assert data["category"] == "Test Cat"
    # full knob set saved (not just overrides) and the override survived
    assert data["knobs"]["knob_internode_len"] == 77.7
    # round-trip: _params_from_user_preset rebuilds params from the json
    params, base_name = ops._params_from_user_preset("Test Cat", "My Plant")
    assert base_name == ""
    assert params.pInternode.lengthAtOptimalFinalBiomassAndExpansion_mm == 77.7


def test_save_preset_sanitizes_names(ops, save_op):
    op, context, _obj = save_op
    op.preset_name = "my/plant: v2?"
    op.category = "NEW"
    op.new_category = "cat/one"
    assert op.execute(context) == {'FINISHED'}
    path = os.path.join(ops.USER_PRESETS_DIR, "catone", "myplant v2.json")
    assert os.path.exists(path)


def test_save_preset_cancels_without_plant(ops, save_op):
    op, context, _obj = save_op

    class _Context:
        active_object = None

    assert op.execute(_Context()) == {'CANCELLED'}


@pytest.fixture
def export_op(ops, monkeypatch, tmp_path):
    """A PS_OT_export_plant_config with plants monkeypatched in."""
    from datetime import date, timedelta
    today = date.today()

    def make(plant_id_name, species, seed, day):
        obj = _FakePlantObj(plant_id_name, species=species, seed=seed, day=day)
        return obj

    p1 = make("daylily_1", "Daylily", 1, 10)
    p2 = make("rose_2", "rose", 2, 20)
    dup = make("daylily_1b", "Daylily", 1, 30)  # same species+seed as p1
    monkeypatch.setattr(ops, "plant_objects", lambda: [p1, p2, dup])
    monkeypatch.setenv("PLANTSTUDIO_PLANTS_DIR", str(tmp_path))

    class _Props:
        export_dir = ""

    class _Scene:
        ps_props = _Props()

    class _Context:
        scene = _Scene()

    class _Op(ops.PS_OT_export_plant_config, _ReportingOp):
        pass

    op = _Op()
    return op, _Context(), tmp_path, today


def test_export_writes_one_config_per_plant(ops, export_op):
    op, context, tmp_path, today = export_op
    assert op.execute(context) == {'FINISHED'}
    files = sorted(os.listdir(str(tmp_path)))
    assert files == ["daylily_1.json", "rose_2.json"]
    with open(os.path.join(str(tmp_path), "daylily_1.json"),
              encoding="utf-8") as f:
        data = json.load(f)
    assert data["plant_id"] == "daylily_1"
    assert data["species"] == "Daylily"
    assert data["seed"] == 1
    assert data["planted_date"] == (today - timedelta(days=10)).isoformat()

def test_export_skips_duplicate_plant_id_with_warning(ops, export_op):
    op, context, tmp_path, _today = export_op
    assert op.execute(context) == {'FINISHED'}
    warnings = op.messages('WARNING')
    assert len(warnings) == 1
    assert "daylily_1" in warnings[0]
    assert "skipped" in warnings[0]
    # the duplicate must not overwrite the first plant's file
    with open(os.path.join(str(tmp_path), "daylily_1.json"),
              encoding="utf-8") as f:
        assert json.load(f)["species"] == "Daylily"
