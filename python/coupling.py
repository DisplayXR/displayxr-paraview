"""Everything this integration depends on that DisplayXR or ParaView does not promise.

Each item is "not a contract": an observed behaviour of DisplayXR 2.53 + the dev
runtime (hosted-window embed, DisplayXR #2332) or ParaView 6.2. Re-check after updates.
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess

#: The legacy camera rig's nominal eye in OpenXR STAGE space (qwerty QWERTY_HMD_CAMERA_POS):
#: 1.6 m up, looking down -Z. Measured at runtime when possible (see displayxr_paraview).
RIG_EYE_POSITION = (0.0, 1.6, 0.0)

#: Window property the dev runtime reads (every 250 ms) for the viewer rect of the
#: embedded 3D window: x | y<<16 | w<<32 | h<<48, physical client pixels of the host window.
VIEW_RECT_PROP = "DXR_HostedViewRect"

#: Env var naming the legacy camera profile (inline JSON or a file path). The runtime
#: re-reads the file for every new OpenXR instance, i.e. every Start 3D.
RIG_ENV = "DXR_LEGACY_CAMERA_RIG"

#: Leia demo panel, used when displayxr-cli is unavailable: 34.4 x 21.5 cm, 3840 x 2400 px.
DEFAULT_PANEL = {"width_m": 0.344, "height_m": 0.215, "width_px": 3840, "height_px": 2400}

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32.GetPropW.restype = wt.HANDLE
_user32.GetPropW.argtypes = [wt.HWND, wt.LPCWSTR]
_EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

_panel = None
_status = "3D ready"


def main_window():
    """ParaView's main window: the largest visible, unowned top-level window of this process."""
    pid = os.getpid()
    best = [None, 0]

    def cb(hwnd, _):
        owner_pid = wt.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if owner_pid.value != pid or not _user32.IsWindowVisible(hwnd) or _user32.GetWindow(hwnd, 4):
            return True
        r = wt.RECT()
        _user32.GetClientRect(hwnd, ctypes.byref(r))
        area = r.right * r.bottom
        if area > best[1]:
            best[0], best[1] = hwnd, area
        return True

    _user32.EnumWindows(_EnumProc(cb), 0)
    return best[0]


def read_view_rect():
    """The render view rect published by Follow-ParaView.ps1, or None."""
    hwnd = main_window()
    if not hwnd:
        return None
    v = _user32.GetPropW(hwnd, VIEW_RECT_PROP) or 0
    if not v:
        return None
    return (v & 0xFFFF, (v >> 16) & 0xFFFF, (v >> 32) & 0xFFFF, (v >> 48) & 0xFFFF)


#: Live depth (DisplayXR #2350): strength*1000 | convergence_mm << 16 on the host window,
#: strength relative to the rig the app seeded. The runtime applies the "Rel" value
#: (written by the shared depth slider) and publishes what is in effect as "RelNow".
DEPTH_REL_PROP = "DXR_HostedDepthRel"
DEPTH_REL_NOW_PROP = "DXR_HostedDepthRelNow"
_user32.SetPropW.argtypes = [wt.HWND, wt.LPCWSTR, wt.HANDLE]


def read_depth_rel_now(hwnd):
    """(relative strength, convergence m) the runtime has in effect, or None."""
    v = (_user32.GetPropW(hwnd, DEPTH_REL_NOW_PROP) or 0) if hwnd else 0
    if not v:
        return None
    return (v & 0xFFFF) / 1000.0, ((v >> 16) & 0xFFFF) / 1000.0


def write_depth_rel(hwnd, strength, convergence_m):
    if hwnd:
        v = min(int(round(strength * 1000)), 0xFFFF) | (min(int(round(convergence_m * 1000)), 0xFFFF) << 16)
        _user32.SetPropW(hwnd, DEPTH_REL_PROP, v)


def panel_geometry():
    """Panel size in metres and pixels, from displayxr-cli (cached), else the Leia demo panel."""
    global _panel
    if _panel is None:
        p = dict(DEFAULT_PANEL)
        cli = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "DisplayXR", "Runtime", "displayxr-cli.exe")
        try:
            out = subprocess.run([cli, "status", "--json"], capture_output=True, timeout=5, creationflags=0x08000000).stdout
            screen = json.loads(out)["screens"][0]
            p = {
                "width_m": screen["physical_mm"]["width"] / 1000.0,
                "height_m": screen["physical_mm"]["height"] / 1000.0,
                "width_px": screen["native"]["width"],
                "height_px": screen["native"]["height"],
            }
        except Exception:
            pass
        p["m_per_px"] = p["width_m"] / p["width_px"]
        _panel = p
    return _panel


def write_rig_profile(profile):
    """Write the camera profile the runtime reads at the next OpenXR instance."""
    path = os.environ.get(RIG_ENV, "")
    if not path or path.lstrip().startswith("{"):
        path = os.path.join(os.environ.get("TEMP", "."), "displayxr-paraview-rig.json")
        os.environ[RIG_ENV] = path
        # The runtime DLL has its own CRT; make sure the OS environment block has it too.
        _kernel32.SetEnvironmentVariableW(RIG_ENV, path)
    with open(path, "w") as f:
        json.dump(profile, f)
    return path


def set_status(text):
    global _status
    _status = text


def status():
    return _status


#: OpenXR action manifest: ParaView XRInterface's, minus the actions only its XR menu uses
#: (unused actions make VTK warn into ParaView's output window on every start).
ACTION_MANIFEST = "dxr_openxr_actions.json"


def action_manifest_dir():
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "openxr")
    return d if os.path.exists(os.path.join(d, ACTION_MANIFEST)) else None
