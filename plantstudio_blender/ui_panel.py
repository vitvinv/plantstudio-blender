"""N-panel UI for the PlantStudio-Blender addon.

Layout:
  - New Plant box: preset Load menu + Create button + seed
  - Selected Plant box: per-plant age (keyable) + wizard knobs
  - Export box: config export dir + export button

Plants are picked in the viewport or Outliner (active object) — no separate
plant list. Per-plant knobs and age live on each object (ps_knobs / ps_day);
a depsgraph handler loads the active plant's knobs into the wizard.
"""

import os
import re
import bpy
from bpy.types import Panel, PropertyGroup
from bpy.props import StringProperty, IntProperty, PointerProperty

from .operators import get_library, USER_PRESETS_DIR

# last object name whose knobs were loaded into the wizard, so switching
# selection reloads knobs exactly once per switch
_active_knob_source = None


def _seed_update(self, context):
    """Seed changed — retarget the active plant (its mesh rebuilds via the
    refresh timer because ps_seed now differs from ps_built_seed)."""
    from .animator import _active_plant
    obj = _active_plant()
    if obj is not None:
        obj["ps_seed"] = int(self.seed)
        from .wizard import _ensure_timer
        _ensure_timer()


def _library_categories():
    try:
        lib, _ = get_library()
        by_cat = lib.names_by_category() if lib else {}
    except Exception:
        by_cat = {}
    return [c for c in by_cat if "tutorial" not in c.lower() and by_cat[c]]


def _user_categories():
    cats = []
    if os.path.isdir(USER_PRESETS_DIR):
        for entry in sorted(os.listdir(USER_PRESETS_DIR)):
            if os.path.isdir(os.path.join(USER_PRESETS_DIR, entry)):
                cats.append(entry)
    return cats


def _all_categories():
    return sorted(set(_library_categories()) | set(_user_categories()))


def _category_entries(cat):
    """Fresh list of (display_name, is_user_preset) for a category menu."""
    entries = []
    try:
        lib, _ = get_library()
        by_cat = lib.names_by_category() if lib else {}
        entries += [(n, False) for n in by_cat.get(cat, [])[:100]]
    except Exception:
        pass
    cat_dir = os.path.join(USER_PRESETS_DIR, cat)
    if os.path.isdir(cat_dir):
        for fn in sorted(os.listdir(cat_dir)):
            if fn.endswith(".json"):
                entries.append((fn[:-5], True))
    return entries


def _menu_id(cat):
    return "PS_MT_preset_" + re.sub(r"\W", "_", cat)


def _make_category_draw(cat):
    def draw(self, context):
        layout = self.layout
        for text, is_user in _category_entries(cat):
            op = layout.operator("plantstudio.load_preset", text=text)
            # Explicitly set BOTH branches' properties so a stale value from a
            # previous menu click can never hijack a species load (Blender can
            # retain operator string/enum property values across invocations).
            if is_user:
                op.species_name = ""
                op.preset_name = text
                op.preset_category = cat
            else:
                op.species_name = text
                op.preset_name = ""
                op.preset_category = ""
    return draw


def ensure_category_menu(cat):
    """Register (if missing) the submenu class for one preset category."""
    menu_id = _menu_id(cat)
    if menu_id in dir(bpy.types):
        return
    cls = type(
        menu_id,
        (bpy.types.Menu,),
        {
            "bl_idname": menu_id,
            "bl_label": cat,
            "draw": _make_category_draw(cat),
        },
    )
    bpy.utils.register_class(cls)


class PS_MT_presets(bpy.types.Menu):
    """Preset picker: submenus per category (library + saved user presets)."""
    bl_label = "PlantStudio-Blender Presets"
    bl_idname = "PS_MT_presets"

    def draw(self, context):
        layout = self.layout
        for cat in _all_categories():
            ensure_category_menu(cat)
            layout.menu(_menu_id(cat), text=cat, icon='FILE_FOLDER')


def register_category_menus():
    """Register one submenu class per preset category (library + user)."""
    for cat in _all_categories():
        ensure_category_menu(cat)


