"""PlantStudio-Blender growth animation operator."""

import bpy
from bpy.types import Operator
from bpy.props import IntProperty

from .scene_bridge import build_plant_object, plant_object_name
from .operators import get_library


class PS_OT_animate_growth(Operator):
    """Animate the selected plant's growth over frames."""
    bl_idname = "plantstudio.animate_growth"
    bl_label = "Animate Growth"
    bl_description = "Animate plant growth day by day over frames"

    days_per_frame: IntProperty(name="Days per frame", default=2, min=1, max=50)

    _timer = None
    _obj = None
    _species = None
    _tdo_lib = None
    _current_day = 0
    _target_day = 0

    def modal(self, context, event):
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            self.cancel(context)
            return {'CANCELLED'}
        if event.type == 'TIMER':
            if self._current_day >= self._target_day:
                self.cancel(context)
                return {'CANCELLED'}
            self._current_day = min(self._current_day + self.days_per_frame,
                                    self._target_day)
            obj = self._obj
            obj["ps_day"] = self._current_day
            # rebuild the mesh in place
            species_name = getattr(self._species, "name", "plant")
            seed = int(obj["ps_seed"])
            new_obj = build_plant_object(self._species, seed,
                                         self._current_day,
                                         obj.users_collection[0], self._tdo_lib)
            new_obj.matrix_world = obj.matrix_world
            bpy.data.objects.remove(obj, do_unlink=True)
            # re-claim the canonical name (Blender may have added ".001")
            new_obj.name = plant_object_name(species_name, seed,
                                             self._current_day)
            self._obj = new_obj
            context.view_layer.objects.active = new_obj
            new_obj.select_set(True)
            context.scene.frame_set(self._current_day)
            # update the timeline to reflect current day
            self._refresh_timeline(context)
        return {'PASS_THROUGH'}

    def _refresh_timeline(self, context):
        scene = context.scene
        if scene.frame_end < self._target_day:
            scene.frame_end = self._target_day

    def execute(self, context):
        obj = context.active_object
        if obj is None or "ps_species" not in obj:
            self.report({'ERROR'}, "Select a PlantStudio plant")
            return {'CANCELLED'}
        self._obj = obj
        self._current_day = int(obj["ps_day"])
        self._target_day = 0
        # grow to maturity for the animation end
        lib, tdo_lib = get_library()
        self._species = lib.get(obj["ps_species"])
        self._tdo_lib = tdo_lib
        if self._species is None:
            self.report({'ERROR'}, "Species not found")
            return {'CANCELLED'}
        maturity = int(self._species.params.pGeneral.ageAtMaturity)
        self._target_day = max(self._current_day + 1, maturity)
        context.scene.frame_start = 0
        context.scene.frame_end = self._target_day
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.05, window=context.window)
        wm.modal_handler_add(self)
        self.report({'INFO'}, f"Animating growth to day {self._target_day}")
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
