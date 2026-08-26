#!/usr/bin/env python3
"""Sync the PlantStudio-Blender addon repo with digital-garden.

This script:
1. Pushes the addon repo to GitHub
2. Copies the headless subset (__init__.py, blender_manifest.toml, core/, data/, tests/, tools/)
   into the sibling digital-garden clone
3. Commits and pushes the digital-garden changes

Usage:
    python scripts/sync_addon.py [--dg <path-to-digital-garden>]

The default sibling is ../digital-garden relative to the addon repo root.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Roots: addon repo is the script's parent's parent (two levels up from scripts/)
# digital-garden sibling defaults to ../digital-garden relative to addon repo root
SCRIPT_DIR = Path(__file__).resolve().parent
ADDON_ROOT = SCRIPT_DIR.parent  # plantstudio-blender/
DG_ROOT = ADDON_ROOT.parent.parent / "digital-garden"  # default: sibling


def main():
    parser = argparse.ArgumentParser(description="Sync PlantStudio-Blender addon with digital-garden")
    parser.add_argument("--dg", type=str, default=None,
                        help="Path to digital-garden repo (default: ../digital-garden relative to addon repo)")
    parser.add_argument("--no-push", action="store_true",
                        help="Skip git push steps (dry-run mode)")
    args = parser.parse_args()

    # Resolve digital-garden path
    if args.dg:
        dg_path = Path(args.dg).resolve()
    else:
        # Default: sibling of parent's parent (i.e., ../digital-garden from addon repo root)
        dg_path = Path(ADDON_ROOT).parent.parent / "digital-garden"
        dg_path = dg_path.resolve()

    print(f"Addon repo: {ADDON_ROOT}")
    print(f"Digital-garden: {dg_path}")

    # Step 1: Push the addon repo
    if not args.no_push:
        print("\n--- Step 1: Pushing addon repo ---")
        try:
            result = subprocess.run(
                ["git", "push", "origin", "main"],
                cwd=ADDON_ROOT,
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                print(f"ERROR: git push failed:\n{result.stdout}\n{result.stderr}")
                sys.exit(1)
            print("Addon repo pushed successfully.")
        except subprocess.TimeoutExpired:
            print("ERROR: git push timed out")
            sys.exit(1)
    else:
        print("\n--- Step 1: SKIPPED (--no-push) ---")

    # Step 2: Copy headless subset to digital-garden
    print("\n--- Step 2: Copying headless subset to digital-garden ---")

    # Files/dirs to copy from addon's plantstudio_blender/ to digital-garden's plantstudio_blender/
    headless_items = [
        "plantstudio_blender/__init__.py",
        "plantstudio_blender/blender_manifest.toml",
        "plantstudio_blender/core",
        "plantstudio_blender/data",
        "plantstudio_blender/tests",
        "plantstudio_blender/tools",
    ]

    # Remove any existing plantstudio_blender in digital-garden to ensure clean copy
    dg_plantstudio = dg_path / "plantstudio_blender"
    if dg_plantstudio.exists():
        # Remove only the contents that should be replaced, keeping other files
        for item in dg_plantstudio.iterdir():
            if item.name in [p.split("/")[-1] for p in headless_items] or item.parent.name == "plantstudio_blender":
                if item.is_dir(shutil.__dir__):
                    shutil.rmtree(item)
                else:
                    item.unlink()

    for item_path in headless_items:
        src = ADDON_ROOT / item_path
        dst = dg_plantstudio / item_path
        if src.exists():
            if src.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
                print(f"  Copied directory: {item_path}")
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                print(f"  Copied file: {item_path}")
        else:
            print(f"  WARNING: Source not found: {item_path}")

    # Step 3: Commit and push digital-garden
    if not args.no_push:
        print("\n--- Step 3: Committing and pushing digital-garden ---")
        os.chdir(dg_path)

        # Check if there are changes
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=30,
        )
        if not result.stdout.strip():
            print("  No changes in digital-garden - nothing to commit.")
        else:
            # Add all changed/new files
            subprocess.run(["git", "add", "."], capture_output=True, timeout=30)

            # Commit
            import datetime
            timestamp = datetime.datetime.now().isoformat()
            commit_msg = f"chore(addon): sync headless subset from plantstudio-blender @ {ADDON_ROOT.name}@{subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ADDON_ROOT, capture_output=True, text=True).stdout.strip()}"
            subprocess.run(["git", "commit", "-m", commit_msg], capture_output=True, timeout=30)

            # Push
            result = subprocess.run(
                ["git", "push", "origin", "main"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                print(f"ERROR: git push digital-garden failed:\n{result.stdout}\n{result.stderr}")
                sys.exit(1)
            print("Digital-garden committed and pushed successfully.")
    else:
        print("\n--- Step 3: SKIPPED (--no-push) ---")

    print("\nSync complete!")


if __name__ == "__main__":
    main()