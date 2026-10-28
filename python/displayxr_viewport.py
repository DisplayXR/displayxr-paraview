"""3D in ParaView's own render view: the in-viewport target (texture mode).

No OpenXR render window and no window over ParaView. ParaView renders two
off-axis eyes with its own renderer (plain vtkCameras), the host core
(bin/displayxr_host.dll, the app-neutral core shared with the Slicer,
MotionBuilder, Nuke and Houdini adapters) hands them to the runtime through
XR_DXR_win32_window_binding (runtime v2.55+), and bin/displayxr_paraview_gl.dll
draws the woven frame back into the render view in the last vtkRenderer's
EndEvent, before VTK copies the frame out. ParaView's menus, widgets and mouse
stay its own.

Per tick:
  1. publish the render view's rect (main-window client px) as the target;
  2. hand the core ParaView's camera (pose, view angle, glass, content depth);
  3. if the core located new eyes, render both, read them back and submit;
  4. render once more with ParaView's camera: EndEvent draws the woven frame.

The eye passes call the render window directly: the view's StillRender()
would render the same eye twice.
"""

import ctypes
import math
import os

from vtkmodules.vtkCommonCore import vtkCommand, vtkMath, vtkUnsignedCharArray
from vtkmodules.vtkCommonMath import vtkMatrix4x4
from vtkmodules.vtkRenderingCore import vtkCamera

BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")
HOST_DLL = "displayxr_host.dll"
GL_DLL = "displayxr_paraview_gl.dll"


class _Pose(ctypes.Structure):
    _fields_ = [(n, ctypes.c_float) for n in ("px", "py", "pz", "qx", "qy", "qz", "qw")]


class _Camera(ctypes.Structure):
    _fields_ = [("pose", _Pose), ("vertical_fov", ctypes.c_float), ("glass_distance", ctypes.c_float),
                ("near_z", ctypes.c_float), ("far_z", ctypes.c_float)]


class _Eye(ctypes.Structure):
    _fields_ = [("pose", _Pose)] + [(n, ctypes.c_float) for n in
                                    ("angle_left", "angle_right", "angle_up", "angle_down")]


class _DepthInfo(ctypes.Structure):
    _fields_ = [(n, ctypes.c_float) for n in ("strength", "glass", "front_pct", "behind_pct", "ipd_factor")]


_libs = None


def available():
    """True if the native helpers are built (native/build.bat)."""
    return os.path.exists(os.path.join(BIN, HOST_DLL)) and os.path.exists(os.path.join(BIN, GL_DLL))


def _load():
    global _libs
    if _libs is None:
        os.add_dll_directory(BIN)
        host = ctypes.CDLL(os.path.join(BIN, HOST_DLL))
        gl = ctypes.CDLL(os.path.join(BIN, GL_DLL))
        host.dxrh_start_in_viewport.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 4
        host.dxrh_set_target.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 4
        host.dxrh_set_camera.argtypes = [ctypes.POINTER(_Camera)]
        host.dxrh_set_depth.argtypes = [ctypes.c_float, ctypes.c_int]
        host.dxrh_get_depth.argtypes = [ctypes.POINTER(_DepthInfo)]
        host.dxrh_get_eyes.argtypes = [ctypes.POINTER(_Eye * 2), ctypes.POINTER(ctypes.c_uint32)]
        host.dxrh_submit_rgba8.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [ctypes.c_int] * 3 + [ctypes.c_uint32]
        host.dxrh_status.argtypes = [ctypes.c_char_p, ctypes.c_int]
        gl.dxs_info.argtypes = [ctypes.c_char_p, ctypes.c_int]
        _libs = (host, gl)
    return _libs


def _quat_from_axes(right, up, back):
    """Quaternion (x, y, z, w) of the rotation whose columns are right, up, back."""
    m00, m01, m02 = right[0], up[0], back[0]
    m10, m11, m12 = right[1], up[1], back[1]
    m20, m21, m22 = right[2], up[2], back[2]
    tr = m00 + m11 + m22
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        return ((m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, 0.25 * s)
    if m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2
        return (0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s)
    if m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2
        return ((m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s)
    s = math.sqrt(1.0 + m22 - m00 - m11) * 2
    return ((m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s)


def _axes_from_quat(q):
    """(right, up, back) columns of quaternion q = (x, y, z, w)."""
    x, y, z, w = q
    right = (1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y))
    up = (2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x))
    back = (2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y))
    return right, up, back


