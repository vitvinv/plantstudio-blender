"""Headless checks for the breeder operators (PS_OT_breed, bred-preset save,
base resolution) using the bpy-stub pattern."""

import json
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class _FakePlantObj:
    """Duck-typed plant object: MESH + ps_species + custom-prop mapping."""

    type = "MESH"

    def __init__(self, name, species="plant", seed=280, day=60, extra=None):
        self.name = name
        self._props = {
            "ps_species": species,
            "ps_seed": seed,
            "ps_day": day,
            "ps_knobs": json.dumps({}),
        }
        self._props.update(extra or {})
        self.selected = False

    def __contains__(self, key):
        return key in self._props

    def get(self, key, default=None):
        return self._props.get(key, default)

    def __getitem__(self, key):
        return self._props[key]

    def __setitem__(self, key, value):
        self._props[key] = value

    def select_set(self, value):
        self.selected = value


class _ReportingOp:
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


def _custom_params_obj(ops, name, seed=1):
    from plantstudio_blender.core.breeding import params_to_dict
    from plantstudio_blender.core.defaults import make_default_params
    return _FakePlantObj(
        name, extra={
            "ps_custom_params": json.dumps(params_to_dict(make_default_params())),
            "ps_custom_name": name,
        })


class _ViewLayer:
    def __init__(self, active):
        self.objects = types.SimpleNamespace(active=active)


class _Scene:
    def __init__(self, breeder, day):
        self.ps_breeder = breeder

        class _Props:
            pass
        self.ps_props = _Props()
        self.ps_props.day = day


class _Context:
    def __init__(self, active, selected, breeder, day=60):
        self.view_layer = _ViewLayer(active)
        self.selected_objects = selected
        self.scene = _Scene(breeder, day)


def _breeder(mutation_scale=100, seed=280, count=2, strategy_json=""):
    return types.SimpleNamespace(
        offspring_count=count, breeding_seed=seed,
        mutation_scale=mutation_scale, strategy_json=strategy_json)


def test_breed_creates_deterministic_offspring(ops, monkeypatch):
    parent_a = _custom_params_obj(ops, "plant_breed_parentA")
    parent_b = _custom_params_obj(ops, "plant_breed_parentB")
    created = []

    def fake_create(params, base_species, seed, day, context, name=None):
        obj = _FakePlantObj(name or "plant", seed=seed, day=day)
        created.append(obj)
        return obj

    monkeypatch.setattr(ops, "_create_plant_object", fake_create)

    class _Op(ops.PS_OT_breed, _ReportingOp):
        pass

    context = _Context(parent_a, [parent_a, parent_b],
                       _breeder(count=3, seed=280))
    op = _Op()
    assert op.execute(context) == {'FINISHED'}
    assert len(created) == 3
    for i, obj in enumerate(created):
        assert obj.name == f"plant_breed_{i + 1}"
        assert "ps_custom_params" in obj
        assert len(obj["ps_parents"]) == 2
        assert "mutationStrengths" in json.loads(obj["ps_strategy"])
    # determinism: same parents + seed -> byte-identical offspring;
    # a different seed differs
    def run(seed):
        created.clear()
        context = _Context(parent_a, [parent_a, parent_b],
                           _breeder(count=3, seed=seed))
        assert _Op().execute(context) == {'FINISHED'}
        return [o["ps_custom_params"] for o in created]

    first = run(280)
    assert run(280) == first
    assert run(281) != first


def test_breed_mutation_only_without_parent_b(ops, monkeypatch):
    parent_a = _custom_params_obj(ops, "plant_breed_parentA")
    created = []
    monkeypatch.setattr(
        ops, "_create_plant_object",
        lambda *a, **k: created.append(a and _FakePlantObj(k.get("name", "x")))
        or created[-1])
    created.clear()

    class _Op(ops.PS_OT_breed, _ReportingOp):
        pass

    context = _Context(parent_a, [parent_a], _breeder(count=1, seed=7))
    assert _Op().execute(context) == {'FINISHED'}
    assert len(created) == 1
    assert len(created[0]["ps_parents"]) == 1


def test_breed_cancels_without_plant(ops):
    class _Op(ops.PS_OT_breed, _ReportingOp):
        pass

    context = _Context(None, [], _breeder())
    assert _Op().execute(context) == {'CANCELLED'}


def test_bred_plant_saves_and_base_resolution_round_trips(ops, monkeypatch,
                                                          tmp_path):
    monkeypatch.setattr(ops, "BREEDS_DIR", str(tmp_path))
    obj = _custom_params_obj(ops, "rosa_breed_1")
    obj._props["ps_day"] = 75

    class _Op(ops.PS_OT_save_preset, _ReportingOp):
        pass

    op = _Op()
    op.preset_name = "My Breed"
    op.category = "NEW"
    op.new_category = ""
    # category is ignored for bred plants: they save as breed files
    context = types.SimpleNamespace()  # only active_object is consulted first

    class _Ctx:
        active_object = obj

    assert op.execute(_Ctx()) == {'FINISHED'}
    path = os.path.join(str(tmp_path), "My Breed.json")
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["name"] == "My Breed"
    assert data["day"] == 75
    assert "pGeneral.LineDivisions" in data["params"]

    # base resolution: custom-params objects resolve to their own params,
    # never to a species lookup (the audit-2026-11-01 bug class)
    base = ops.base_species_for_object(obj)
    rebuilt = ops.params_for_object(obj)
    from plantstudio_blender.core.breeding import params_to_dict
    assert params_to_dict(rebuilt) == json.loads(obj["ps_custom_params"])
    assert base.name == "rosa_breed_1"
