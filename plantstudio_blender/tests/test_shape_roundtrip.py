"""Regression tests: the wizard shape-knob roundtrip must preserve the
species' own embedded 3D objects.

Species .pla files embed their own copies of 3D objects ('Petal, daylily'
etc.); the parser stores them as Tdo instances on the params. The wizard
stores shape knobs as TDO NAME strings. Applying the knobs used to replace
the embedded Tdo with the library's same-name object — or, for embedded-only
names, with 'Default 3D object' — so dialing the age down and up replaced
flowers with placeholder blobs (or flowers + placeholders).
"""

import copy
import os
import sys
import types
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from plantstudio_blender.core.plant_library import SpeciesLibrary, iter_embedded_tdos
from plantstudio_blender.core.tdo_parser import TdoLibrary, Tdo, apply_object3d_name

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
TDO_PATH = os.path.join(DATA_DIR, "3D object library.tdo")


def tdo_signature(tdo):
    return (tuple(tdo.points), tuple(tdo.triangles))


def merged_library():
    """Library TDOs + species-embedded TDOs (mirrors operators.get_library)."""
    lib = SpeciesLibrary(DATA_DIR)
    tdo_lib = TdoLibrary.from_file(TDO_PATH)
    missing = [t for name, t in lib.embedded_tdos.items()
               if tdo_lib.get(name) is None]
    tdo_lib.merge(missing)
    return lib, tdo_lib


class TestEmbeddedTdoCollection:
    def test_daylily_petal_collected(self):
        species_lib = SpeciesLibrary(DATA_DIR)
        assert "Petal, daylily" in species_lib.embedded_tdos
        daylily = species_lib.get("Daylily")
        row = daylily.params.flowers["kGenderFemale"]["tdoParams"]["kFirstPetals"]
        assert isinstance(row.object3D, Tdo)
        assert row.object3D.name == "Petal, daylily"
        # 'Petal, daylily' is not a library object — embedded only
        base_lib = TdoLibrary.from_file(TDO_PATH)
        assert base_lib.get("Petal, daylily") is None

    def test_iter_embedded_tdos_walks_flower_rows(self):
        species_lib = SpeciesLibrary(DATA_DIR)
        daylily = species_lib.get("Daylily")
        names = {t.name for t in iter_embedded_tdos(daylily.params)}
        assert "Petal, daylily" in names
        assert "Leaf, grassy 2" in names  # leaf TDO

    def test_merge_makes_embedded_names_resolvable(self):
        _, tdo_lib = merged_library()
        assert tdo_lib.get("Petal, daylily") is not None
        # library entries win over same-name embedded objects
        species_lib = SpeciesLibrary(DATA_DIR)
        base_lib = TdoLibrary.from_file(TDO_PATH)
        for name in species_lib.embedded_tdos:
            resolved = tdo_lib.get(name)
            assert resolved is not None
            base = base_lib.get(name)
            if base is not None:
                assert tdo_signature(resolved) == tdo_signature(base)


class TestApplyObject3dName:
    def _row(self):
        species_lib = SpeciesLibrary(DATA_DIR)
        daylily = species_lib.get("Daylily")
        return daylily.params.flowers["kGenderFemale"]["tdoParams"]["kFirstPetals"]

    def test_same_name_keeps_embedded_object(self):
        row = self._row()
        apply_object3d_name(row, "Petal, daylily")
        assert isinstance(row.object3D, Tdo)
        assert row.object3D.name == "Petal, daylily"

    def test_different_name_swaps_to_string(self):
        row = self._row()
        apply_object3d_name(row, "Leaf, broad")
        assert row.object3D == "Leaf, broad"

    def test_unnamed_embedded_kept_for_default_name(self):
        tdo = Tdo("", [(0, 0, 0)], [])
        row = types.SimpleNamespace(object3D=tdo)
        apply_object3d_name(row, "Default 3D object",
                            default_name="Default 3D object")
        assert row.object3D is tdo
        apply_object3d_name(row, "Leaf, broad",
                            default_name="Default 3D object")
        assert row.object3D == "Leaf, broad"

    def test_dict_container_supported(self):
        tdo = Tdo("Petal, daylily", [(0, 0, 0)], [])
        row = {"object3D": tdo}
        apply_object3d_name(row, "Petal, daylily")
        assert row["object3D"] is tdo
        apply_object3d_name(row, "Leaf, broad")
        assert row["object3D"] == "Leaf, broad"


