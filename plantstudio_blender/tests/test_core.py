"""Phase 0 tests: RNG determinism, parsers, species library."""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from plantstudio_blender.core.rng import PdRandom
from plantstudio_blender.core.tdo_parser import parse_tdo_file
from plantstudio_blender.core.pla_parser import parse_pla_file
from plantstudio_blender.core.plant_library import SpeciesLibrary

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
TDO_PATH = os.path.join(DATA_DIR, "3D object library.tdo")


class TestRng:
    def test_same_seed_same_sequence(self):
        r1 = PdRandom()
        r2 = PdRandom()
        r1.setSeed(1234)
        r2.setSeed(1234)
        s1 = [r1.zeroToOne() for _ in range(100)]
        s2 = [r2.zeroToOne() for _ in range(100)]
        assert s1 == s2

    def test_different_seed_different_sequence(self):
        r1 = PdRandom()
        r2 = PdRandom()
        r1.setSeed(1234)
        r2.setSeed(5678)
        s1 = [r1.zeroToOne() for _ in range(20)]
        s2 = [r2.zeroToOne() for _ in range(20)]
        assert s1 != s2

    def test_values_in_range(self):
        r = PdRandom()
        r.setSeed(42)
        for _ in range(500):
            v = r.zeroToOne()
            assert 0.0 <= v <= 1.0
            p = r.randomPercent()
            assert 0 <= p <= 100

    def test_deterministic_across_instances(self):
        """Park-Miller is pure arithmetic — identical across platforms."""
        r = PdRandom()
        r.setSeed(999)
        seq = [r.zeroToOne() for _ in range(10)]
        # known Park-Miller first value for seed 999: 16807*999 mod 2147483647
        assert abs(seq[0] - (16807 * 999 % 2147483647) * 4.656612875e-10) < 1e-9


class TestTdoParser:
    def test_library_count(self):
        tdos = parse_tdo_file(TDO_PATH)
        assert len(tdos) >= 50

    def test_parse_structure(self):
        tdos = parse_tdo_file(TDO_PATH)
        t = tdos[0]
        assert t.name
        assert len(t.points) >= 3
        assert len(t.triangles) >= 1
        for (i, j, k) in t.triangles:
            assert i <= len(t.points)
            assert j <= len(t.points)
            assert k <= len(t.points)

    def test_parse_compact(self):
        from plantstudio_blender.core.tdo_parser import parse_tdo_compact
        t = parse_tdo_compact("N[Default 3D object],P[134 245 150],T[1 2 3]")
        assert t is not None
        assert t.name == "Default 3D object"
        assert t.points == [(134.0, 245.0, 150.0)]
        assert t.triangles == [(1, 2, 3)]
        # plain name strings are not compact TDOs
        assert parse_tdo_compact("Leaf, corn") is None


class TestOriginalDefaults:
    """The Create button must build plants from the original PlantStudio
    default parameter values (umakepm.py / parameters.tab)."""

    def test_defaults_cover_registry(self):
        from plantstudio_blender.core.defaults import DEFAULT_PARAMS
        from plantstudio_blender.core.pla_parser import registry_by_id
        reg = registry_by_id()
        # every default must map onto a registry entry so it can be applied
        assert set(DEFAULT_PARAMS) <= set(reg)
        assert len(DEFAULT_PARAMS) >= 300

    def test_default_params_are_complete(self):
        from plantstudio_blender.core.defaults import make_default_params
        p = make_default_params()
        assert p.leafTdoParams.object3D is not None
        assert p.leafTdoParams.scaleAtFullSize == 30.0
        assert p.pGeneral.ageAtMaturity == 100.0
        assert p.pInternode.lengthAtOptimalFinalBiomassAndExpansion_mm == 60.0
        row = p.flowers["kGenderFemale"]["tdoParams"]["kFirstPetals"]
        assert getattr(row, "scaleAtFullSize", None) == 3.0
        assert getattr(row, "repetitions", None) == 5
        assert p.pFruit.tdoParams.object3D is not None

    def test_defaults_plant_draws(self):
        from plantstudio_blender.core.factory import grow_species
        from plantstudio_blender.core.defaults import make_default_params
        from plantstudio_blender.core.mesh_buffer import MeshBuffer
        from plantstudio_blender.core.turtle import MeshTurtle
        from plantstudio_blender.core.draw import draw_plant
        from plantstudio_blender.core.tdo_parser import TdoLibrary
        plant = grow_species(make_default_params(), 120, seed=280,
                             tdo_library=TdoLibrary.from_file(TDO_PATH))
        buf = MeshBuffer()
        turtle = MeshTurtle(buf)
        turtle.setScale_pixelsPerMm(0.1)
        draw_plant(plant, turtle)
        verts, faces = buf.stats()
        assert verts > 0
        assert faces > 0


class TestPlaParser:
    def test_all_libraries_parse(self):
        total = 0
        for name in os.listdir(DATA_DIR):
            if not name.endswith(".pla"):
                continue
            path = os.path.join(DATA_DIR, name)
            species = parse_pla_file(path)
            total += len(species)
            assert len(species) >= 1, f"{name}: no species"
        assert total >= 60

    def test_general_params_parsed(self):
        path = os.path.join(DATA_DIR, "Garden flowers.pla")
        species = parse_pla_file(path)
        assert len(species) >= 1
        p = species[0].params
        assert p.pGeneral.ageAtMaturity is not None
        assert p.pGeneral.startingSeedForRandomNumberGenerator is not None
        assert p.pGeneral.phyllotacticRotationAngle is not None

    def test_embedded_tdos(self):
        path = os.path.join(DATA_DIR, "Garden flowers.pla")
        species = parse_pla_file(path)
        p = species[0].params
        # leaves have a 3D object
        leaf_tdo = getattr(p, "leafTdoParams", None)
        # axillary bud object
        bud = getattr(p, "pAxillaryBud", None)
        assert (leaf_tdo is not None and leaf_tdo.object3D is not None) or \
               (bud is not None and bud.object3D is not None)


class TestSpeciesLibrary:
    def test_load_all(self):
        lib = SpeciesLibrary(DATA_DIR)
        assert len(lib) >= 60
        names = lib.names()
        # some names legitimately repeat across libraries; library keys by name (first wins)
        assert len(lib._by_name) >= 60

    def test_get_species(self):
        lib = SpeciesLibrary(DATA_DIR)
        s = lib.get(lib.names()[0])
        assert s is not None
        assert s.name
