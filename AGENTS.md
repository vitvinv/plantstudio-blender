# AGENTS.md — Agent Rules

This repository is **public** (or will become public): anything that lands in the
git index lands on GitHub. Local internals (agent memory, agent/IDE workspaces,
secrets) are not needed for the addon to function — keep them on disk only, outside git.

## Never commit

- Agent/IDE workspaces: `.freebuff/`, `.kilo/`, `.claude/`, `.cursor/`, `.hermes/`,
  `.agents/`, `.agentmemory/`, `.graphify/`, `.expanse.json`
- Agent memory and local instructions: `MEMORY.md`, local guidance inside `AGENTS.md`
  (references to `AGENTMEMORY_URL`, ports, machine paths, session/lesson dumps)
- Secrets: `.env`, `.env.*`, keys, tokens, passwords, `local_config.py`
- Build artifacts: `*.zip`, `dist/`, `build/`, `node_modules/`
- Local caches and databases: `__pycache__/`, `.pytest_cache/`, `.hypothesis/`, `*.db`, `*.sqlite`
- Draft plan documents with no references from code (e.g. `LOD_PLAN.md`) — only on explicit request
- `scripts/sync_addon.py` — local maintainer repo-sync tool (gitignored; never commit)

## Commit workflow

1. Before committing, run `git status` — the index should contain only what is intended.
2. Never use a bare `git add .` / `git add -A` — add explicit paths.
3. If `git status` shows anything from the never-commit list, do not add it — extend `.gitignore`.
4. Keep local agent instructions in `~/.agents/` or files named `*.local.md`, both gitignored.
5. Never rewrite history without an explicit request (no force pushes).

## About this project

PlantStudio Blender addon: plant growth simulation (meristem), 63 species,
deterministic seeds, GLB export, animation; works in Blender 4.2 + 5.x.
- Package: `plantstudio_blender/` (pure-Python core + data + Blender UI).
- Tests: `pytest plantstudio_blender/tests`.
- Distribution build: `.vscode/tasks.json` task "Build distribution zip" (the `*.zip` artifact is never committed).
- README.md is the single source of truth for install/usage.
- **Standalone product**: keep code, docs, and UI free of references to other projects
  (e.g. the digital garden). JSON config export targets a user-set directory
  (panel *Config export dir* / `$PLANTSTUDIO_PLANTS_DIR` / `~/.plantstudio/exports`).