"""Gamepad navigation for ParaView's camera while 3D is active.

The pad drives ParaView's own camera, the one the mouse drives, rather than the XR rig, so
the 2D view, the 3D, the depth fit and the USD export stay on one camera. The launcher
turns the runtime's own pad handling off for ParaView (DXR_INPUT_GAMEPAD_NAV=0,
DXR_INPUT_GAMEPAD_EMULATE_CONTROLLERS=0): its fly camera would move the 3D away from
ParaView's camera, and ParaView's 3D has no use for emulated VR hands.

    left stick      orbit (rotate about the focal point)
    right stick     pan
    (sticks move the scene the way dragging the mouse does in ParaView)
    triggers        zoom: right in, left out
    A               reset the camera to the visible data

Read with XInput, only while ParaView is the foreground window, so a pad used with
another 3D app on the panel doesn't move ParaView too.
"""

import ctypes
import math

DEADZONE = 0.15
ORBIT_DPS = 90.0  # degrees per second at full deflection
PAN_PER_S = 1.0  # view half-heights per second
ZOOM_PER_S = 1.0  # doublings of magnification per second, full trigger
BUTTON_A = 0x1000

_user32 = ctypes.WinDLL("user32")
_xinput = None
for _name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
    try:
        _xinput = ctypes.WinDLL(_name)
        break
    except OSError:
        pass


class _State(ctypes.Structure):
    _fields_ = [
        ("packet", ctypes.c_uint),
        ("buttons", ctypes.c_ushort),
        ("left_trigger", ctypes.c_ubyte),
        ("right_trigger", ctypes.c_ubyte),
        ("lx", ctypes.c_short),
        ("ly", ctypes.c_short),
        ("rx", ctypes.c_short),
        ("ry", ctypes.c_short),
    ]


#: Tests set this to a dict like read() returns, in place of a real pad.
fake = None


def _stick(x, y):
    x, y = x / 32767.0, y / 32767.0
    m = math.hypot(x, y)
    if m < DEADZONE:
        return 0.0, 0.0
    s = min((m - DEADZONE) / (1.0 - DEADZONE), 1.0) / m
    return x * s, y * s


def read():
    """The first connected pad: {lx, ly, rx, ry (-1..1, +y up), lt, rt (0..1), buttons}, or None."""
    if fake is not None:
        return fake
    if _xinput is None:
        return None
    for i in range(4):
        st = _State()
        if _xinput.XInputGetState(i, ctypes.byref(st)) == 0:
            lx, ly = _stick(st.lx, st.ly)
            rx, ry = _stick(st.rx, st.ry)
            return {
                "lx": lx, "ly": ly, "rx": rx, "ry": ry,
                "lt": max(st.left_trigger - 30, 0) / 225.0,
                "rt": max(st.right_trigger - 30, 0) / 225.0,
                "buttons": st.buttons,
            }
    return None


class Navigator:
    """Applies the pad to a ParaView render view's camera; call update() every frame."""

    def __init__(self, view, main_window):
        self.view = view
        self.main_window = main_window
        self.prev_buttons = 0
        self.moving = False

    def _focused(self):
        if fake is not None:
            return True
        fg = _user32.GetForegroundWindow()
        return bool(fg) and _user32.GetAncestor(fg, 2) == self.main_window  # GA_ROOT

    def update(self, dt):
        """Returns True if the camera changed."""
        pad = read() if self._focused() else None
        if pad is None:
            self.prev_buttons = 0
            return self._settle()
        pressed = pad["buttons"] & ~self.prev_buttons
        self.prev_buttons = pad["buttons"]
        cam = self.view.GetActiveCamera()
        changed = False
        if pressed & BUTTON_A:
            self.view.ResetCamera(False)
            changed = True
        dt = min(dt, 0.1)  # no jump after a stall
        if pad["lx"] or pad["ly"]:
            cam.Azimuth(-pad["lx"] * ORBIT_DPS * dt)
            cam.Elevation(pad["ly"] * ORBIT_DPS * dt)
            cam.OrthogonalizeViewUp()
            changed = True
        if pad["rx"] or pad["ry"]:
            half = cam.GetDistance() * math.tan(math.radians(cam.GetViewAngle()) / 2.0)
            if cam.GetParallelProjection():
                half = cam.GetParallelScale()
            dop = cam.GetDirectionOfProjection()
            up = cam.GetViewUp()
            right = (dop[1] * up[2] - dop[2] * up[1], dop[2] * up[0] - dop[0] * up[2], dop[0] * up[1] - dop[1] * up[0])
            step = half * PAN_PER_S * dt
            d = [-(pad["rx"] * right[i] + pad["ry"] * up[i]) * step for i in range(3)]
            fp, pos = cam.GetFocalPoint(), cam.GetPosition()
            cam.SetFocalPoint(*[fp[i] + d[i] for i in range(3)])
            cam.SetPosition(*[pos[i] + d[i] for i in range(3)])
            changed = True
        zoom = pad["rt"] - pad["lt"]
        if zoom:
            f = 2.0 ** (zoom * ZOOM_PER_S * dt)
            if cam.GetParallelProjection():
                cam.SetParallelScale(cam.GetParallelScale() / f)
            else:
                cam.Dolly(f)
            changed = True
        if changed:
            self.moving = True
            self.view.GetRenderer().ResetCameraClippingRange()
            # Keep ParaView's camera properties (and so its 2D view, undo, state files) in step.
            self.view.SMProxy.SynchronizeCameraProperties()
            return True
        return self._settle()

    def _settle(self):
        """After the pad lets go, render the 2D view once so it matches the 3D."""
        if self.moving:
            self.moving = False
            self.view.StillRender()
        return False