def eye_camera(cam, eye, glass):
    """Set vtkCamera `cam` to the core's off-axis eye (world = ParaView's units)."""
    p = eye.pose
    right, up, back = _axes_from_quat((p.qx, p.qy, p.qz, p.qw))
    tl, tr = math.tan(eye.angle_left), math.tan(eye.angle_right)
    tu, td = math.tan(eye.angle_up), math.tan(eye.angle_down)
    cam.SetPosition(p.px, p.py, p.pz)
    d = max(glass, 1e-6)
    cam.SetFocalPoint(p.px - back[0] * d, p.py - back[1] * d, p.pz - back[2] * d)
    cam.SetViewUp(*up)
    cam.SetParallelProjection(False)
    # VTK frustum: y in [(wy-1)t, (wy+1)t], x in [(wx-1)t*aspect, (wx+1)t*aspect],
    # t = tan(viewAngle/2); the explicit projection below then pins the exact tangents.
    cam.SetViewAngle(math.degrees(2.0 * math.atan((tu - td) / 2.0)))
    cam.SetWindowCenter((tr + tl) / (tr - tl), (tu + td) / (tu - td))


def set_exact_frustum(cam, eye):
    """Pin the eye's projection to its exact tangents (VTK otherwise takes the
    width from the render's aspect). Call after the clipping range is set."""
    if not hasattr(cam, "SetExplicitProjectionTransformMatrix"):
        return False
    n, f = cam.GetClippingRange()
    l, r = math.tan(eye.angle_left) * n, math.tan(eye.angle_right) * n
    b, t = math.tan(eye.angle_down) * n, math.tan(eye.angle_up) * n
    m = vtkMatrix4x4()
    m.Zero()
    m.SetElement(0, 0, 2 * n / (r - l))
    m.SetElement(0, 2, (r + l) / (r - l))
    m.SetElement(1, 1, 2 * n / (t - b))
    m.SetElement(1, 2, (t + b) / (t - b))
    m.SetElement(2, 2, -(f + n) / (f - n))
    m.SetElement(2, 3, -2 * f * n / (f - n))
    m.SetElement(3, 2, -1.0)
    cam.SetExplicitProjectionTransformMatrix(m)
    cam.SetUseExplicitProjectionTransformMatrix(True)
    return True


