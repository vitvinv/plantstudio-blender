"""Headless Campanula age round-trip comparison.

The tool renders two deterministic mesh buffers with the same orthographic
camera: a plant generated directly at day 60 and a plant grown to day 80,
rewound to day 40, then grown back to day 60. It writes a side-by-side PPM and
reports whether flower lifecycle and geometry signatures match.
"""

import argparse
import os
import sys
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from plantstudio_blender.core.draw import draw_plant, kExportPartFlower
from plantstudio_blender.core.factory import create_plant, grow_species
from plantstudio_blender.core.mesh_buffer import MeshBuffer
from plantstudio_blender.core.plant_library import SpeciesLibrary
from plantstudio_blender.core.tdo_parser import TdoLibrary
from plantstudio_blender.core.turtle import MeshTurtle

DATA_DIR = os.path.join(ROOT, "plantstudio_blender", "data")
TDO_PATH = os.path.join(DATA_DIR, "3D object library.tdo")


@dataclass(frozen=True)
class OrthographicCamera:
    """A fixed front-facing x/z orthographic camera."""

    width: int = 1000
    height: int = 700
    pixels_per_unit: float = 700.0
    center_x: float = 0.0
    center_z: float = 0.0

    def project(self, point):
        x, _, z = point
        return (
            (x - self.center_x) * self.pixels_per_unit + self.width / 2.0,
            self.height / 2.0 - (z - self.center_z) * self.pixels_per_unit,
        )


def iter_parts(plant):
    if plant.firstPhytomer is None:
        return
    stack = [plant.firstPhytomer]
    seen = set()
    while stack:
        part = stack.pop()
        if part is None or id(part) in seen:
            continue
        seen.add(id(part))
        yield part
        stack.extend([
            getattr(part, "leftBranchPlantPart", None),
            getattr(part, "rightBranchPlantPart", None),
            getattr(part, "nextPlantPart", None),
            getattr(part, "leftLeaf", None),
            getattr(part, "rightLeaf", None),
        ])
        stack.extend(getattr(part, "flowers", []) or [])


def flower_signature(plant, buffer):
    flowers = [part for part in iter_parts(plant)
               if type(part).__name__ == "PdFlowerFruit"]
    flower_records = [record for record in buffer.triangle_set_records
                      if record.get("part_id") == kExportPartFlower]
    return {
        "age": plant.age,
        "stages": [getattr(flower, "stage", "bud") for flower in flowers],
        "biomass": [(
            round(flower.liveBiomass_pctMPB, 9),
            round(flower.deadBiomass_pctMPB, 9),
        ) for flower in flowers],
        "flower_scales": [round(record["scale"], 9)
                          for record in flower_records],
        "flower_triangles": sum(record["triangles"]
                                 for record in flower_records),
    }


def draw_headless(plant):
    buffer = MeshBuffer()
    turtle = MeshTurtle(buffer)
    # Keep units stable and identical for both plants.
    turtle.setScale_pixelsPerMm(0.001)
    draw_plant(plant, turtle)
    return buffer


def _bounds(buffers):
    vertices = [vertex for buffer in buffers for vertex in buffer.vertices]
    if not vertices:
        return 0.0, 0.0, 0.0, 0.0
    xs = [vertex[0] for vertex in vertices]
    zs = [vertex[2] for vertex in vertices]
    return min(xs), max(xs), min(zs), max(zs)


def _translated_buffer(buffer, offset_x):
    """Return mesh vertices translated for side-by-side projection."""
    translated = MeshBuffer()
    translated.vertices = [(x + offset_x, y, z)
                           for x, y, z in buffer.vertices]
    translated.faces = [list(face) for face in buffer.faces]
    translated.face_colors = list(buffer.face_colors)
    return translated


def _triangle_pixels(camera, vertices, face):
    return [camera.project(vertices[index]) for index in face]


def _edge(point_a, point_b, point):
    return ((point[0] - point_a[0]) * (point_b[1] - point_a[1])
            - (point[1] - point_a[1]) * (point_b[0] - point_a[0]))


