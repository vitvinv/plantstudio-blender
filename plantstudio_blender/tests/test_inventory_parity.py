"""Regression test for the 3-way inventory parity check.

Verifies that `compare_reference_obj.py --inventory` maps every reference
OBJ plant onto exactly one census species (and vice versa) for the validated
anchor folder. Skipped when the untracked reference assets are absent (a
fresh clone) — the campaign rounds regenerate them via PlantStudio export.
"""

import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

REF_OBJ = os.path.join(ROOT, "data", "reference", "New version 2 plants_age100.obj")
CENSUS = os.path.join(ROOT, "census_new_version_2.json")

pytestmark = pytest.mark.skipif(
    not (os.path.exists(REF_OBJ) and os.path.exists(CENSUS)),
    reason="anchor reference OBJ / census not generated on this machine")


def test_anchor_inventory_parity():
    result = subprocess.run(
        [sys.executable,
         os.path.join(ROOT, "tools", "compare_reference_obj.py"),
         "--inventory", "--census", CENSUS, "--reference", REF_OBJ],
        capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    for name in ("Daylily", "rose", "purplef", "flowert"):
        assert f"OK: '{name}'" in result.stdout
    assert "MISSING" not in result.stdout
