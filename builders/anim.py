"""Animation helpers shared by the builders."""


def find_fcurves(anim_data, data_path):
    """All fcurves on an animated ID matching a data path, handling both the
    legacy Action.fcurves API and Blender 5.x slotted actions."""
    if not anim_data or not anim_data.action:
        return []
    action = anim_data.action
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        fcurves = list(legacy)
    else:
        fcurves = []
        slot = anim_data.action_slot
        if slot is not None:
            for layer in action.layers:
                for strip in layer.strips:
                    channelbag = strip.channelbag(slot)
                    if channelbag is not None:
                        fcurves.extend(channelbag.fcurves)
    return [fc for fc in fcurves if fc.data_path == data_path]