def _rasterize_triangle(pixels, camera, vertices, face, color):
    points = _triangle_pixels(camera, vertices, face)
    min_x = max(0, int(min(point[0] for point in points)))
    max_x = min(camera.width - 1, int(max(point[0] for point in points)))
    min_y = max(0, int(min(point[1] for point in points)))
    max_y = min(camera.height - 1, int(max(point[1] for point in points)))
    if min_x > max_x or min_y > max_y:
        return
    area = _edge(points[0], points[1], points[2])
    if abs(area) < 1e-9:
        return
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            sample = (x + 0.5, y + 0.5)
            weights = (
                _edge(points[1], points[2], sample),
                _edge(points[2], points[0], sample),
                _edge(points[0], points[1], sample),
            )
            if all(weight >= 0 for weight in weights) or all(weight <= 0 for weight in weights):
                pixels[y * camera.width + x] = tuple(color)


def rasterize_side_by_side(left, right, gap=0.12, width=1000, height=700):
    """Rasterize two buffers with one orthographic camera into RGB pixels."""
    left_min, left_max, min_z, max_z = _bounds([left, right])
    right_min, right_max, _, _ = _bounds([right])
    left_width = left_max - left_min
    right_width = right_max - right_min
    span = left_width + gap + right_width
    # Meshes are translated into a new side-by-side coordinate frame below.
    center_x = span / 2.0
    center_z = (min_z + max_z) / 2.0
    scale = min((width - 20) / max(span, 1e-9),
                (height - 20) / max(max_z - min_z, 1e-9))
    camera = OrthographicCamera(width, height, scale, center_x, center_z)
    left_mesh = _translated_buffer(left, -left_min)
    right_mesh = _translated_buffer(right, -right_min + left_width + gap)
    pixels = [(248, 247, 242)] * (width * height)
    for buffer in (left_mesh, right_mesh):
        for face, color in zip(buffer.faces, buffer.face_colors):
            _rasterize_triangle(pixels, camera, buffer.vertices, face, color)
    return camera, pixels


def write_ppm(path, width, height, pixels):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="ascii", newline="\n") as output:
        output.write(f"P3\n{width} {height}\n255\n")
        for row in range(height):
            output.write(" ".join(
                f"{red} {green} {blue}"
                for red, green, blue in pixels[row * width:(row + 1) * width]
            ))
            output.write("\n")


def compare_campanula(day=60, rewind_day=40, intermediate_day=80, seed=280,
                      output_path=None):
    library = SpeciesLibrary(DATA_DIR)
    species = library.get("campanula")
    if species is None:
        raise LookupError("campanula is not present in the bundled species data")
    tdo_library = TdoLibrary.from_file(TDO_PATH)

    direct = grow_species(species, day, seed=seed, tdo_library=tdo_library)
    round_trip = create_plant(species, seed=seed, tdo_library=tdo_library)
    round_trip.growTo(intermediate_day)
    round_trip.setAge(rewind_day)
    round_trip.growTo(day)
    direct_buffer = draw_headless(direct)
    round_trip_buffer = draw_headless(round_trip)
    direct_signature = flower_signature(direct, direct_buffer)
    round_trip_signature = flower_signature(round_trip, round_trip_buffer)
    mesh_equal = (
        direct_buffer.vertices == round_trip_buffer.vertices
        and direct_buffer.faces == round_trip_buffer.faces
        and direct_buffer.face_colors == round_trip_buffer.face_colors
    )
    if output_path:
        _, pixels = rasterize_side_by_side(direct_buffer, round_trip_buffer)
        write_ppm(output_path, 1000, 700, pixels)
    return {
        "direct": direct_signature,
        "round_trip": round_trip_signature,
        "mesh_equal": mesh_equal,
        "image": output_path,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=None,
                        help="optional side-by-side orthographic PPM path")
    parser.add_argument("--day", type=int, default=60)
    parser.add_argument("--rewind-day", type=int, default=40)
    parser.add_argument("--intermediate-day", type=int, default=80)
    parser.add_argument("--seed", type=int, default=280)
    args = parser.parse_args()
    result = compare_campanula(
        day=args.day,
        rewind_day=args.rewind_day,
        intermediate_day=args.intermediate_day,
        seed=args.seed,
        output_path=args.output,
    )
    print(f"mesh_equal={result['mesh_equal']}")
    print(f"direct={result['direct']}")
    print(f"round_trip={result['round_trip']}")
    if args.output:
        print(f"image={args.output}")
    if not result["mesh_equal"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
