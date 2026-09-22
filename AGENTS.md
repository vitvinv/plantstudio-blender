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

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