class ViewportSession:
    """One texture-mode 3D session on a ParaView render view."""

    def __init__(self, view, main_hwnd, origin_fn):
        self.host, self.gl = _load()
        self.view = view
        self.main_hwnd = main_hwnd
        self.origin_fn = origin_fn      # () -> (x, y) of the render view, main-window client px, or None
        self.rw = view.GetRenderWindow()
        self.ren = view.GetRenderer()
        self.target = None
        self.serial = 0
        self.pairs = 0
        self.eye_cams = (vtkCamera(), vtkCamera())
        self._in_eyes = False
        self._obs = None
        self._obs_ren = None
        self.glass = 0.0

    # -- lifecycle --------------------------------------------------------
    def rect(self):
        """(x, y, w, h): the render view's position from the follower, its size from VTK,
        so the target is exactly the pixels VTK draws (the weave is phased for them)."""
        origin = self.origin_fn()
        w, h = (int(v) for v in self.rw.GetActualSize())
        if origin is None or w <= 0 or h <= 0:
            return None
        return (origin[0], origin[1], w, h)

    def start(self):
        rect = self.rect()
        if rect is None:
            return "the render view's position on screen isn't known yet (Follow-ParaView.ps1 not running?)"
        self.target = rect
        if self.host.dxrh_start_in_viewport(ctypes.c_void_p(self.main_hwnd), *rect) != 0:
            return self.status()
        self._observe()
        return None

    def stop(self):
        self.host.dxrh_stop()
        # One more render with the observer on releases the GL objects on VTK's context.
        try:
            self.rw.Render()
        except Exception:
            pass
        if self._obs is not None:
            self._obs_ren.RemoveObserver(self._obs)
        self._obs = self._obs_ren = None

    def running(self):
        return bool(self.host.dxrh_is_running())

    def status(self):
        buf = ctypes.create_string_buffer(256)
        self.host.dxrh_status(buf, 256)
        return buf.value.decode("utf-8", "replace")

    def gl_info(self):
        buf = ctypes.create_string_buffer(512)
        self.gl.dxs_info(buf, 512)
        return buf.value.decode("utf-8", "replace")

    def drawn(self):
        return self.gl.dxs_drawn()

    def depth(self):
        d = _DepthInfo()
        self.host.dxrh_get_depth(ctypes.byref(d))
        return d

    def set_depth(self, strength):
        """Depth strength (1.0 = the comfort budget filled). Above 1.0 is an explicit
        opt-in from the user's slider: stronger than the calibrated budget."""
        self.host.dxrh_set_depth(float(strength), 1 if strength > 1.0 else 0)

    # -- per tick ---------------------------------------------------------
    def _last_renderer(self):
        rens = self.rw.GetRenderers()
        last, layer = None, -1
        for i in range(rens.GetNumberOfItems()):
            r = rens.GetItemAsObject(i)
            if r.GetLayer() >= layer:
                last, layer = r, r.GetLayer()
        return last

    def _observe(self):
        ren = self._last_renderer()
        self._obs_ren = ren
        self._obs = ren.AddObserver(vtkCommand.EndEvent, self._on_end)

    def _on_end(self, *_):
        if not self._in_eyes:
            self.gl.dxs_present()

    def content_depth(self, cam):
        """Nearest/farthest visible content along the view direction (world units), or None."""
        b = [0.0] * 6
        self.ren.ComputeVisiblePropBounds(b)
        if b[0] > b[1]:
            return None
        pos, dop = cam.GetPosition(), cam.GetDirectionOfProjection()
        ds = [sum((p[n] - pos[n]) * dop[n] for n in range(3))
              for p in ((b[i], b[j], b[k]) for i in (0, 1) for j in (2, 3) for k in (4, 5))]
        return min(ds), max(ds)

    def set_camera(self, cam, glass, content):
        """ParaView's camera -> the core (pose, framing, glass, depth range)."""
        dop = list(cam.GetDirectionOfProjection())
        up = list(cam.GetViewUp())
        right = [0.0] * 3
        vtkMath.Cross(dop, up, right)
        vtkMath.Normalize(right)
        vtkMath.Cross(right, dop, up)
        vtkMath.Normalize(up)
        q = _quat_from_axes(right, up, [-d for d in dop])
        pos = cam.GetPosition()
        c = _Camera()
        c.pose = _Pose(pos[0], pos[1], pos[2], *q)
        c.vertical_fov = math.radians(cam.GetViewAngle())
        c.glass_distance = glass
        if content:
            c.near_z, c.far_z = max(content[0], glass * 0.01), content[1]
        self.glass = glass
        self.host.dxrh_set_camera(ctypes.byref(c))

    def tick(self, pv_cam):
        """Publish the target, render a new eye pair if the core has new eyes,
        and redraw the view (which draws the woven frame). True if rendered."""
        rect = self.rect()
        if rect is not None and rect != self.target:
            self.target = rect
            self.host.dxrh_set_target(ctypes.c_void_p(self.main_hwnd), *rect)
        eyes = (_Eye * 2)()
        serial = ctypes.c_uint32()
        if not self.host.dxrh_get_eyes(ctypes.byref(eyes), ctypes.byref(serial)):
            return False
        if serial.value == self.serial:
            return False
        self.serial = serial.value
        self._render_pair(eyes, serial.value, pv_cam)
        return True

    def _render_pair(self, eyes, serial, pv_cam):
        import numpy as np
        from vtkmodules.util.numpy_support import vtk_to_numpy
        w, h = (int(v) for v in self.rw.GetActualSize())
        if w <= 0 or h <= 0:
            self.serial = 0
            return
        # Every renderer drawing with ParaView's camera (the main one and the
        # non-composited one for widgets) takes the eye camera.
        rens = self.rw.GetRenderers()
        sharing = [rens.GetItemAsObject(i) for i in range(rens.GetNumberOfItems())
                   if rens.GetItemAsObject(i).GetActiveCamera() is pv_cam]
        imgs = []
        self._in_eyes = True
        try:
            for i in range(2):
                ec = self.eye_cams[i]
                eye_camera(ec, eyes[i], self.glass or pv_cam.GetDistance())
                if hasattr(ec, "SetUseExplicitProjectionTransformMatrix"):
                    ec.SetUseExplicitProjectionTransformMatrix(False)  # clipping range from the plain frustum
                for r in sharing:
                    r.SetActiveCamera(ec)
                self.ren.ResetCameraClippingRange()
                set_exact_frustum(ec, eyes[i])
                self.rw.Render()
                arr = vtkUnsignedCharArray()
                self.rw.GetRGBACharPixelData(0, 0, w - 1, h - 1, 0, arr)
                imgs.append(np.ascontiguousarray(vtk_to_numpy(arr).reshape(h, w, 4)[::-1]))  # top row first
        finally:
            for r in sharing:
                r.SetActiveCamera(pv_cam)
            self.ren.ResetCameraClippingRange()
            self._in_eyes = False
        self.host.dxrh_submit_rgba8(imgs[0].ctypes.data, imgs[1].ctypes.data, w, h, w * 4, serial)
        self.pairs += 1
        self.rw.Render()  # ParaView's own camera; EndEvent draws the woven frame