class PSProperties(bpy.types.PropertyGroup):
    seed: IntProperty(name="Seed", default=280, min=1, max=99999,
                      update=_seed_update)
    day: IntProperty(name="Age (days)", default=60, min=0, max=1000)
    export_dir: StringProperty(
        name="Export Dir",
        subtype='DIR_PATH',
        default="",
        description="Directory for exported plant configs (JSON). Leave empty to "
                    "use $PLANTSTUDIO_PLANTS_DIR or ~/.plantstudio/exports",
    )


@bpy.app.handlers.persistent
def _depsgraph_load_active_knobs(scene, depsgraph):
    """Load the active plant's stored knobs into the wizard on selection."""
    global _active_knob_source
    if bpy.app.background:
        return
    view_layer = bpy.context.view_layer
    obj = view_layer.objects.active if view_layer else None
    name = obj.name if (obj is not None and obj.type == 'MESH'
                        and "ps_species" in obj) else None
    if name == _active_knob_source:
        return
    _active_knob_source = name
    if name is None:
        return
    # guard against re-entrant depsgraph updates during data changes
    if getattr(bpy.context.scene, "ps_wizard_knobs", None) is None:
        return
    try:
        from . import wizard
        # loading programmatically must not fire _knob_update (which would
        # save the half-loaded group back onto the plant)
        wizard._loading = True
        try:
            wizard.load_knobs_from_obj(obj, bpy.context.scene.ps_wizard_knobs)
        finally:
            wizard._loading = False
    except Exception:
        pass


def _draw_export(layout, props):
    box = layout.box()
    box.prop(props, "export_dir", text="Config export dir")
    box.operator("plantstudio.export_plant_config",
                 text="export with metadata", icon='EXPORT')


class PS_PT_panel(Panel):
    bl_label = "PlantStudio-Blender"
    bl_idname = "PS_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "PlantStudio-Blender"

    def draw(self, context):
        try:
            self._draw(context)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.layout.label(text=f"PlantStudio-Blender error: {e}", icon='ERROR')

    def _draw(self, context):
        from .wizard import knobs_for_step, STEP_NAMES, placement_enabled

        layout = self.layout
        props = context.scene.ps_props
        knobs = context.scene.ps_wizard_knobs

        obj = context.view_layer.objects.active
        is_plant = (obj is not None and obj.type == 'MESH'
                    and "ps_species" in obj)

        # ── New Plant: Load and Create share this panel ──
        box = layout.box()
        box.label(text="New Plant", icon='PRESET')
        row = box.row(align=True)
        row.menu("PS_MT_presets", text="Load Preset", icon='FILE_FOLDER')
        row.operator("plantstudio.add_plant", text="Create", icon='ADD')
        row2 = box.row(align=True)
        row2.label(text="Seed:")
        row2.prop(props, "seed", text="")

        if not is_plant:
            box = layout.box()
            box.label(text="Select a plant", icon='INFO')
            box.label(text="(or Create / Load Preset above)")
            _draw_export(layout, props)
            return
        box = layout.box()
        box.label(text=f"Plant — {obj.name}", icon='OUTLINER_OB_MESH')
        col = box.column(align=True)
        # ps_day / ps_seed are the plant's own age and seed; drawn from the
        # object so keyframes and per-plant values just work (keyable by
        # hovering + pressing I, or by any driver you add to it)
        col.prop(obj, '["ps_day"]', text="Age (days)")
        col.prop(obj, '["ps_seed"]', text="Seed")

        # all wizard sections in one panel, in order
        can_repro = placement_enabled(knobs)
        for s, section_name in enumerate(STEP_NAMES):
            if s >= 5 and not can_repro:
                continue  # inflor drawing / flowers / fruits hidden
            sub = box.box()
            sub.label(text=section_name, icon='OPTIONS')
            col = sub.column(align=True)
            col.scale_y = 0.7
            for defn in knobs_for_step(s):
                if len(defn) == 7:
                    prop_name, _path, label, _lo, _hi, _default, kstep = defn
                elif len(defn) == 4:
                    prop_name, _path, label, kstep = defn
                else:
                    continue
                col.prop(knobs, prop_name, text=label)

        # ── Export ──
        _draw_export(layout, props)
