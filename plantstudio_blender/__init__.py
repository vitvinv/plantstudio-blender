"""PlantStudio Blender extension.

The pure-Python growth core remains importable outside Blender. Blender-only
modules are loaded only while the extension is registered.
"""

import sys


PACKAGE_VERSION = "0.5.0"

bl_info = {
    "name": "PlantStudio-Blender",
    "author": "Kurtz-Fernhout Software (ported)",
    "version": (0, 5, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > PlantStudio-Blender",
    "description": "PlantStudio-Blender plant growth simulator with a live wizard and config export",
    "category": "Add Mesh",
}


def _module_is_ours(value):
    return getattr(value, "__module__", "").startswith(__name__ + ".")


def _unregister_loaded_classes(bpy):
    """Remove classes from any previous PlantStudio module revision."""
    for name in reversed(dir(bpy.types)):
        try:
            cls = getattr(bpy.types, name)
        except (AttributeError, RuntimeError):
            continue
        if not isinstance(cls, type) or not _module_is_ours(cls):
            continue
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass


def _unregister_loaded_handlers(bpy):
    for stack_names in ("depsgraph_update_post", "frame_change_post"):
        stack = getattr(bpy.app.handlers, stack_names, [])
        for handler in list(stack):
            if _module_is_ours(handler):
                try:
                    stack.remove(handler)
                except (ValueError, RuntimeError):
                    pass


def _cancel_loaded_timers():
    module = sys.modules.get(f"{__name__}.wizard")
    cancel = getattr(module, "_cancel_timer", None) if module else None
    if cancel:
        try:
            cancel()
        except Exception:
            pass


def _remove_scene_properties(bpy):
    for name in ("ps_props", "ps_wizard_knobs", "ps_plant_list"):
        try:
            delattr(bpy.types.Scene, name)
        except AttributeError:
            pass


def _purge_submodules():
    prefix = __name__ + "."
    for name in list(sys.modules):
        if name.startswith(prefix):
            del sys.modules[name]


def _clear_runtime_state(bpy):
    _cancel_loaded_timers()
    _unregister_loaded_handlers(bpy)
    _unregister_loaded_classes(bpy)
    _remove_scene_properties(bpy)


def register():
    import bpy

    # Blender can keep an installed package's submodules in sys.modules after
    # an install-over-enabled operation. Clear both RNA classes and Python
    # modules so the current archive cannot inherit an older UI revision.
    _clear_runtime_state(bpy)
    _purge_submodules()

    from .ui_panel import (PSProperties, PS_PT_panel, PS_MT_presets,
                           register_category_menus, _depsgraph_load_active_knobs)
    from .operators import (PS_OT_add_plant, PS_OT_load_preset,
                            PS_OT_save_preset, PS_OT_regrow, PS_OT_step_day,
                            PS_OT_random_seed, PS_OT_export_plant_config)
    from .animator import (_frame_change_rebuild as _ps_frame_change_rebuild)
    from .wizard import PSWizardKnobs

    classes = [
        PSProperties,
        PSWizardKnobs,
        PS_MT_presets,
        PS_PT_panel,
        PS_OT_add_plant,
        PS_OT_load_preset,
        PS_OT_save_preset,
        PS_OT_regrow,
        PS_OT_step_day,
        PS_OT_export_plant_config,
    ]
    for cls in classes:
        bpy.utils.register_class(cls)
    register_category_menus()
    bpy.types.Scene.ps_props = bpy.props.PointerProperty(type=PSProperties)
    bpy.types.Scene.ps_wizard_knobs = bpy.props.PointerProperty(type=PSWizardKnobs)
    if _depsgraph_load_active_knobs not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_depsgraph_load_active_knobs)
    if _ps_frame_change_rebuild not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(_ps_frame_change_rebuild)
    # keeps direct ps_day edits + wizard knob changes rebuilding without any
    # keyframes present; the frame handler alone only fires on scrub/play
    from .wizard import _ensure_timer as _ps_ensure_timer
    _ps_ensure_timer()


def unregister():
    import bpy

    _clear_runtime_state(bpy)
    _purge_submodules()


if __name__ == "__main__":
    register()
