# DisplayXR for ParaView

Glasses-free 3D for [ParaView](https://www.paraview.org) on 3D displays through the
[DisplayXR](https://github.com/DisplayXR) OpenXR runtime (tested on Leia SR).

Press **Start 3D** and ParaView's render view shows in 3D, in place, inside ParaView's
window. The 3D follows ParaView's own camera: rotate, zoom, pick and use widgets with the
mouse as usual, and the panels, pipeline and filters keep working. **Exit 3D** returns to
2D. Other 3D apps (USD Composer, Substance Modeler, Blender, Slicer...) can show 3D in
their own windows at the same time.

## Quick start (Windows)

1. ParaView 6.2 (the zip or installer from paraview.org; the default location is
   `%USERPROFILE%\ParaView-6.2.0-Windows-Python3.12-msvc2017-AMD64`, otherwise set `PARAVIEW_HOME`).
2. DisplayXR runtime with its Leia SR plug-in. 3D inside the window and mouse
   pass-through currently need the dev runtime build (see *Runtime* below).
3. Run `Launch-ParaView-DisplayXR.cmd` (demo: flow around a heated disk), or
   `Launch-ParaView-DisplayXR.cmd your.pvsm` for your own state or data.
4. Click **Start 3D** on the Macros toolbar.

Click **Start 3D** again while 3D is active to re-fit the depth to the current view, for
example after zooming far in or out.

## How it works

ParaView ships VTK's OpenXR module in its Python. `python/displayxr_paraview.py`:

- opens a `vtkOpenXRRenderWindow` that renders in ParaView's own OpenGL context (as a
  helper window) with the render view's props, so nothing is copied or re-loaded;
- drives frames from a Qt timer on the render view's interactor, so ParaView stays
  interactive (no blocking XR loop);
- every frame, sets the physical-to-world matrix from ParaView's camera: the focal region
  sits on the glass, at the size the 2D view shows it, seen from the panel's real viewing
  distance (0.6 m). Head tracking adds look-around parallax on top;
- fits depth to the display's comfort budget at Start 3D: it slides the glass through the
  scene and sets the eye separation so the nearest point uses the in-front budget
  (0.14 % of panel width) and the farthest the behind budget (0.42 %). The camera rig is
  written to `DXR_LEGACY_CAMERA_RIG`, which DisplayXR reads for each new session.

DisplayXR runs ParaView as a *hosted legacy* OpenXR app. The runtime's window is embedded
over ParaView's main window. `Follow-ParaView.ps1` publishes the render view's rect
(`DXR_HostedViewRect`) so the 3D covers exactly the render view and follows layout changes.
With `DXR_HOSTED_INPUT=app` the 3D window never takes focus and passes the mouse
to ParaView underneath.

We don't use ParaView's XRInterface "Send to XR". It frames the scene for a standing
headset user (a 1.6 m scene around the viewer), runs a blocking loop, and always starts on
OpenVR.

## Runtime

| Needs | Where |
|---|---|
| 3D inside ParaView's window, `DXR_HostedViewRect` | DisplayXR PR #2332 (draft) |
| Mouse pass-through `DXR_HOSTED_INPUT=app` | branch `hosted/input-passthrough` on #2332 |

With the released runtime, the 3D covers the whole panel, but navigation still works from
the 2D view (the 3D follows the camera).

## Files

| File | |
|---|---|
| `Launch-ParaView-DisplayXR.cmd` | launcher: runtime selection, env, macros, follower |
| `python/displayxr_paraview.py` | Start/Exit 3D, camera sync, depth fit |
| `python/coupling.py` | every DisplayXR / ParaView internal relied on ("not a contract") |
| `Follow-ParaView.ps1` | publishes the render view rect to the runtime |
| `Install-Macros.ps1` | adds Start 3D / Exit 3D to ParaView's Macros toolbar |
| `openxr/` | OpenXR action manifests |
| `startup/demo_disk.py` | demo scene (ParaView's `disk_out_ref.ex2` example) |

## Platforms

- **Windows**: supported (Leia SR is Windows-only).
- **Linux**: DisplayXR on Linux has only a Vulkan compositor, and VTK's OpenXR backend is
  OpenGL only, so this does not run there today. It would need a GL client compositor on
  Linux (GL imports the runtime's Vulkan swapchain images through
  `GL_EXT_memory_object_fd`, as Monado's client GL compositor does) plus a Linux 3D display
  plug-in. ParaView's Linux builds include the OpenXR module.
- **macOS**: DisplayXR has a GL compositor on macOS, but ParaView's macOS builds don't
  include VTK's OpenXR module. It would need a ParaView build with
  `VTK_MODULE_ENABLE_VTK_RenderingOpenXR=YES`. No macOS 3D display plug-in exists yet
  (sim-display only).

## License

Apache-2.0, see `LICENSE` and `NOTICE`.
