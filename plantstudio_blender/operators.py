"""Blender operators for the PlantStudio-Blender addon."""

import os
import json
import bpy
from bpy.types import Operator
from bpy.props import IntProperty, StringProperty, BoolProperty, EnumProperty

from .core.plant_library import SpeciesLibrary
from .core.tdo_parser import TdoLibrary
from .scene_bridge import (ensure_collection, build_plant_object,
                           COLLECTION_NAME, plant_object_name)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
USER_PRESETS_DIR = os.path.join(DATA_DIR, "user-presets")

# module-level cache: parsing 9 .pla files on every UI draw is slow
_lib_cache = None
_tdo_cache = None


def clear_library_cache():
    global _lib_cache, _tdo_cache
    _lib_cache = None
    _tdo_cache = None


def get_library():
    """Get the cached species library + tdo library (parsed once)."""
    global _lib_cache, _tdo_cache
    if _lib_cache is None:
        _lib_cache = SpeciesLibrary(DATA_DIR)
    if _tdo_cache is None:
        path = os.path.join(DATA_DIR, "3D object library.tdo")
        _tdo_cache = TdoLibrary.from_file(path) if os.path.exists(path) else None
    return _lib_cache, _tdo_cache


def _default_species():
    """A species wrapper whose params are the original PlantStudio defaults."""
    from .core.defaults import make_default_params
    params = make_default_params()
    return _named_params(params, "plant")


def _named_params(params, name):
    """Wrap raw params so they carry a species-like name."""
    class _Named:
        pass
    n = _Named()
    n.params = params
    n.name = name
    return n


def _create_plant_object(params, base_species, seed, day, context, name=None):
    """Grow + link a new plant from params; select it and sync the wizard."""
    from .wizard import load_knobs_from_params, save_knobs_to_obj
    from .ui_panel import sync_plant_list
    _, tdo_lib = get_library()
    coll = ensure_collection(COLLECTION_NAME)
    wrapped = _named_params(params, name or "plant")
    obj = build_plant_object(wrapped, seed, day, coll, tdo_lib)
    obj["ps_base_species"] = base_species
    knobs = context.scene.ps_wizard_knobs
    load_knobs_from_params(params, knobs)
    save_knobs_to_obj(obj, knobs)
    knobs.selected_index = len(coll.objects) - 1
    sync_plant_list(context.scene)
    context.view_layer.objects.active = obj
    obj.select_set(True)
    return obj


def _sanitize_name(name):
    """Make a name safe to use as a file/folder name."""
    import re
    return re.sub(r'[\\/:*?"<>|]', "", str(name)).strip()


def _plant_id(species, seed):
    """Canonical plant id: lowercase slug species + seed (e.g. daylily_280)."""
    import re
    slug = re.sub(r'[^a-z0-9]+', '_', str(species).strip().lower()).strip('_')
    return f"{slug}_{int(seed):d}"


def resolve_plants_dir():
    """Locate digital-garden-AR/src/assets/plants for export.

    Order: explicit env override -> walk up from the addon's module
    location (covers running the addon straight from the repo) -> common
    repo locations under the user profile (covers Blender appdata installs).
    """
    env = os.environ.get("PLANTSTUDIO_PLANTS_DIR")
    if env and os.path.isdir(env):
        return env
    start = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cur = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(cur, "digital-garden-AR", "src")):
            return os.path.join(cur, "digital-garden-AR", "src", "assets",
                                "plants")
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    for base in (os.path.expanduser("~"), os.path.expanduser("~/dev"),
                 os.path.expanduser("~/projects")):
        for name in ("digital-garden", "digital_garden"):
            cand = os.path.join(base, name, "digital-garden-AR", "src",
                                "assets", "plants")
            if os.path.isdir(cand):
                return cand
    raise RuntimeError(
        "Cannot locate digital-garden-AR/src/assets/plants for export. "
        "Set PLANTSTUDIO_PLANTS_DIR to the plants directory.")


def _user_preset_categories():
    cats = []
    if os.path.isdir(USER_PRESETS_DIR):
        for entry in sorted(os.listdir(USER_PRESETS_DIR)):
            if os.path.isdir(os.path.join(USER_PRESETS_DIR, entry)):
                cats.append(entry)
    return cats


