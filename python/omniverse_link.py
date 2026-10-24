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
import time

from paraview import simple
from vtkmodules.vtkCommonCore import vtkCommand

DEFAULT_PATH = os.path.join(os.path.expanduser("~"), "Documents", "DisplayXR-ParaView", "paraview_live.usda")
#: Quiet time before a live re-export, seconds (dragging a slider fires many changes).
SETTLE_S = 0.6

_live = {}


def _log(msg):
    print("[DisplayXR->Omniverse] " + msg)


#: Scene units per metre when written for Kit (cm, Kit's default). ParaView data has no unit.
METERS_PER_UNIT = float(os.environ.get("DXR_PV_USD_METERS_PER_UNIT", "0.01"))


def _kit_layout(stage_path, view):
    """Wrap the exported stage in one root Xform, upright in Kit's default layout (Y-up)
    and with a defaultPrim, so referencing it in USD Composer needs no fix-up: Kit does
    not convert the axis or units of a reference. The up axis is the camera's view-up."""
    up = view.GetActiveCamera().GetViewUp()
    axis = max(range(3), key=lambda i: abs(up[i]))
    sign = 1 if up[axis] > 0 else -1
    # Rotation (degrees about X, Y, Z) taking the scene's up axis to +Y.
    rotate = {0: (0, 0, 90 * sign), 1: (0, 0, 0 if sign > 0 else 180), 2: (-90 * sign, 0, 0)}[axis]
    with open(stage_path, "r", encoding="utf-8") as f:
        text = f.read()
    first, _, body = text.partition("\n")
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
    simple.ExportView(os.path.join(staging, os.path.basename(path)), view=view)
    if path.endswith(".usda"):
        _kit_layout(os.path.join(staging, os.path.basename(path)), view)
    files = sorted(os.listdir(staging), key=lambda f: f == os.path.basename(path))
    for f in files:
        _replace(os.path.join(staging, f), os.path.join(folder, f))
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
