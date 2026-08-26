# PlantStudio-Blender Addon

The PlantStudio-Blender addon is a Blender addon for plant growth simulation based on the original PlantStudio software.

## Structure

- `plantstudio_blender/` - Full addon source including Blender GUI bridge (`animator.py`, `operators.py`, `scene_bridge.py`, `ui_panel.py`, `wizard.py`)
- `scripts/sync_addon.py` - Sync script to push headless subset to digital-garden
- `.vscode/tasks.json` - VS Code tasks for one-button sync

## Development

See the [Plan](plan.md) for details on the split between the full addon repo and the headless digital-garden subset.

## License

GPL-3.0 (see LICENSE)