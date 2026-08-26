"""Tests for the semantic PlantStudio versus Blender geometry audit."""

import json
from pathlib import Path

from scripts.compare_plant_geometry import (
    AddonMeasurement,
    ObjDocument,
    ObjGroup,
    SourceInfo,
    build_manifest_template,
    compare_occurrence,
    obj_semantics,
    parse_obj,
    run_geometry_audit,
)
from plantstudio_blender.core.plant_library import SpeciesLibrary
from plantstudio_blender.core.tdo_parser import TdoLibrary
from scripts.compare_plant_geometry import _addon_measurement


ROOT = Path(__file__).resolve().parents[2]
ORIGINAL_DIR = ROOT / "examples" / "PlantStudio2"
ADDON_DIR = ROOT / "plantstudio_blender" / "data"
REGISTRY_PATH = ROOT / "plantstudio_blender" / "core" / "param_registry.json"
TDO_PATH = ADDON_DIR / "3D object library.tdo"


def _entry(**overrides):
    entry = {
        "occurrence_id": "Garden flowers.pla#1",
        "source_file": "Garden flowers.pla",
        "occurrence_index": 1,
        "plant_name": "gilia",
        "saved_age": 120,
        "starting_seed": 482,
        "obj_file": "original_obj/gilia.obj",
        "plantstudio_scale_to_meters": 0.001,
        "height_axis": "z",
        "export_grouping": "by_plant_part",
        "leaf_count_quality": "reliable",
    }
    entry.update(overrides)
    return entry


def _obj_with_groups(*groups, height=10.0):
    vertices = []
    obj_groups = []
    for index, name in enumerate(groups):
        base = len(vertices)
        z = height if index else 0.0
        vertices.extend([(0.0, 0.0, z), (1.0, 0.0, z), (0.0, 1.0, z)])
        obj_groups.append(ObjGroup(name=f"Plant:{name}", object_name="Plant",
                                   group_name=name, face_count=1))
    return ObjDocument(vertices, obj_groups, True)


def _base_addon(**overrides):
    values = {
        "model_leaf_count": 2,
        "active_leaf_count": 2,
        "active_ordinary_leaf_count": 1,
        "active_seedling_leaf_count": 1,
        "visible_leaf_count": 2,
        "visible_ordinary_leaf_count": 1,
        "visible_seedling_leaf_count": 1,
        "suppressed_leaf_count": 0,
        "fallen_leaf_count": 0,
        "height_m": 0.01,
        "width_m": 0.001,
        "depth_m": 0.001,
        "internode_count": 2,
        "branch_count": 0,
        "meristem_count": 2,
        "flower_count": 0,
        "fruit_count": 0,
        "bud_count": 0,
        "open_flower_count": 0,
        "unripe_fruit_count": 0,
        "ripe_fruit_count": 0,
        "vertex_count_info": 20,
        "face_count_info": 10,
    }
    values.update(overrides)
    return AddonMeasurement(values, [])


def _compare(addon, obj=None):
    return compare_occurrence(
        _entry(),
        SourceInfo("gilia", 120, 482, 8),
        addon,
        obj or _obj_with_groups("1stLeaf", "Leaf", height=10.0),
        Path("original_obj/gilia.obj"),
        ORIGINAL_DIR,
        True,
        0.005,
        0.05,
    )


def test_obj_parser_and_semantic_groups(tmp_path):
    path = tmp_path / "plant.obj"
    path.write_text(
        "o Plant\n"
        "g Plant_1stLeaf\n"
        "v 0 0 0\n"
        "v 1 0 0\n"
        "v 0 1 0\n"
        "f 1 2 3\n"
        "g Plant_Leaf\n"
        "v 0 0 10\n"
        "v 1 0 10\n"
        "v 0 1 10\n"
        "f 4 5 6\n",
        encoding="latin-1",
    )

    document = parse_obj(path)
    values = obj_semantics(document, _entry())

    assert values["leaf_count"] == 2
    assert values["ordinary_leaf_count"] == 1
    assert values["seedling_leaf_count"] == 1
    assert values["height_m"] == 0.01
    assert values["leaf_count_quality"] == "reliable"


def test_leaf_count_distinguishes_missing_model_leaf():
    _rows, summary = _compare(_base_addon(active_leaf_count=1, visible_leaf_count=1,
                                           model_leaf_count=1))

    assert summary["overall_status"] == "leaf_missing_from_model"
    assert "fewer active leaves" in summary["cause"]


def test_leaf_count_distinguishes_suppressed_draw_leaf():
    rows, summary = _compare(_base_addon(visible_leaf_count=1,
                                         visible_ordinary_leaf_count=0))

    assert summary["overall_status"] == "leaf_suppressed_in_draw"
    visible_row = next(row for row in rows if row["metric"] == "visible_leaf_count")
    assert visible_row["status"] == "leaf_suppressed_in_draw"


def test_height_mismatch_does_not_depend_on_polygon_count():
    rows, summary = _compare(_base_addon(height_m=0.02, vertex_count_info=3,
                                         face_count_info=1))

    assert summary["overall_status"] == "height_mismatch"
    height_row = next(row for row in rows if row["metric"] == "height_m")
    assert height_row["status"] == "height_mismatch"
    assert height_row["difference"] == "0.01"


def test_manifest_template_covers_all_source_occurrences():
    manifest = build_manifest_template(ORIGINAL_DIR, REGISTRY_PATH)

    assert len(manifest["occurrences"]) == 76
    assert manifest["occurrences"][0]["occurrence_id"]
    assert all(entry["saved_age"] is not None for entry in manifest["occurrences"])
    assert all(entry["starting_seed"] is not None for entry in manifest["occurrences"])
    assert len({entry["occurrence_id"] for entry in manifest["occurrences"]}) == 76


def test_addon_measurement_records_model_and_visible_leaves():
    library = SpeciesLibrary(str(ADDON_DIR))
    tdo_library = TdoLibrary.from_file(str(TDO_PATH))
    measurement = _addon_measurement(library.get("gilia"), 120, 482, tdo_library)

    assert not measurement.error
    assert measurement.values["model_leaf_count"] >= measurement.values["active_leaf_count"]
    assert measurement.values["visible_leaf_count"] <= measurement.values["active_leaf_count"]
    assert measurement.values["height_m"] > 0


def test_missing_obj_report_is_explicit(tmp_path):
    manifest = build_manifest_template(ORIGINAL_DIR, REGISTRY_PATH)
    manifest["occurrences"] = [manifest["occurrences"][0]]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    output_dir = tmp_path / "report"

    result = run_geometry_audit(
        ORIGINAL_DIR, ADDON_DIR, REGISTRY_PATH, manifest_path, output_dir
    )

    assert result["summary_rows"][0]["overall_status"] == "missing_original_export"
    assert (output_dir / "plant_geometry_report.html").exists()
    assert (output_dir / "plant_geometry_summary.csv").exists()
