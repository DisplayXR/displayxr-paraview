"""Glasses-free 3D for ParaView on DisplayXR (tested on Leia SR).

ParaView's render view is shown in 3D through DisplayXR's OpenXR runtime, which runs it
as a hosted legacy app embedded in ParaView's window. The 3D follows ParaView's own
camera, so everything that moves the desktop camera (mouse in the view, toolbar view
buttons, Python, animations) moves the 3D too.

    import displayxr_paraview as dxr
    dxr.start()     # "Start 3D"
    dxr.stop()      # "Exit 3D"

What it does differently from ParaView's XRInterface ("Send to XR"):
  - no headset framing: instead of a 1.6 m room-scale scene around a standing user, the
    camera's focal region sits on the glass at the panel's true size and viewing distance
  - depth is fitted to the display's comfort budget (parallax in front / behind the glass)
  - ParaView stays fully interactive: frames are driven from a Qt timer of the render
    view's interactor, not a blocking loop

Runtime internals this relies on are listed in coupling.py ("not a contract").
"""

import math
import os
import time

from paraview import simple
from vtkmodules.vtkCommonCore import vtkCommand, vtkEventDataDevice
from vtkmodules.vtkCommonMath import vtkMatrix4x4
from vtkmodules.vtkRenderingCore import vtkLight
from vtkmodules.vtkRenderingOpenXR import (
    vtkOpenXRCamera,
    vtkOpenXRRenderer,
    vtkOpenXRRenderWindow,
    vtkOpenXRRenderWindowInteractor,
)

import coupling

#: Comfort budget, millimetres of on-screen disparity on the 34.4 cm Leia panel
#: (0.14 % / 0.42 % of its width, calibrated with the user 2026-10-23).
FRONT_BUDGET_MM = 0.14e-2 * 344.0
BEHIND_BUDGET_MM = 0.42e-2 * 344.0
#: Nominal viewer distance from the glass, metres.
VIEWER_DISTANCE_M = 0.6
#: Interpupillary distance the rig's ipdFactor scales, metres.
NOMINAL_IPD_M = 0.063
#: How long between XR frames, ms (the runtime paces the real rate).
FRAME_MS = 11


LOG_PATH = os.path.join(os.environ.get("TEMP", "."), "displayxr-paraview.log")


def _log(msg):
    line = "[DisplayXR] " + msg
    print(line)
    try:
        with open(LOG_PATH, "a") as f:
            f.write(time.strftime("%H:%M:%S ") + line + "\n")
    except OSError:
        pass


def _normalize(v):
    n = math.sqrt(sum(c * c for c in v))
    return [c / n for c in v] if n > 0 else list(v)


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


