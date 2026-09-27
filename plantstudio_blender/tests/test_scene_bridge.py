"""Headless checks for scene_bridge.plants() collection-tree scanning."""

import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class _Coll:
    """Stand-in for a bpy collection (direct objects + child collections)."""

    def __init__(self, name):
        self.name = name
        self.objects = []
        self.children = []


class _PlantObj:
    """MESH object carrying ps_species like a real plant's custom props."""

    type = "MESH"

    def __init__(self, name):
        self.name = name

    def __contains__(self, key):
        return key == "ps_species"


class _OtherObj:
    type = "MESH"

    def __contains__(self, key):
        return False


@pytest.fixture(scope="module")
def sb():
    """scene_bridge imports bpy/bmesh/mathutils — stub them headless."""
    if "bpy" in sys.modules:
        import plantstudio_blender.scene_bridge as real_sb
        yield real_sb
        return
    installed = {"bpy": types.ModuleType("bpy"),
                 "bmesh": types.ModuleType("bmesh"),
                 "mathutils": types.ModuleType("mathutils")}
    for name, mod in installed.items():
        sys.modules[name] = mod
    try:
        import plantstudio_blender.scene_bridge as real_sb
        yield real_sb
    finally:
        for name in installed:
            sys.modules.pop(name, None)


@pytest.fixture
def fake_bpy(monkeypatch, sb):
    def install(colls):
        data = types.SimpleNamespace(
            collections=types.SimpleNamespace(get=lambda n: colls.get(n)))
        monkeypatch.setattr(sb, "bpy", types.SimpleNamespace(data=data))
    return install


def test_plants_found_in_subcollections(sb, fake_bpy):
    """Plants in sub-collections of 'PlantStudio Plants' are still found.

    Regression: moving plants into per-status sub-collections ("done",
    "to be done") left the direct-objects scan empty, so the frame-change
    rebuild loop saw zero plants and growth stopped following the slider
    and driver-connected plants froze too.
    """
    root = _Coll("PlantStudio Plants")
    done = _Coll("done")
    todo = _Coll("to be done")
    root.children = [done, todo]
    unrelated = _Coll("Other")
    p1, p2 = _PlantObj("plant_529"), _PlantObj("wild_pink_9228")
    done.objects = [p1]
    todo.objects = [p2]
    root.objects = [_OtherObj()]  # non-plant objects are filtered out
    stray = _PlantObj("stray")
    unrelated.objects = [stray]   # outside the tree is not the addon's scope
    fake_bpy({"PlantStudio Plants": root, "done": done,
              "to be done": todo, "Other": unrelated})
    assert sb.plants() == [p1, p2]


def test_plants_direct_members_still_work(sb, fake_bpy):
    root = _Coll("PlantStudio Plants")
    p = _PlantObj("plant_1")
    root.objects = [p]
    fake_bpy({"PlantStudio Plants": root})
    assert sb.plants() == [p]


def test_plants_missing_collection(sb, fake_bpy):
    fake_bpy({})
    assert sb.plants() == []