class _BpyStub:
    """Minimal bpy/bmesh/mathutils stub so the wizard's pure knob logic can
    be imported and exercised headless."""

    def __init__(self):
        self.installed = {}

    def install(self):
        prop_names = ("FloatProperty", "IntProperty", "BoolProperty",
                      "EnumProperty", "FloatVectorProperty", "StringProperty",
                      "CollectionProperty", "PointerProperty")

        def _prop(*args, **kwargs):
            return None

        bpy_mod = types.ModuleType("bpy")
        bpy_mod.types = types.SimpleNamespace(
            PropertyGroup=type("PropertyGroup", (object,), {}),
            Operator=type("Operator", (object,), {}),
        )
        bpy_mod.props = types.SimpleNamespace(
            **{name: _prop for name in prop_names})
        bpy_mod.app = types.SimpleNamespace(
            timers=types.SimpleNamespace(register=lambda f: None,
                                         unregister=lambda h: None))
        bpy_mod.data = types.SimpleNamespace()
        bpy_mod.context = types.SimpleNamespace()
        self.installed["bpy"] = bpy_mod
        # 'from bpy.types import X' needs real submodules in sys.modules
        self.installed["bpy.types"] = bpy_mod.types
        self.installed["bpy.props"] = bpy_mod.props
        self.installed["bpy.app"] = bpy_mod.app
        self.installed["bmesh"] = types.ModuleType("bmesh")
        self.installed["mathutils"] = types.ModuleType("mathutils")
        for name, mod in self.installed.items():
            if name not in sys.modules:
                sys.modules[name] = mod

    def remove(self):
        for name in self.installed:
            sys.modules.pop(name, None)


@pytest.fixture(scope="module")
def wizard():
    stub = _BpyStub()
    stub.install()
    try:
        import plantstudio_blender.wizard as wizard_mod
        yield wizard_mod
    finally:
        stub.remove()


class TestWizardShapeKnobRoundtrip:
    """Exercise the real wizard load/apply functions (bpy stubbed)."""

    def test_load_keeps_embedded_petal_name(self, wizard):
        species_lib = SpeciesLibrary(DATA_DIR)
        daylily = species_lib.get("Daylily")
        knobs = types.SimpleNamespace()
        wizard.load_knobs_from_params(daylily, knobs)
        assert knobs.knob_petal_shape == "Petal, daylily"

    def test_apply_roundtrip_preserves_embedded_geometry(self, wizard):
        species_lib = SpeciesLibrary(DATA_DIR)
        daylily = species_lib.get("Daylily")
        knobs = types.SimpleNamespace()
        wizard.load_knobs_from_params(daylily, knobs)
        params2 = wizard.apply_knobs_to_params(daylily, knobs)
        row = params2.flowers["kGenderFemale"]["tdoParams"]["kFirstPetals"]
        assert isinstance(row.object3D, Tdo)
        assert row.object3D.name == "Petal, daylily"
        # same geometry as the species' own embedded petal
        original = daylily.params.flowers["kGenderFemale"]["tdoParams"][
            "kFirstPetals"].object3D
        assert tdo_signature(row.object3D) == tdo_signature(original)

    def test_apply_roundtrip_leaves_untouched_rows_embedded(self, wizard):
        # only kFirstPetals is knobbed; the other flower rows must keep
        # their embedded objects untouched (this is what kept the second
        # petal row real while the first turned into placeholders)
        species_lib = SpeciesLibrary(DATA_DIR)
        daylily = species_lib.get("Daylily")
        knobs = types.SimpleNamespace()
        wizard.load_knobs_from_params(daylily, knobs)
        params2 = wizard.apply_knobs_to_params(daylily, knobs)
        rows = params2.flowers["kGenderFemale"]["tdoParams"]
        assert rows["kSecondPetals"].object3D.name == "Petal, daylily"
        assert rows["kSepals"].object3D.name == "Leaf, broad with point"

    def test_explicit_library_shape_still_applies(self, wizard):
        species_lib = SpeciesLibrary(DATA_DIR)
        daylily = species_lib.get("Daylily")
        knobs = types.SimpleNamespace()
        wizard.load_knobs_from_params(daylily, knobs)
        knobs.knob_petal_shape = "Leaf, broad"
        params2 = wizard.apply_knobs_to_params(daylily, knobs)
        row = params2.flowers["kGenderFemale"]["tdoParams"]["kFirstPetals"]
        assert row.object3D == "Leaf, broad"