class _Session:
    def __init__(self, view, depth_strength):
        self.view = view
        self.depth_strength = depth_strength
        self.pv_renderer = view.GetRenderer()
        self.pv_window = view.GetRenderWindow()
        self.pv_interactor = view.GetInteractor()
        self.added_props = []
        self.prop_mtime = 0
        self.timer_id = None
        self.observer = None
        self.window = None
        self.rig = None
        self.eye = coupling.RIG_EYE_POSITION
        self.host = coupling.main_window()
        self.focus_set = False
        self._depth_key = None
        self._depth_range = (0.0, 0.0)
        self.frames = 0
        self.started = time.time()

    # -- rig: the legacy camera DisplayXR gives this app --------------------------------

    def _canvas_metres(self):
        """Physical size of the render view on the panel (the 3D is embedded over it)."""
        panel = coupling.panel_geometry()
        w_px, h_px = self.view.ViewSize
        rect = coupling.read_view_rect()
        if rect is not None:
            w_px, h_px = rect[2], rect[3]
        return w_px * panel["m_per_px"], h_px * panel["m_per_px"]

    def _fit_depth(self):
        """Where the glass sits in the data, and the eye separation, so the data's nearest
        point uses the front budget and its farthest the behind budget."""
        cam = self.pv_renderer.GetActiveCamera()
        dop = _normalize(cam.GetDirectionOfProjection())
        fp = cam.GetFocalPoint()
        dist = cam.GetDistance()
        canvas_w, canvas_h = self._canvas_metres()
        # World units per metre: the desktop framing at the focal point fills the canvas.
        half_world = dist * math.tan(math.radians(cam.GetViewAngle()) / 2.0)
        scale = half_world / (canvas_h / 2.0)

        near_w, far_w = self._view_depths(fp, dop)
        near_m, far_m = (near_w / scale, far_w / scale) if far_w > near_w else (-0.02, 0.02)
        # Never past the viewer: clamp the near side to half the viewing distance.
        near_m = max(near_m, -0.5 * VIEWER_DISTANCE_M)
        far_m = max(far_m, near_m + 1e-4)
        C = VIEWER_DISTANCE_M
        f = FRONT_BUDGET_MM * 1e-3
        g = BEHIND_BUDGET_MM * 1e-3

        def disparity_ratio(shift):
            n, fr = near_m - shift, far_m - shift
            front = max(-n, 0.0) / (C + n)
            behind = max(fr, 0.0) / (C + fr)
            return front, behind

        # Slide the glass through the data until front/behind use their budgets equally.
        lo, hi = near_m, far_m
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            front, behind = disparity_ratio(mid)
            # More of the front budget used than the behind one: move the glass towards the viewer.
            if front * g > behind * f:
                hi = mid
            else:
                lo = mid
        shift = 0.5 * (lo + hi)
        front, behind = disparity_ratio(shift)
        need = max(front / f if front > 0 else 0.0, behind / g if behind > 0 else 0.0)
        baseline = (1.0 / need) if need > 0 else NOMINAL_IPD_M
        ipd_factor = min(1.0, self.depth_strength * baseline / NOMINAL_IPD_M)
        vfov = 2.0 * math.atan(canvas_h / 2.0 / C)

        return {
            "convergenceMeters": C,
            "verticalFov": vfov,
            "ipdFactor": ipd_factor,
            "_scale": scale,
            "_depth_m": [near_m - shift, far_m - shift],
            "_canvas_m": [canvas_w, canvas_h],
        }

    # -- 3D <- ParaView camera ----------------------------------------------------------

    def _sync_camera(self):
        """Map ParaView's camera onto the rig, keeping the scene inside the comfort budget.

        The eye separation is fixed for the session (set at Start 3D), so as the user zooms
        or the data changes, this re-solves every frame where the scene sits: the focal
        point stays on the glass when it can, the scene moves forward or back just enough
        that its nearest point stays within the front budget and its farthest within the
        behind budget, and only when the scene is deeper than the budget allows at the 2D
        view's size is the 3D shown smaller than the 2D view."""
        cam = self.pv_renderer.GetActiveCamera()
        dop = _normalize(cam.GetDirectionOfProjection())
        up = list(cam.GetViewUp())
        up = _normalize([up[i] - _dot(up, dop) * dop[i] for i in range(3)])
        x = _cross(up, [-d for d in dop])
        fp = cam.GetFocalPoint()
        half_world = cam.GetDistance() * math.tan(math.radians(cam.GetViewAngle()) / 2.0)

        # The depth in effect: the shared depth slider (DXR_HostedDepthRel) changes the
        # rig's eye separation and convergence live, in the runtime.
        strength, C = self._live_depth()
        # Rig metres per metre in front of the real panel: the rig's glass is at C, the
        # real one at the viewing distance.
        k = C / VIEWER_DISTANCE_M
        scale = half_world / (self.rig["_canvas_m"][1] / 2.0 * k)
        b = self.rig["ipdFactor"] * NOMINAL_IPD_M * strength
        # Budgets in rig metres; below 100 % the slider scales them, so it scales the depth.
        f = FRONT_BUDGET_MM * 1e-3 * k * min(strength, 1.0)
        g = BEHIND_BUDGET_MM * 1e-3 * k * min(strength, 1.0)
        z_min = b * C / (b + f)  # nearest distance within the front budget
        z_max = b * C / (b - g) if b > g else float("inf")
        near_w, far_w = self._view_depths(fp, dop)
        depth_w = far_w - near_w
        if depth_w / scale > z_max - z_min:
            scale = depth_w / (z_max - z_min)
        # Focus: the slider's distance is where the 2D focal point should appear, in front
        # of the real panel; the default puts it on the glass.
        z_target = k * (C if self.focus_set else VIEWER_DISTANCE_M)
        z_near = min(max(z_target + near_w / scale, z_min), z_max - depth_w / scale)
        z_focal = z_near - near_w / scale

        # The focal point goes straight ahead of the rig's eye, z_focal away.
        eye = self.eye
        p = [eye[0], eye[1], eye[2] - z_focal]
        m = vtkMatrix4x4()
        axes = (x, up, [-d for d in dop])
        for row in range(3):
            for col in range(3):
                m.SetElement(row, col, axes[col][row] * scale)
            # world = S*R*phys + t  with  S*R*p = fp - t
            m.SetElement(row, 3, fp[row] - scale * sum(axes[c][row] * p[c] for c in range(3)))
        self.window.SetPhysicalToWorldMatrix(m)

    def _live_depth(self):
        """(strength relative to the fitted rig, convergence m) in effect, from the runtime's
        DXR_HostedDepthRelNow. Depth above 100 % would exceed the comfort budget: it is
        written back as 100 %, so the shared slider stops at comfort here as everywhere."""
        now = coupling.read_depth_rel_now(self.host)
        if not now:
            self.focus_set = False
            return 1.0, self.rig["convergenceMeters"]
        strength, conv = now
        seeded = self.rig["convergenceMeters"]
        self.focus_set = conv > 0 and abs(conv - seeded) > 1e-3
        if strength > 1.001:
            coupling.write_depth_rel(self.host, 1.0, conv)
            strength = 1.0
        return max(strength, 0.0), conv if conv > 0 else seeded

    def _view_depths(self, fp, dop):
        """Depth range of what the camera actually sees, along the view direction relative to
        the focal point, in world units: a grid over each visible prop's bounds, kept only
        where it falls inside the camera's frustum (zoomed in, most of the data is out of
        view and must not limit the depth). Cached until the camera or the props change."""
        cam = self.pv_renderer.GetActiveCamera()
        key = (cam.GetMTime(), self.pv_renderer.GetViewProps().GetMTime(), self.prop_data_mtime())
        if key == self._depth_key:
            return self._depth_range
        aspect = self.rig["_canvas_m"][0] / self.rig["_canvas_m"][1]
        tan_v = math.tan(math.radians(cam.GetViewAngle()) / 2.0) * 1.05
        tan_h = tan_v * aspect
        pos = cam.GetPosition()
        up = list(cam.GetViewUp())
        up = _normalize([up[i] - _dot(up, dop) * dop[i] for i in range(3)])
        right = _cross(dop, up)
        steps = [i / 4.0 for i in range(5)]
        near, far, all_depths = None, None, []
        for p in self._pv_props():
            if not p.GetVisibility() or not hasattr(p, "GetBounds"):
                continue
            b = p.GetBounds()
            if b is None or b[0] > b[1]:
                continue
            for u in steps:
                for v in steps:
                    for w in steps:
                        q = (b[0] + u * (b[1] - b[0]), b[2] + v * (b[3] - b[2]), b[4] + w * (b[5] - b[4]))
                        rel = [q[n] - pos[n] for n in range(3)]
                        z = _dot(rel, dop)
                        depth = z - cam.GetDistance()
                        all_depths.append(depth)
                        if z <= 0 or abs(_dot(rel, right)) > z * tan_h or abs(_dot(rel, up)) > z * tan_v:
                            continue
                        near = depth if near is None else min(near, depth)
                        far = depth if far is None else max(far, depth)
        if near is None:  # nothing in view: fall back to everything
            near, far = (min(all_depths), max(all_depths)) if all_depths else (0.0, 0.0)
        self._depth_key, self._depth_range = key, (near, far)
        return near, far

    def _pv_props(self):
        props = self.pv_renderer.GetViewProps()
        props.InitTraversal()
        return [props.GetNextProp() for _ in range(props.GetNumberOfItems())]

    def prop_data_mtime(self):
        t = 0
        for p in self._pv_props():
            mapper = p.GetMapper() if hasattr(p, "GetMapper") else None
            inp = mapper.GetInputDataObject(0, 0) if mapper is not None else None
            if inp is not None:
                t = max(t, inp.GetMTime())
        return t

    def _measure_eye(self):
        """Log where the tracked eye is. The mapping keeps the rig's *nominal* eye: the
        runtime anchors the glass to it, and tracked head motion is parallax around it."""
        m = self.window.GetDeviceToPhysicalMatrixForDevice(vtkEventDataDevice.HeadMountedDisplay)
        if m is not None:
            eye = (m.GetElement(0, 3), m.GetElement(1, 3), m.GetElement(2, 3))
            _log("tracked eye at (%.3f, %.3f, %.3f) m; rig eye (%.3f, %.3f, %.3f)" % (eye + tuple(self.eye)))

    # -- props --------------------------------------------------------------------------

    def _update_props(self):
        props = self.pv_renderer.GetViewProps()
        if props.GetMTime() == self.prop_mtime and self.added_props:
            return
        for p in self.added_props:
            self.renderer.RemoveViewProp(p)
        self.added_props = []
        props.InitTraversal()
        for _ in range(props.GetNumberOfItems()):
            p = props.GetNextProp()
            name = p.GetClassName()
            if "WidgetRepresentation" in name or "ImplicitPlaneRepresentation" in name or "QWidget" in name:
                continue
            self.renderer.AddViewProp(p)
            self.added_props.append(p)
        self.prop_mtime = props.GetMTime()

    # -- lifecycle ----------------------------------------------------------------------

    def start(self):
        self.rig = {"_canvas_m": list(self._canvas_metres())}
        self.rig = self._fit_depth()
        coupling.write_rig_profile({k: v for k, v in self.rig.items() if not k.startswith("_")})
        _log(
            "rig: convergence %.2f m, vFOV %.1f deg, ipdFactor %.3f; data %+.1f..%+.1f mm about the glass"
            % (
                self.rig["convergenceMeters"],
                math.degrees(self.rig["verticalFov"]),
                self.rig["ipdFactor"],
                self.rig["_depth_m"][0] * 1000,
                self.rig["_depth_m"][1] * 1000,
            )
        )

        self.window = vtkOpenXRRenderWindow()
        self.window.SetHelperWindow(self.pv_window)
        self.renderer = vtkOpenXRRenderer()
        self.renderer.SetActiveCamera(vtkOpenXRCamera())
        self.renderer.SetShowFloor(False)
        self.renderer.RemoveCuller(self.renderer.GetCullers().GetLastItem())
        self.renderer.SetBackground(self.pv_renderer.GetBackground())
        self.renderer.SetBackground2(self.pv_renderer.GetBackground2())
        self.renderer.SetGradientBackground(self.pv_renderer.GetGradientBackground())
        self.interactor = vtkOpenXRRenderWindowInteractor()
        manifest_dir = coupling.action_manifest_dir()
        if manifest_dir:
            self.interactor.SetActionManifestDirectory(manifest_dir + os.sep)
            self.interactor.SetActionManifestFileName(coupling.ACTION_MANIFEST)
        self.window.SetBaseStationVisibility(False)
        self.window.AddRenderer(self.renderer)
        self.window.SetInteractor(self.interactor)
        for pos, intensity in (((0.0, 1.0, 0.0), 1.0), ((0.8, -0.2, 0.0), 0.8), ((-0.3, -0.2, 0.7), 0.6), ((-0.3, -0.2, -0.7), 0.4)):
            light = vtkLight()
            light.SetPosition(*pos)
            light.SetIntensity(intensity)
            light.SetLightTypeToCameraLight()
            self.renderer.AddLight(light)

        self.window.Initialize()
        if not self.window.GetVRInitialized():
            _log("OpenXR did not start; is DisplayXR the runtime for this process (XR_RUNTIME_JSON)?")
            self.window = None
            return False
        self._update_props()
        self._sync_camera()
        self.observer = self.pv_interactor.AddObserver(vtkCommand.TimerEvent, self._tick)
        self.timer_id = self.pv_interactor.CreateRepeatingTimer(FRAME_MS)
        coupling.set_status("3D active")
        _log("3D active")
        return True

    def _tick(self, obj, event):
        if self.window is None:
            return
        try:
            self._update_props()
            self._sync_camera()
            self.interactor.DoOneEvent(self.window, self.renderer)
            self.frames += 1
            if self.frames == 5:
                self._measure_eye()
            if self.interactor.GetDone():  # session ended in the 3D window (Esc / closed)
                stop()
        except Exception as e:  # never let an exception escape into ParaView's timer
            _log("frame failed: %r" % (e,))
            stop()

    def stop(self):
        if self.timer_id is not None:
            self.pv_interactor.DestroyTimer(self.timer_id)
            self.timer_id = None
        if self.observer is not None:
            self.pv_interactor.RemoveObserver(self.observer)
            self.observer = None
        if self.window is not None:
            for p in self.added_props:
                self.renderer.RemoveViewProp(p)
            self.added_props = []
            self.window.Finalize()
            self.window.SetHelperWindow(None)
            self.window = None
        coupling.set_status("3D ready")
        secs = max(time.time() - self.started, 1e-3)
        _log("Exit 3D after %d frames (%.0f fps)" % (self.frames, self.frames / secs))
        simple.Render(self.view)


_session = None


def start(depth_strength=1.0):
    """Start 3D for the active render view, its depth fitted to the display's comfort budget
    for the current view. While 3D is active, Start 3D again re-fits the depth (after zooming
    a lot, or to another view). depth_strength scales the fitted depth."""
    global _session
    if _session is not None:
        _log("re-fitting depth to the current view")
        stop()
    view = simple.GetActiveViewOrCreate("RenderView")
    simple.Render(view)
    _session = _Session(view, depth_strength)
    if not _session.start():
        _session = None
        return False
    return True


def stop():
    global _session
    if _session is None:
        return
    s, _session = _session, None
    s.stop()


def toggle(depth_strength=1.0):
    if _session is None:
        start(depth_strength)
    else:
        stop()


def active():
    return _session is not None
