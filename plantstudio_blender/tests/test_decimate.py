"""Tests for the headless QEM decimator (core/decimate.py)."""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from plantstudio_blender.core.decimate import simplify_mesh
from plantstudio_blender.core.factory import grow_species
from plantstudio_blender.core.plant_library import SpeciesLibrary
from plantstudio_blender.core.mesh_buffer import MeshBuffer
from plantstudio_blender.core.turtle import MeshTurtle
from plantstudio_blender.core.draw import draw_plant
from plantstudio_blender.core.tdo_parser import TdoLibrary

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
TDO_PATH = os.path.join(DATA_DIR, "3D object library.tdo")


def mesh_for(species_name, day, seed=280):
    lib = SpeciesLibrary(DATA_DIR)
    species = lib.get(species_name)
    tdo_lib = TdoLibrary.from_file(TDO_PATH)
    plant = grow_species(species, day, seed=seed, tdo_library=tdo_lib)
    buffer = MeshBuffer()
    turtle = MeshTurtle(buffer)
    turtle.setScale_pixelsPerMm(0.1)
    draw_plant(plant, turtle)
    return buffer


def grid(rows, cols, color=(10, 200, 30)):
    """rows x cols quad grid split into triangles on the z=0 plane."""
    verts = []
    for r in range(rows + 1):
        for c in range(cols + 1):
            verts.append((float(c), float(r), 0.0))
    faces = []
    colors = []

    def vid(r, c):
        return r * (cols + 1) + c

    for r in range(rows):
        for c in range(cols):
            a = vid(r, c)
            b = vid(r, c + 1)
            cc = vid(r + 1, c)
            d = vid(r + 1, c + 1)
            faces.append([a, b, d])
            faces.append([a, d, cc])
            colors.append(color)
            colors.append(color)
    return verts, faces, colors


def _face_area(verts, face):
    a, b, c = (verts[face[0]], verts[face[1]], verts[face[2]])
    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    w = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    nx = u[1] * w[2] - u[2] * w[1]
    ny = u[2] * w[0] - u[0] * w[2]
    nz = u[0] * w[1] - u[1] * w[0]
    return math.sqrt(nx * nx + ny * ny + nz * nz)


def _assert_valid_mesh(out):
    verts = out["vertices"]
    faces = out["faces"]
    colors = out["face_colors"]
    assert verts and faces
    assert len(faces) == len(colors)
    assert all(len(face) == 3 for face in faces)
    for face in faces:
        i, j, k = face
        assert i != j and j != k and i != k, f"duplicate vertex in {face}"
        assert 0 <= i < len(verts) and 0 <= j < len(verts) and 0 <= k < len(verts)
        assert _face_area(verts, face) > 1e-9


class TestDecimateUnit:
    def test_deterministic(self):
        verts, faces, colors = grid(40, 40)
        out1 = simplify_mesh(verts, faces, colors)
        out2 = simplify_mesh(verts, faces, colors)
        assert out1["vertices"] == out2["vertices"]
        assert out1["faces"] == out2["faces"]
        assert out1["face_colors"] == out2["face_colors"]

    def test_reduces_large_grid_to_ratio(self):
        verts, faces, colors = grid(40, 40)
        n = len(faces)
        out = simplify_mesh(verts, faces, colors, ratio=0.2)
        assert 0.15 * n <= len(out["faces"]) <= 0.25 * n
        assert len(out["faces"]) < n // 2
        _assert_valid_mesh(out)

    def test_output_bounds_stay_within_input(self):
        verts, faces, colors = grid(40, 40)
        out = simplify_mesh(verts, faces, colors, ratio=0.2)
        for axis in range(3):
            in_lo = min(v[axis] for v in verts)
            in_hi = max(v[axis] for v in verts)
            out_lo = min(v[axis] for v in out["vertices"])
            out_hi = max(v[axis] for v in out["vertices"])
            tol = 0.01 * (in_hi - in_lo) + 1e-6
            assert out_lo >= in_lo - tol
            assert out_hi <= in_hi + tol

    def test_colors_preserved_from_input_set(self):
        verts, faces, colors = grid(40, 40, color=(5, 17, 29))
        out = simplify_mesh(verts, faces, colors)
        assert set(out["face_colors"]) <= {(5, 17, 29)}
        assert out["face_colors"]

    def test_color_seam_is_locked(self):
        red, blue = (200, 0, 0), (0, 0, 200)
        verts, faces, colors = grid(16, 32, color=red)
        for r in range(16):
            for c in range(16, 32):
                cell = r * 32 + c
                colors[cell * 2] = blue
                colors[cell * 2 + 1] = blue
        out = simplify_mesh(verts, faces, colors, ratio=0.2)
        present = set(out["face_colors"])
        assert red in present
        assert blue in present

    def test_ratio_one_leaves_unchanged(self):
        verts, faces, colors = grid(20, 20)
        out = simplify_mesh(verts, faces, colors, ratio=1.0)
        assert out["faces"] == faces
        assert out["face_colors"] == colors
        assert out["vertices"] == verts

    def test_small_mesh_unchanged(self):
        verts, faces, colors = grid(2, 2)
        out = simplify_mesh(verts, faces, colors)
        assert out["faces"] == faces
        assert out["face_colors"] == colors

    def test_min_faces_floor(self):
        verts, faces, colors = grid(10, 10)  # 200 faces
        out = simplify_mesh(verts, faces, colors, ratio=0.2, min_faces=180)
        assert 160 <= len(out["faces"]) <= 200
        _assert_valid_mesh(out)

    def test_tiny_mesh_at_floor_is_untouched(self):
        verts, faces, colors = grid(6, 6)  # 72 faces <= default floor 100
        out = simplify_mesh(verts, faces, colors)
        assert out["faces"] == faces


class TestDecimatePlants:
    @pytest.mark.parametrize("name", [
        "phlox", "maiden grass", "sunflower", "Daylily",
    ])
    def test_species_sweep_decimates(self, name):
        buffer = mesh_for(name, 200)
        n = len(buffer.faces)
        assert n > 120
        data = buffer.to_mesh_data()
        out = simplify_mesh(data["vertices"], data["faces"], data["face_colors"])
        assert len(out["faces"]) < n // 2
        _assert_valid_mesh(out)
        out2 = simplify_mesh(data["vertices"], data["faces"], data["face_colors"])
        assert out2["faces"] == out["faces"]

    def test_all_output_colors_come_from_the_plant(self):
        buffer = mesh_for("maiden grass", 200)
        data = buffer.to_mesh_data()
        out = simplify_mesh(data["vertices"], data["faces"], data["face_colors"])
        in_set = set(data["face_colors"])
        assert set(out["face_colors"]) <= in_set
        assert out["face_colors"]