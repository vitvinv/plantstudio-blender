"""N-panel UI for the PlantStudio-Blender addon.

Layout:
  - New Plant box: preset Load menu + Create button
  - Selected Plant box: per-plant age + growth % (keyable) + wizard knobs
  - Export box: config export dir + export button

Plants are picked in the viewport or Outliner (active object) — no separate
plant list. Per-plant knobs and age live on each object (ps_knobs / ps_day);
a depsgraph handler loads the active plant's knobs into the wizard.
"""

import os
import re
import json
import bpy
from bpy.types import Panel, PropertyGroup
from .animator import is_growth_animated
from .scene_bridge import plants
from bpy.props import (StringProperty, IntProperty, PointerProperty,
                       BoolProperty, EnumProperty)

from .operators import (get_library, USER_PRESETS_DIR, BREEDS_DIR,
                        get_breeder_strategy)

# last object name whose knobs were loaded into the wizard, so switching
# selection reloads knobs exactly once per switch
_active_knob_source = None


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
        breeds = _breed_files()
        if breeds:
            layout.menu("PS_MT_breeds", text="Breeds", icon='PARTICLE_DATA')
            layout.separator()
        for cat in _all_categories():
            ensure_category_menu(cat)
            layout.menu(_menu_id(cat), text=cat, icon='FILE_FOLDER')


def _breed_files():
    """Saved breed files (name, path) from ~/.plantstudio/breeds."""
    if not os.path.isdir(BREEDS_DIR):
        return []
    return [(fn[:-5], os.path.join(BREEDS_DIR, fn))
            for fn in sorted(os.listdir(BREEDS_DIR))
            if fn.endswith(".json") and not fn.endswith(".strategy.json")]


class PS_MT_breeds(bpy.types.Menu):
    """Saved bred plants (full params, rebuildable)."""
    bl_idname = "PS_MT_breeds"
    bl_label = "Breeds"

    def draw(self, context):
        layout = self.layout
        breeds = _breed_files()
        if not breeds:
            layout.label(text="No saved breeds", icon='INFO')
            return
        for name, _path in breeds:
            op = layout.operator("plantstudio.load_preset", text=name)
            op.species_name = ""
            op.preset_name = ""
            op.preset_category = ""
            op.breed_name = name


def register_category_menus():
    """Register one submenu class per preset category (library + user)."""
    for cat in _all_categories():
        ensure_category_menu(cat)


class PSProperties(bpy.types.PropertyGroup):
    day: IntProperty(name="Age (days)", default=60, min=0, max=1000)
    export_dir: StringProperty(
        name="Export Dir",
        subtype='DIR_PATH',
        default="",
        description="Directory for exported plant configs (JSON). Leave empty to "
                    "use $PLANTSTUDIO_PLANTS_DIR or ~/.plantstudio/exports",
    )


# ── breeder ──

def _breeder_section_items(_self, _context):
    from .core.breeding import load_sections
    items = [(str(i), s["name"], "") for i, s in enumerate(load_sections())]
    return items or [("0", "General parameters", "")]


def _breeder_section_changed(self, context):
    """Load the picked section's values into the two sliders."""
    try:
        strategy = get_breeder_strategy(self)
        index = int(self.section)
        self.section_mutation = int(strategy.mutationStrengths[index])
        self.section_weight = int(strategy.firstPlantWeights[index])
    except Exception:
        pass


def _breeder_value_changed(self, context):
    """Write the slider values back into the stored strategy."""
    try:
        strategy = get_breeder_strategy(self)
        index = int(self.section)
        strategy.mutationStrengths[index] = int(self.section_mutation)
        strategy.firstPlantWeights[index] = int(self.section_weight)
        self.strategy_json = json.dumps(strategy.to_dict())
    except Exception:
        pass


class PSBreederProps(bpy.types.PropertyGroup):
    offspring_count: IntProperty(
        name="Offspring", default=3, min=1, max=20,
        description="How many offspring one Breed click creates")
    breeding_seed: IntProperty(
        name="Breeding seed", default=280, min=1,
        description="Same parents + same seed + same count = identical offspring")
    mutation_scale: IntProperty(
        name="Mutation %", default=100, min=0, max=200,
        description="Scales every section's mutation strength")
    show_advanced: BoolProperty(name="Advanced", default=False)
    section: EnumProperty(
        name="Section", items=_breeder_section_items,
        update=_breeder_section_changed,
        description="Which breeding section the sliders edit")
    section_mutation: IntProperty(
        name="Mutation", default=60, min=0, max=100,
        update=_breeder_value_changed,
        description="Mutation strength for the picked section (0-100)")
    section_weight: IntProperty(
        name="Parent A weight", default=50, min=0, max=100,
        update=_breeder_value_changed,
        description="Blend weight of parent A for the picked section")
    strategy_json: StringProperty(
        name="Strategy", default="",
        description="Stored breeding strategy (per-section mutation/weights)")


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
        row.operator("plantstudio.save_preset", text="Save Preset",
                     icon='FILE_TICK')
        row.operator("plantstudio.add_plant", text="Create", icon='ADD')

        if not is_plant:
            box = layout.box()
            box.label(text="Select a plant", icon='INFO')
            box.label(text="(or Create / Load Preset above)")
            _draw_export(layout, props)
            return
        box = layout.box()
        box.label(text=f"Plant — {obj.name}", icon='OUTLINER_OB_MESH')
        col = box.column(align=True)
        # ps_day / ps_pct / ps_seed are the plant's own age, growth-% mirror
        # and seed; drawn from the object so keyframes and per-plant values
        # just work (keyable by hovering + pressing I, or by any driver you
        # add to it). The animator keeps day and % in sync — whichever you
        # move last wins, so driving one plant's % and copying that driver
        # onto others makes them grow in lockstep.
        col.prop(obj, '["ps_day"]', text="Age (days)")
        col.prop(obj, '["ps_pct"]', text="Growth (% of full)")
        col.prop(obj, '["ps_seed"]', text="Seed")
        if any(is_growth_animated(p) for p in plants()):
            note = box.box()
            text = note.column(align=True)  # aligned: no gaps between lines
            text.label(text="Growth is animated.", icon='INFO')
            text.label(text="Plain render (Ctrl+F12) won't grow")
            text.label(text="the plants: use the button below.")
            note.operator("plantstudio.render_growth", icon='RENDER_ANIMATION')

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

        # ── Breeder ──
        breeder = context.scene.ps_breeder
        box = layout.box()
        box.label(text="Breeder", icon='PARTICLE_DATA')
        col = box.column(align=True)
        col.label(text=f"Parent A: {obj.name}")
        others = [o for o in context.selected_objects
                  if o != obj and o.type == 'MESH' and "ps_species" in o]
        col.label(text="Parent B: " + (others[0].name if others
                                       else "none (mutation only)"))
        col.prop(breeder, "offspring_count")
        col.prop(breeder, "breeding_seed")
        col.prop(breeder, "mutation_scale")
        col.operator("plantstudio.breed", icon='PLUS')
        box.prop(breeder, "show_advanced")
        if breeder.show_advanced:
            col = box.column(align=True)
            col.prop(breeder, "section", text="Section")
            col.prop(breeder, "section_mutation")
            col.prop(breeder, "section_weight")
            row = col.row(align=True)
            row.operator("plantstudio.breed_strategy_save", text="Save")
            row.operator("plantstudio.breed_strategy_load", text="Load")

        # ── Export ──
        _draw_export(layout, props)