def _preset_category_items(self, context):
    items = [(c, c, "") for c in _user_preset_categories()]
    items.append(("NEW", "New category...", ""))
    return items or [("NEW", "New category...", "")]


def _params_from_user_preset(category, name):
    """Load a saved preset json and rebuild params (defaults/species + knobs)."""
    from .core.tdo_parser import AssetError
    from .wizard import (KNOB_DEFS, SHAPE_KNOB_DEFS, COLOR_KNOB_DEFS,
                         DEFAULT_TDO_NAME, apply_knobs_to_params)
    from types import SimpleNamespace
    path = os.path.join(USER_PRESETS_DIR, _sanitize_name(category),
                        f"{_sanitize_name(name)}.json")
    if not os.path.exists(path):
        raise AssetError(
            f"preset '{name}' not found in category '{category}' "
            f"(expected {path})")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    knobs_ns = SimpleNamespace()
    saved = data.get("knobs", {})
    for pn, _path, _label, _lo, _hi, _default, _step in KNOB_DEFS:
        setattr(knobs_ns, pn, float(saved.get(pn, _default)))
    for pn, _path, _label, _step in SHAPE_KNOB_DEFS:
        setattr(knobs_ns, pn, str(saved.get(pn, DEFAULT_TDO_NAME)))
    for pn, _path, _label, _step in COLOR_KNOB_DEFS:
        color = saved.get(pn)
        if color:
            setattr(knobs_ns, pn, tuple(float(c) for c in color))
        else:
            setattr(knobs_ns, pn, (0.2, 0.6, 0.3))
    base_name = data.get("base_species", "")
    base = None
    if base_name:
        lib, _ = get_library()
        base = lib.get(base_name)
    if base is None:
        base = _default_species()
    params = apply_knobs_to_params(base, knobs_ns)
    return params, base_name or ""


def _get_species(name):
    """Get a species by name (library or default)."""
    lib, _ = get_library()
    s = lib.get(name)
    if s is not None:
        return s
    return _default_species()


def _species_items(self, context):
    from .core.tdo_parser import AssetError
    try:
        lib, _ = get_library()
        names = lib.names() if lib else []
    except Exception as e:
        raise AssetError(
            f"cannot load species library for the preset list: {e}")
    items = [(n, n, n) for n in names[:500]]
    if not items:
        raise AssetError(
            "cannot populate the preset list: the species library is empty "
            "(no .pla files were found or parsed in the data directory)")
    return items


class PS_OT_add_plant(Operator):
    bl_idname = "plantstudio.add_plant"
    bl_label = "Create"
    bl_description = "Create a new plant with all original PlantStudio default settings"

    def execute(self, context):
        props = context.scene.ps_props
        from .core.defaults import make_default_params
        params = make_default_params()
        obj = _create_plant_object(params, "", props.seed, props.day, context,
                                   name="plant")
        self.report({'INFO'}, f"Created {obj.name} from default settings "
                              f"({len(obj.data.polygons)} faces)")
        return {'FINISHED'}


class PS_OT_load_preset(Operator):
    bl_idname = "plantstudio.load_preset"
    bl_label = "Load Preset"
    bl_description = "Create a new plant from a library species or a saved preset"
    species_name: EnumProperty(name="Species", items=_species_items)
    preset_name: StringProperty(name="Preset", default="")
    preset_category: StringProperty(name="Preset category", default="")

    def execute(self, context):
        props = context.scene.ps_props
        import copy
        if self.species_name:
            # library species — non-empty species_name wins, so a stale
            # preset_name/preset_category from a previous call can never
            # hijack a species load.
            lib, _ = get_library()
            species = lib.get(self.species_name)
            if species is None:
                self.report({'ERROR'}, f"Species '{self.species_name}' not found")
                return {'CANCELLED'}
            params = copy.deepcopy(species.params)
            base_name = species.name
            display = species.name
        else:
            # saved user preset (json with base species + knob deltas)
            if not (self.preset_name and self.preset_category):
                self.report({'ERROR'}, "No species or preset selected")
                return {'CANCELLED'}
            try:
                params, base_name = _params_from_user_preset(
                    self.preset_category, self.preset_name)
            except Exception as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            display = self.preset_name
        obj = _create_plant_object(params, base_name, props.seed, props.day,
                                   context, name=display)
        self.report({'INFO'}, f"Created new plant from preset: {display}")
        return {'FINISHED'}


