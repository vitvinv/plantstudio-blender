"""N-panel UI for the PlantStudio-Blender addon.

Layout:
  - New Plant box: preset Load menu + Create button + seed (shared panel)
  - Plant list (Blender-style UIList of all plants in the scene)
  - Wizard: step navigation (Meristems/Internodes/Leaves/...),
    live knobs for the selected plant + Save Preset dialog
"""

import os
import re
import bpy
from bpy.types import Panel, UIList, PropertyGroup
from bpy.props import (StringProperty, IntProperty, PointerProperty,
                       EnumProperty, CollectionProperty, BoolProperty)

from .operators import get_library, USER_PRESETS_DIR


def _species_items(self, context):
    """Dynamic enum items, grouped by category (.pla file name).
    Tutorial categories are excluded."""
    try:
        lib, _ = get_library()
        by_cat = lib.names_by_category() if lib else {}
    except Exception:
        by_cat = {}
    items = []
    skip_cats = [c for c in by_cat if "tutorial" in c.lower()]
    for cat in sorted(by_cat.keys()):
        if cat in skip_cats:
            continue
        names = by_cat[cat]
        if names:
            items.append(("", cat, "", 'NONE', 0))
            for n in names[:100]:
                items.append((n, n, ""))
    if not items:
        items.append(("maiden grass", "maiden grass", ""))
    return items


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


def _seed_update(self, context):
    """Seed changed — rebuild the selected plant with the new seed."""
    knobs = context.scene.ps_wizard_knobs
    coll = bpy.data.collections.get("PlantStudio Plants")
    if coll is not None and 0 <= knobs.selected_index < len(coll.objects):
        obj = coll.objects[knobs.selected_index]
        obj["ps_seed"] = int(self.seed)
        knobs.dirty = True
        from .wizard import _ensure_timer
        _ensure_timer()


class PSProperties(bpy.types.PropertyGroup):
    species_name: EnumProperty(name="Species", items=_species_items)
    base_species: StringProperty(name="Base species", default="")
    seed: IntProperty(name="Seed", default=280, min=1, max=99999, update=_seed_update)
    day: IntProperty(name="Age (days)", default=60, min=0, max=1000)


class PSPlantListItem(PropertyGroup):
    name: StringProperty()
    selected: BoolProperty(name="Export", default=True)


class PSPlantList(PropertyGroup):
    plants: CollectionProperty(type=PSPlantListItem)


def sync_plant_list(scene):
    """Reconcile the ps_plant_list collection with the scene collection.

    Must NOT be called during panel draw (Blender forbids writing to
    ID data in draw). Called from operators and a depsgraph handler.
    """
    from .scene_bridge import COLLECTION_NAME
    try:
        plist = scene.ps_plant_list
    except AttributeError:
        return
    coll = bpy.data.collections.get(COLLECTION_NAME)
    names = [o.name for o in coll.objects] if coll else []
    current = [i.name for i in plist.plants]
    if names != current:
        plist.plants.clear()
        for n in names:
            item = plist.plants.add()
            item.name = n


@bpy.app.handlers.persistent
def _depsgraph_sync_plant_list(scene, depsgraph):
    """Keep the plant list in sync when objects are added/removed/renamed."""
    try:
        sync_plant_list(scene)
    except Exception:
        pass


class PS_UL_plants(UIList):
    """Blender-style list of plants in the scene."""

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, "selected", text="")
            row.prop(item, "name", text="", emboss=False,
                     icon='OUTLINER_OB_MESH')
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon='OUTLINER_OB_MESH')


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
        from .scene_bridge import COLLECTION_NAME
        from .wizard import knobs_for_step, STEP_NAMES, placement_enabled

        layout = self.layout
        props = context.scene.ps_props
        knobs = context.scene.ps_wizard_knobs
        plist = context.scene.ps_plant_list

        coll = bpy.data.collections.get(COLLECTION_NAME)
        plants = list(coll.objects) if coll else []
        selected_valid = (0 <= knobs.selected_index < len(plants))

        # ── New Plant: Load and Create share this panel ──
        box = layout.box()
        box.label(text="New Plant", icon='PRESET')
        row = box.row(align=True)
        row.menu("PS_MT_presets", text="Load Preset", icon='FILE_FOLDER')
        row.operator("plantstudio.add_plant", text="Create", icon='ADD')
        row2 = box.row(align=True)
        row2.label(text="Seed:")
        row2.prop(props, "seed", text="")

        # ── Plant list ──
        box = layout.box()
        box.label(text=f"Plants ({len(plants)})", icon='OUTLINER_OB_MESH')
        box.template_list("PS_UL_plants", "", plist, "plants",
                          knobs, "selected_index")
        box.operator("plantstudio.export_plant_config",
                     text="export with metadata", icon='EXPORT')
        box.operator("plantstudio.delete_plant", text="Delete Plant",
                     icon='TRASH')

        # ── Wizard (selected plant) ──
        if selected_valid:
            obj = plants[knobs.selected_index]
            box = layout.box()
            box.label(text=f"Wizard — {obj.name}", icon='TOOL_SETTINGS')

            row = box.row(align=True)
            row.label(text="Age (days):")
            row.prop(knobs, "knob_day", text="")
            row.operator("plantstudio.save_preset", text="Save Preset",
                         icon='FILE_TICK')

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
        else:
            box = layout.box()
            box.label(text="No plant selected.", icon='INFO')
            box.label(text="Click Create to make a new plant.")


def register_panel_classes():
    pass
