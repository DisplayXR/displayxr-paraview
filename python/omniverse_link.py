"""ParaView -> Omniverse: export the render view as USD for USD Composer (or any Kit app).

    import omniverse_link as ov
    ov.send()            # one export
    ov.live(True)        # re-export whenever the visible scene or time changes

Uses ParaView's own USD exporter (vtkUSDExporter, ParaView >= 6.1), so no NVIDIA
connector is needed. The file is replaced atomically, so a Kit app watching it never
reads a half-written stage. Open it in USD Composer (File > Open, or add it as a
reference/sublayer); with Kit's layer auto-reload on, edits in ParaView show up there.
"""

import os
import re
import time

from paraview import simple
from vtkmodules.vtkCommonCore import vtkCommand

DEFAULT_PATH = os.path.join(os.path.expanduser("~"), "Documents", "DisplayXR-ParaView", "paraview_live.usda")
#: Quiet time before a live re-export, seconds (dragging a slider fires many changes).
SETTLE_S = 0.6

_live = {}
_state = {}


def _log(msg):
    print("[DisplayXR->Omniverse] " + msg)


#: Scene units per metre when written for Kit (cm, Kit's default). ParaView data has no unit.
METERS_PER_UNIT = float(os.environ.get("DXR_PV_USD_METERS_PER_UNIT", "0.01"))


def _kit_layout(stage_path, view, textures):
    """Wrap the exported stage in one root Xform, upright in Kit's default layout (Y-up)
    and with a defaultPrim, so referencing it in USD Composer needs no fix-up: Kit does
    not convert the axis or units of a reference. The up axis is the camera's view-up.

    Also rebases the exporter's absolute prim paths (material bindings, shader
    connections) under the new root, and points texture assets at `textures`
    ({absolute path as written: new relative file name}), so materials survive both the
    wrapping and the move out of the staging folder."""
    up = view.GetActiveCamera().GetViewUp()
    axis = max(range(3), key=lambda i: abs(up[i]))
    sign = 1 if up[axis] > 0 else -1
    # Rotation (degrees about X, Y, Z) taking the scene's up axis to +Y.
    rotate = {0: (0, 0, 90 * sign), 1: (0, 0, 0 if sign > 0 else 180), 2: (-90 * sign, 0, 0)}[axis]
    with open(stage_path, "r", encoding="utf-8") as f:
        text = f.read()
    first, _, body = text.partition("\n")
    body = re.sub(r"</(?!ParaView[/>])", "</ParaView/", body)
    for written, name in textures.items():
        body = body.replace("@" + written + "@", "@./" + name + "@")
    with open(stage_path, "w", encoding="utf-8") as f:
        f.write(first + "\n(\n")
        f.write('    defaultPrim = "ParaView"\n    metersPerUnit = %g\n    upAxis = "Y"\n)\n\n' % METERS_PER_UNIT)
        f.write('def Xform "ParaView"\n{\n')
        f.write("    float3 xformOp:rotateXYZ = (%g, %g, %g)\n" % rotate)
        f.write('    uniform token[] xformOpOrder = ["xformOp:rotateXYZ"]\n')
        f.write(body)
        f.write("\n}\n")


def _replace(src, dst, tries=20):
    """os.replace, retried: a reader (Kit reloading the layer, a virus scanner) can hold
    the target open for a moment without delete sharing."""
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.1)


def send(path=None, view=None):
    """Export the render view's visible scene to USD. Returns the path."""
    path = path or os.environ.get("DXR_PV_USD_PATH") or DEFAULT_PATH
    view = view or simple.GetActiveViewOrCreate("RenderView")
    folder = os.path.dirname(path)
    staging = os.path.join(folder, ".writing")
    os.makedirs(staging, exist_ok=True)
    t0 = time.time()
    # Write next to the target under the same name (texture files are named after the
    # stage), then move textures first and the stage last, each an atomic replace.
    stage_name = os.path.basename(path)
    for f in os.listdir(staging):
        os.remove(os.path.join(staging, f))
    simple.ExportView(os.path.join(staging, stage_name), view=view)
    # Textures get a new name per export: RTX caches textures by path, so a colour-map
    # change written to the same file name may not show.
    # Unique across ParaView restarts too (a counter would reuse names after a restart).
    _state["serial"] = max(_state.get("serial", 0) + 1, int(time.time() * 10))
    textures = {}
    for f in os.listdir(staging):
        if f != stage_name:
            root, ext = os.path.splitext(f)
            new = "%s_%d%s" % (root, _state["serial"], ext)
            os.rename(os.path.join(staging, f), os.path.join(staging, new))
            textures[os.path.join(staging, f).replace("\\", "/")] = new
    if path.endswith(".usda"):
        _kit_layout(os.path.join(staging, stage_name), view, textures)
    for f in textures.values():
        _replace(os.path.join(staging, f), os.path.join(folder, f))
    _replace(os.path.join(staging, stage_name), os.path.join(folder, stage_name))
    # Textures of earlier exports: nothing references them once the new stage is in place.
    prefix = os.path.splitext(stage_name)[0] + "_tex"
    for f in os.listdir(folder):
        if f.startswith(prefix) and f not in textures.values():
            try:
                os.remove(os.path.join(folder, f))
            except OSError:
                pass
    _log("exported %s (%.0f KB, %.2f s)" % (path, os.path.getsize(path) / 1024.0, time.time() - t0))
    return path


def _scene_stamp(view):
    """Changes when what the view shows changes: props, their data, visibility, time."""
    ren = view.GetRenderer()
    props = ren.GetViewProps()
    stamp = [props.GetMTime(), view.ViewTime]
    props.InitTraversal()
    for _ in range(props.GetNumberOfItems()):
        p = props.GetNextProp()
        if not p.GetVisibility():
            continue
        # Not the actor's or mapper's own MTime: rendering touches those every frame.
        if hasattr(p, "GetProperty"):
            stamp.append(p.GetProperty().GetMTime())
        mapper = p.GetMapper() if hasattr(p, "GetMapper") else None
        if mapper is not None:
            stamp.append(mapper.GetScalarVisibility())
            lut = mapper.GetLookupTable()
            stamp.append(lut.GetMTime() if lut is not None else 0)
            inp = mapper.GetInputDataObject(0, 0)
            if inp is not None:
                stamp.append(inp.GetMTime())
    return tuple(stamp)


def live(on=True, path=None):
    """Keep re-exporting the scene to USD while it changes."""
    view = simple.GetActiveViewOrCreate("RenderView")
    iren = view.GetInteractor()
    if not on:
        if _live:
            iren.DestroyTimer(_live["timer"])
            iren.RemoveObserver(_live["observer"])
            _live.clear()
            _log("live export off")
        return
    if _live:
        return
    state = {"path": send(path, view), "stamp": _scene_stamp(view), "changed": None}

    def tick(obj, ev):
        try:
            stamp = _scene_stamp(view)
            now = time.time()
            if stamp != state["stamp"]:
                state["stamp"], state["changed"] = stamp, now
            elif state["changed"] is not None and now - state["changed"] > SETTLE_S:
                state["changed"] = None
                send(state["path"], view)
        except Exception as e:
            _log("live export failed: %r" % (e,))

    _live["observer"] = iren.AddObserver(vtkCommand.TimerEvent, tick)
    _live["timer"] = iren.CreateRepeatingTimer(250)
    _log("live export on -> " + state["path"])


def toggle_live(path=None):
    live(not _live, path)
