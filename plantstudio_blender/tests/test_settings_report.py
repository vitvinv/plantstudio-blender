"""Tests for the PlantStudio settings comparison report."""

import csv
import json
import shutil
from pathlib import Path

from scripts.compare_plant_settings import (
    LONG_COLUMNS,
    SUMMARY_COLUMNS,
    _parse_scalar,
    build_rows,
    compare_values,
    extract_occurrences,
    run_audit,
    run_fixture_audit,
)
from plantstudio_blender.core.tdo_parser import TdoLibrary


ROOT = Path(__file__).resolve().parents[2]
ORIGINAL_DIR = ROOT / "examples" / "PlantStudio2"
ADDON_DIR = ROOT / "plantstudio_blender" / "data"
REGISTRY_PATH = ADDON_DIR.parent / "core" / "param_registry.json"
TDO_PATH = ADDON_DIR / "3D object library.tdo"


def registry():
    entries = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return {entry["id"]: entry for entry in entries if entry.get("id") != "header"}


def test_raw_extraction_preserves_occurrences_lines_and_embedded_geometry():
    occurrences = extract_occurrences(ADDON_DIR / "Garden flowers.pla", registry())

    assert len(occurrences) == 9
    assert occurrences[0].name == "gilia"
    assert occurrences[0].start_line == 8
    assert occurrences[0].end_line > occurrences[0].start_line
    setting = occurrences[0].settings["kFlowerFemaleObject3D"]
    assert setting.line_no == 182
    assert setting.end_line > setting.line_no
    assert setting.embedded_tdo is not None
    assert setting.embedded_tdo.name == "Petal, gilia"
    assert len(setting.embedded_tdo.points) > 3


def test_value_comparison_distinguishes_exact_tolerance_and_mismatch():
    assert compare_values(3, 3, 2) == "match"
    assert compare_values(1.0, 1.0 + 1e-10, 1) == "numeric_tolerance"
    assert compare_values(1.0, 1.1, 1) == "mismatch"
    assert compare_values((10, 20, 30), (10, 20, 30), 3) == "match"
    assert compare_values((10, 20, 30), (10, 20, 31), 3) == "mismatch"


def test_compact_tdo_defaults_are_compared_as_geometry():
    library = TdoLibrary.from_file(str(TDO_PATH))
    entry = registry()["kLeafObject3D"]
    value = _parse_scalar(entry["default"], entry["type"], library)

    assert value.name == "Default 3D object"
    assert value.geometry is not None
    assert len(value.geometry[0]) == 8
    assert len(value.geometry[1]) == 8


def test_audit_covers_all_occurrences_and_registry_fields(tmp_path):
    result = run_audit(ORIGINAL_DIR, ADDON_DIR, REGISTRY_PATH, tmp_path)

    assert result["registry_fields"] == 352
    assert len(result["summary_rows"]) == 76
    assert len(result["occurrence_rows"]) == 76
    assert len(result["canonical_rows"]) == 63
    assert result["long_rows"] == 76 * 352
    assert all(row["overall_status"] == "match" for row in result["summary_rows"])

    with (tmp_path / "plant_settings_long.csv").open(encoding="utf-8", newline="") as handle:
        long_rows = list(csv.DictReader(handle))
    assert long_rows
    assert list(long_rows[0]) == LONG_COLUMNS
    assert all(row["field_id"] for row in long_rows)
    assert all(row["original_line"] or row["original_presence"] == "implicit_default"
               for row in long_rows)

    with (tmp_path / "plant_settings_summary.csv").open(encoding="utf-8", newline="") as handle:
        summary_rows = list(csv.DictReader(handle))
    assert list(summary_rows[0]) == SUMMARY_COLUMNS
    assert {row["source_file"] for row in summary_rows} == {
        path.name for path in ORIGINAL_DIR.glob("*.pla")
    }
    assert (tmp_path / "plant_settings_report.html").read_text(encoding="utf-8").startswith("<!doctype html>")


def test_fixture_audit_writes_one_visible_mismatch(tmp_path):
    output_dir = tmp_path / "fixture-report"

    result = run_fixture_audit(ORIGINAL_DIR, ADDON_DIR, REGISTRY_PATH, output_dir)

    assert result["fixture"] == {
        "source_file": "Garden flowers.pla",
        "field_id": "kGeneralAgeAtMaturity",
        "occurrence_index": "1",
        "original_value": "120",
        "mutated_value": "121",
    }
    mismatches = [
        row for row in result["summary_rows"]
        if row["mismatch_count"] != "0"
    ]
    assert len(mismatches) == 1
    assert mismatches[0]["source_file"] == "Garden flowers.pla"
    assert mismatches[0]["source_occurrence_index"] == "1"
    assert mismatches[0]["overall_status"] == "mismatch"
    assert mismatches[0]["mismatch_count"] == "1"

    age = next(row for row in csv.DictReader(
        (output_dir / "plant_settings_long.csv").open(encoding="utf-8", newline="")
    ) if row["field_id"] == "kGeneralAgeAtMaturity"
        and row["source_occurrence_index"] == "1")
    assert age["original_effective_value"] == "120"
    assert age["addon_parsed_value"] == "121"
    assert age["addon_normalized_value"] == "121"
    assert age["parser_status"] == "mismatch"
    assert age["status"] == "mismatch"

    manifest = json.loads((output_dir / "fixture_manifest.json").read_text(encoding="utf-8"))
    assert manifest["fixture"] == result["fixture"]
    assert (output_dir / "plant_settings_report.html").exists()


def test_audit_exposes_addon_parser_mismatch_and_implicit_default(tmp_path):
    source_dir = tmp_path / "original"
    addon_dir = tmp_path / "addon"
    source_dir.mkdir()
    addon_dir.mkdir()
    source_path = source_dir / "Garden flowers.pla"
    addon_path = addon_dir / "Garden flowers.pla"
    original_text = (ORIGINAL_DIR / source_path.name).read_text(encoding="latin-1")
    source_path.write_text(original_text, encoding="latin-1", newline="\n")

    mutated = original_text.replace(
        "Age at maturity [kGeneralAgeAtMaturity] =120",
        "Age at maturity [kGeneralAgeAtMaturity] =121",
        1,
    )
    mutated = mutated.replace(
        "If pinnate, alternate or opposite [kLeafCompoundPinnateArrangement] =0 Alternate\n",
        "",
        1,
    )
    addon_path.write_text(mutated, encoding="latin-1", newline="\n")
    shutil.copy2(TDO_PATH, addon_dir / TDO_PATH.name)

    library = TdoLibrary.from_file(str(addon_dir / TDO_PATH.name))
    long_rows, summary_rows, _occurrence_rows, _canonical_rows = build_rows(
        source_dir, addon_dir, registry(), library
    )
    age = next(row for row in long_rows
               if row["field_id"] == "kGeneralAgeAtMaturity"
               and row["source_occurrence_index"] == "1")
    defaulted = next(row for row in long_rows
                     if row["field_id"] == "kLeafCompoundPinnateArrangement"
                     and row["source_occurrence_index"] == "1")

    assert age["parser_status"] == "mismatch"
    assert age["normalization_status"] == "match"
    assert age["status"] == "mismatch"
    assert defaulted["original_presence"] == "implicit_default"
    assert defaulted["addon_presence"] == "missing"
    assert defaulted["parser_status"] == "implicit_default"
    assert defaulted["normalization_status"] == "default_injected"
    assert defaulted["status"] == "match"
    assert summary_rows[0]["overall_status"] == "mismatch"
    assert summary_rows[0]["mismatch_count"] == "1"
    assert summary_rows[0]["parser_gap_count"] == "0"