class PS_OT_wizard_step(Operator):
    bl_idname = "plantstudio.wizard_step"
    bl_label = "Wizard Step"
    bl_description = "Navigate the plant wizard"
    step: IntProperty(name="Step", default=0)

    def execute(self, context):
        knobs = context.scene.ps_wizard_knobs
        from .wizard import STEP_NAMES, placement_enabled
        can_repro = placement_enabled(knobs)
        step = max(0, min(7, self.step))
        # skip steps 5-7 if inflorescence placement disabled
        if not can_repro and step >= 5:
            step = 4
        knobs.wizard_step = step
        return {'FINISHED'}


class PS_OT_save_preset(Operator):
    bl_idname = "plantstudio.save_preset"
    bl_label = "Save Preset"
    bl_description = "Save the selected plant's settings as a preset (name + category)"
    preset_name: StringProperty(name="Name", default="", maxlen=64)
    category: EnumProperty(name="Category", items=_preset_category_items)
    new_category: StringProperty(name="New category", default="", maxlen=64)

    def invoke(self, context, event):
        # prefill the name from the selected plant
        if not self.preset_name:
            knobs = context.scene.ps_wizard_knobs
            coll = bpy.data.collections.get(COLLECTION_NAME)
            if coll is not None and 0 <= knobs.selected_index < len(coll.objects):
                obj = coll.objects[knobs.selected_index]
                self.preset_name = obj.get("ps_base_species", "") or \
                    obj.name.split("_")[0]
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "preset_name")
        layout.prop(self, "category")
        if self.category == "NEW":
            layout.prop(self, "new_category")

    def execute(self, context):
        knobs = context.scene.ps_wizard_knobs
        coll = bpy.data.collections.get(COLLECTION_NAME)
        if coll is None or not (0 <= knobs.selected_index < len(coll.objects)):
            self.report({'ERROR'}, "Select a plant in the list first")
            return {'CANCELLED'}
        obj = coll.objects[knobs.selected_index]
        name = _sanitize_name(self.preset_name) or "preset"
        if self.category == "NEW":
            category = _sanitize_name(self.new_category) or "My Presets"
        else:
            category = _sanitize_name(self.category) or "My Presets"
        from .wizard import _knobs_to_dict
        preset = {
            "name": name,
            "category": category,
            "base_species": obj.get("ps_base_species", ""),
            "knobs": _knobs_to_dict(knobs),
        }
        cat_dir = os.path.join(USER_PRESETS_DIR, category)
        os.makedirs(cat_dir, exist_ok=True)
        path = os.path.join(cat_dir, f"{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(preset, f, indent=2)
        from .ui_panel import ensure_category_menu
        ensure_category_menu(category)
        self.report({'INFO'}, f"Saved preset '{name}' to category '{category}'")
        return {'FINISHED'}


class PS_OT_regrow(Operator):
    bl_idname = "plantstudio.regrow"
    bl_label = "Grow To Age"
    bl_description = "Rebuild the selected plant at its target day"

    def execute(self, context):
        obj = context.active_object
        if obj is None or "ps_species" not in obj:
            self.report({'ERROR'}, "Select a PlantStudio plant")
            return {'CANCELLED'}
        _, tdo_lib = get_library()
        species_name = obj["ps_species"]
        species = _get_species(species_name)
        day = int(obj["ps_day"])
        seed = int(obj["ps_seed"])
        new_obj = build_plant_object(species, seed, day,
                                     obj.users_collection[0], tdo_lib)
        new_obj.matrix_world = obj.matrix_world
        bpy.data.objects.remove(obj, do_unlink=True)
        # Blender may have auto-suffixed the fresh object (".001") while the
        # old one still held the canonical name; claim the canonical name now.
        new_obj.name = plant_object_name(species_name, seed, day)
        context.view_layer.objects.active = new_obj
        new_obj.select_set(True)
        self.report({'INFO'}, f"Regrew to day {day}")
        return {'FINISHED'}


class PS_OT_step_day(Operator):
    bl_idname = "plantstudio.step_day"
    bl_label = "Step Day"
    bl_description = "Advance the selected plant by one day"

    def execute(self, context):
        obj = context.active_object
        if obj is None or "ps_day" not in obj:
            self.report({'ERROR'}, "Select a PlantStudio plant")
            return {'CANCELLED'}
        obj["ps_day"] = int(obj["ps_day"]) + 1
        bpy.ops.plantstudio.regrow()
        return {'FINISHED'}


class PS_OT_delete_plant(Operator):
    bl_idname = "plantstudio.delete_plant"
    bl_label = "Delete Plant"
    bl_description = "Remove the selected plant from the scene"

    def execute(self, context):
        knobs = context.scene.ps_wizard_knobs
        coll = bpy.data.collections.get(COLLECTION_NAME)
        if coll is None or not (0 <= knobs.selected_index < len(coll.objects)):
            self.report({'ERROR'}, "Select a plant in the list first")
            return {'CANCELLED'}
        obj = coll.objects[knobs.selected_index]
        bpy.data.objects.remove(obj, do_unlink=True)
        knobs.selected_index = min(knobs.selected_index, len(coll.objects) - 1)
        from .ui_panel import sync_plant_list
        sync_plant_list(context.scene)
        return {'FINISHED'}


class PS_OT_random_seed(Operator):
    bl_idname = "plantstudio.random_seed"
    bl_label = "Randomize Seed"

    def execute(self, context):
        import random
        context.scene.ps_props.seed = random.randint(1, 9999)
        return {'FINISHED'}


class PS_OT_export_plant_config(Operator):
    bl_idname = "plantstudio.export_plant_config"
    bl_label = "Export Plant Config"
    bl_description = ("Write one JSON config (plant_id/species/seed/planted_date) "
                      "per checked plant to digital-garden-AR/src/assets/plants/ "
                      "so the cloud regeneration script can grow these plants daily; "
                      "plant_id is derived from species+seed, dates are strict ISO")

    def execute(self, context):
        from datetime import date, timedelta

        coll = bpy.data.collections.get(COLLECTION_NAME)
        if coll is None:
            self.report({'ERROR'}, "No PlantStudio plant collection in the scene")
            return {'CANCELLED'}

        objects = {o.name: o for o in coll.objects}
        selected = [i.name for i in context.scene.ps_plant_list.plants
                    if i.selected]
        if not selected:
            self.report({'ERROR'}, "Check at least one plant in the list to export")
            return {'CANCELLED'}

        try:
            plants_dir = resolve_plants_dir()
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        os.makedirs(plants_dir, exist_ok=True)

        planted = date.today()
        seen = set()
        warnings = []
        exported = []
        for name in selected:
            obj = objects.get(name)
            if obj is None or "ps_species" not in obj:
                warnings.append(f"'{name}' is not a PlantStudio plant")
                continue
            species = str(obj["ps_species"])
            seed = int(obj["ps_seed"])
            day = int(obj["ps_day"])
            plant_id = _plant_id(species, seed)
            if plant_id in seen:
                warnings.append(
                    f"'{name}' skipped: plant_id '{plant_id}' already exported "
                    f"by another checked plant (same species + seed) — not "
                    f"overwriting")
                continue
            seen.add(plant_id)
            planted_date = (planted - timedelta(days=day)).isoformat()
            out_path = os.path.join(plants_dir, f"{plant_id}.json")
            config = {
                "plant_id": plant_id,
                "species": species,
                "seed": seed,
                "planted_date": planted_date,
            }
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
                f.write("\n")
            exported.append(f"Exported {plant_id} (day {day}, "
                            f"planted {planted_date})")

        for w in warnings:
            self.report({'WARNING'}, w)
        for line in exported:
            self.report({'INFO'}, line)
        if not exported:
            self.report({'ERROR'}, "Nothing exported — check a valid plant")
            return {'CANCELLED'}
        self.report({'INFO'}, f"{len(exported)} config(s) written to "
                              f"{plants_dir}")
        return {'FINISHED'}
