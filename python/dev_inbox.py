"""Development only (never enabled by the launcher): run .py files dropped into a folder
inside the running ParaView, so a test harness can drive it without UI automation.
Enabled by DXR_PV_DEV_INBOX=<folder>. Output goes to <file>.log next to the script."""

import io
import os
import traceback
from contextlib import redirect_stdout

from paraview import simple
from vtkmodules.vtkCommonCore import vtkCommand

_state = {}


def install(folder):
    os.makedirs(folder, exist_ok=True)
    iren = simple.GetActiveViewOrCreate("RenderView").GetInteractor()

    def poll(obj, ev):
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            src = open(path).read()
            os.remove(path)
            out = io.StringIO()
            try:
                with redirect_stdout(out):
                    exec(compile(src, path, "exec"), {"__name__": "__inbox__"})
            except Exception:
                out.write(traceback.format_exc())
            with open(path[:-3] + ".log", "w") as f:
                f.write(out.getvalue())

    _state["obs"] = iren.AddObserver(vtkCommand.TimerEvent, poll)
    _state["timer"] = iren.CreateRepeatingTimer(500)