def _flowers_with_stages(plant):
    out = []
    stack = [plant.firstPhytomer]
    seen = set()
    while stack:
        part = stack.pop()
        if part is None or id(part) in seen:
            continue
        seen.add(id(part))
        for attr in ("nextPlantPart", "leftBranchPlantPart",
                     "rightBranchPlantPart", "leftLeaf", "rightLeaf"):
            stack.append(getattr(part, attr, None))
        for fl in getattr(part, "flowers", []) or []:
            stage = getattr(fl, "stage", None)
            if stage is None:
                stage = "open" if fl.isOpen and not fl.hasSetFruit else "bud"
            out.append(stage)
    return out


def _drawn(plant):
    from plantstudio_blender.core.draw import draw_plant
    from plantstudio_blender.core.mesh_buffer import MeshBuffer
    from plantstudio_blender.core.turtle import MeshTurtle
    buffer = MeshBuffer()
    turtle = MeshTurtle(buffer)
    turtle.setScale_pixelsPerMm(0.001)
    draw_plant(plant, turtle)
    return buffer.vertices, buffer.faces, buffer.face_colors


class TestFlowersAfterAgeDial:
    """Dialing the age down and up must reproduce the same flowers."""

    def test_setage_down_up_matches_straight_growth(self):
        from plantstudio_blender.core.factory import create_plant
        species_lib, tdo_lib = merged_library()
        daylily = species_lib.get("Daylily")
        straight = create_plant(daylily, seed=280, tdo_library=tdo_lib)
        straight.growTo(100)
        dialed = create_plant(daylily, seed=280, tdo_library=tdo_lib)
        dialed.growTo(30)
        dialed.setAge(100)

        assert len(_flowers_with_stages(straight)) == \
            len(_flowers_with_stages(dialed)) > 0
        assert all(stage == "open" for stage in _flowers_with_stages(dialed))
        assert _drawn(straight) == _drawn(dialed)

    def test_roundtripped_params_grow_identically(self, wizard):
        """Full circle: species -> knobs -> applied params must grow and
        draw exactly like the species' own params (no placeholder swap)."""
        from plantstudio_blender.core.factory import create_plant
        species_lib, tdo_lib = merged_library()
        daylily = species_lib.get("Daylily")
        knobs = types.SimpleNamespace()
        wizard.load_knobs_from_params(daylily, knobs)
        params2 = wizard.apply_knobs_to_params(daylily, knobs)

        def grown(params):
            plant = create_plant(params, seed=280, tdo_library=tdo_lib)
            plant.growTo(100)
            return plant

        straight = grown(daylily.params)
        roundtripped = grown(params2)
        assert _drawn(straight) == _drawn(roundtripped)
        assert _flowers_with_stages(straight) == \
            _flowers_with_stages(roundtripped)
