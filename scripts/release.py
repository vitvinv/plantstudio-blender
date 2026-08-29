"""Build the PlantStudio-Blender distribution zip and publish it as a GitHub release.

Usage:
    python scripts/release.py            # build zip + create/update GitHub release
    python scripts/release.py --zip-only # only rebuild plantstudio_blender.zip
    python scripts/release.py --dry-run  # print the plan, change nothing

The release version is read from bl_info["version"] in
plantstudio_blender/__init__.py — that is the single source of truth for the
git tag (vX.Y.Z). A missing release is created; an existing one gets the fresh
zip uploaded with --clobber, so re-running the command always updates the
artifact on GitHub.

The README download link points at
    <repo>/releases/latest/download/plantstudio_blender.zip
which GitHub resolves to the newest release's asset automatically, so the
"Click here" link never goes stale after a new release.

Requires: git and the GitHub CLI (gh) on PATH, authenticated.
Stdlib only — no third-party dependencies.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ADDON_DIR = REPO_ROOT / "plantstudio_blender"
INIT_FILE = ADDON_DIR / "__init__.py"
ZIP_PATH = REPO_ROOT / "plantstudio_blender.zip"
REPO = "vitvinv/plantstudio-blender"
RELEASE_URL = (
    f"https://github.com/{REPO}/releases/latest/download/plantstudio_blender.zip"
)

EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".hypothesis", "htmlcov"}
EXCLUDE_NAMES = {".DS_Store", "Thumbs.db"}
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".coverage", ".zip", ".tgz")

VERSION_RE = re.compile(r'"version"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)')
TAG_RE = re.compile(r"v(\d+)\.(\d+)\.(\d+)")


def read_version() -> str:
    text = INIT_FILE.read_text(encoding="utf-8")
    m = VERSION_RE.search(text)
    if not m:
        sys.exit(
            f'ERROR: could not find bl_info "version": (maj, min, pat) in {INIT_FILE}'
        )
    return ".".join(m.groups())


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if check and res.returncode != 0:
        print(res.stdout, end="")
        print(res.stderr, end="")
        sys.exit(f"ERROR: command failed: {' '.join(cmd)}")
    return res


def git_clean() -> bool:
    res = run(["git", "status", "--porcelain"], check=False)
    return res.returncode == 0 and res.stdout.strip() == ""


def build_zip() -> Path:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    files = sorted(
        p
        for p in ADDON_DIR.rglob("*")
        if p.is_file()
        and not any(part in EXCLUDE_DIRS for part in p.relative_to(ADDON_DIR).parts)
        and p.name not in EXCLUDE_NAMES
        and not p.name.endswith(EXCLUDE_SUFFIXES)
    )
    if not files:
        sys.exit(f"ERROR: no files found under {ADDON_DIR}")
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, arcname=f.relative_to(REPO_ROOT).as_posix())
    return ZIP_PATH


def last_tag(version: str) -> str | None:
    """Newest existing vX.Y.Z tag other than the current version, if any."""
    for sort_flag in ("--sort=-version:refname", ""):
        cmd = ["git", "tag"] + ([sort_flag] if sort_flag else [])
        res = run(cmd, check=False)
        if res.returncode != 0:
            continue
        tags = [
            t.strip()
            for t in res.stdout.splitlines()
            if TAG_RE.fullmatch(t.strip()) and t.strip() != f"v{version}"
        ]
        return tags[0] if tags else None
    return None


def release_notes(version: str) -> str:
    prev = last_tag(version)
    if prev:
        log = run(["git", "log", "--oneline", f"{prev}..HEAD"]).stdout.strip()
    else:
        log = run(["git", "log", "--oneline", "-20"]).stdout.strip()
    if not log:
        log = f"Initial release of version {version}."
    return (
        f"## What's New\n\n{log}\n\n"
        "**Install:** Edit → Preferences → Add-ons → Install from Disk → select "
        "`plantstudio_blender.zip`."
    )


def release_exists(version: str) -> bool:
    res = run(["gh", "release", "view", f"v{version}", "--repo", REPO], check=False)
    return res.returncode == 0


def check_readme_link() -> bool:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    return "releases/latest/download/plantstudio_blender.zip" in readme


def publish(version: str, dry_run: bool) -> None:
    if not git_clean():
        sys.exit(
            "ERROR: working tree has uncommitted changes — commit or stash first, "
            "so the release matches pushed code."
        )
    tag = f"v{version}"
    existing = release_exists(version)
    if dry_run:
        print(f"[dry-run] git: clean")
        print(f"[dry-run] release {tag}: "
              + ("exists — zip would be re-uploaded" if existing else "missing — would be created"))
        print(f"[dry-run] asset: plantstudio_blender.zip "
              + (f"({ZIP_PATH.stat().st_size} bytes on disk)" if ZIP_PATH.exists() else "(to be built)"))
        print(f"[dry-run] README download URL: {RELEASE_URL}")
        return
    zip_path = build_zip()
    notes = release_notes(version)
    if existing:
        print(f"Release {tag} exists — uploading fresh zip (--clobber)...")
        run(["gh", "release", "upload", tag, str(zip_path), "--repo", REPO, "--clobber"])
    else:
        print(f"Creating release {tag}...")
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(notes)
            notes_file = f.name
        try:
            run(
                ["gh", "release", "create", tag, str(zip_path), "--repo", REPO,
                 "--title", f"PlantStudio-Blender {version}", "--notes-file", notes_file]
            )
        finally:
            os.unlink(notes_file)
    print(f"OK: {RELEASE_URL} now serves the current {tag} zip.")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--zip-only", action="store_true",
                    help="only rebuild plantstudio_blender.zip, no git/gh interaction")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan without building or publishing anything")
    args = ap.parse_args()

    os.chdir(REPO_ROOT)
    version = read_version()
    print(f"bl_info version: {version}")

    if args.zip_only:
        p = build_zip()
        with zipfile.ZipFile(p) as zf:
            n = len(zf.infolist())
        print(f"Built {p} ({p.stat().st_size} bytes, {n} entries)")
        return

    if not check_readme_link():
        print(f"WARNING: README.md does not contain the latest-download link "
              f"({RELEASE_URL}). Update the Download section before publishing.")

    publish(version, dry_run=args.dry_run)


if __name__ == "__main__":
    main()