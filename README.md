# DisplayXR for ParaView

Glasses-free 3D for [ParaView](https://www.paraview.org) on 3D displays through the
[DisplayXR](https://github.com/DisplayXR) OpenXR runtime (tested on Leia SR).

Press **Start 3D** and ParaView's render view shows in 3D, in place, inside ParaView's
window. The 3D follows ParaView's own camera: rotate, zoom, pick and use widgets with the
mouse as usual, and the panels, pipeline and filters keep working. **Exit 3D** returns to
2D. Other 3D apps (USD Composer, Substance Modeler, Blender, Slicer...) can show 3D in
their own windows at the same time.

## In the browser (ParaView Glance)

ParaView's browser viewer, ParaView Glance, runs in 3D in the DisplayXR Browser: see
[web/README.md](web/README.md).

## Quick start (Windows)

1. ParaView 6.2 (the zip or installer from paraview.org; the default location is
   `%USERPROFILE%\ParaView-6.2.0-Windows-Python3.12-msvc2017-AMD64`, otherwise set `PARAVIEW_HOME`).
2. DisplayXR runtime with its Leia SR plug-in. 3D inside the window and mouse
   pass-through currently need the dev runtime build (see *Runtime* below).
3. Run `Launch-ParaView-DisplayXR.cmd` (demo: flow around a heated disk), or
   `Launch-ParaView-DisplayXR.cmd your.pvsm` for your own state or data.
4. Click **Start 3D** on the Macros toolbar.

Depth stays inside the display's comfort budget as you zoom or change the data: the scene
moves forward or back to fit, and when you zoom into a very deep region the 3D is shown
smaller than the 2D view rather than too strong. Click **Start 3D** again to re-fit the
eye separation to the current view, for
example after zooming far in or out.

The **Depth / Focus** slider at the right end of the menu bar changes the 3D live (the
shared DisplayXR depth slider, which needs the dev runtime's `DXR_HostedDepth`, #2350):

- Depth 100 % means the comfort budget is filled for what's in view. Lower is flatter.
  Higher is capped back to 100 %, so the slider can't make ParaView uncomfortable.
- Focus 0.60 m means ParaView's focal point sits on the glass. Nearer brings it out of
  the screen, farther sinks it in, always within the comfort budget.

## Gamepad

While 3D is active, an Xbox-style pad drives ParaView's camera, the same camera the mouse
uses:

| Pad | |
|---|---|
| left stick | orbit about the focal point |
| right stick | pan |
| right / left trigger | zoom in / out |
| A | reset the camera to the visible data |

The sticks move the scene the way dragging the mouse does. The pad only acts while ParaView
is the foreground window. The launcher turns off DisplayXR's own pad fly camera for
ParaView (`DXR_INPUT_GAMEPAD_NAV=0`), because it would move the 3D away from ParaView's view.

## Omniverse

- **Omniverse Live** writes the render view's visible scene to
  `Documents\DisplayXR-ParaView\paraview_live.usda` with ParaView's own USD exporter, and
  re-exports whenever the visible scene or time changes, until you press it again. No
  NVIDIA connector needed: NVIDIA's ParaView Connector lists ParaView 5.12 only.
  `omniverse_link.send()` does a one-off export.
- The stage is written upright in Kit's default layout (Y-up, cm, one root prim
  `/ParaView` as defaultPrim), so you can reference it in USD Composer as is. Turn on layer
  auto-reload to see ParaView edits live. `DXR_PV_USD_PATH` and
  `DXR_PV_USD_METERS_PER_UNIT` override the path and units.
- ParaView's 3D and USD Composer's 3D viewport (with `displayxr.omniverse`) weave at the
  same time, each in its own window.

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

The overlay window (#2332 / #2350 / #2353) is a stop-gap for testing and measurements.
DisplayXR's direction is *texture mode*: ParaView draws the woven image into its own
render view, so its UI stays on top. Where that isn't possible, the 3D goes in a dedicated
3D window. A shared host library would run the OpenXR session, and this module would
become a thin ParaView adapter: camera pinning, the depth fit and the ParaView UI.

Panel size and viewing distance come from DisplayXR's display info (`displayxr-cli status
--json`). The comfort budget is still a calibrated fraction of panel width, because the
display info has no comfort field yet.

## Files

| File | |
|---|---|
| `Launch-ParaView-DisplayXR.cmd` | launcher: runtime selection, env, macros, follower |
| `python/displayxr_paraview.py` | Start/Exit 3D, camera sync, depth fit |
| `python/gamepad.py` | gamepad navigation of ParaView's camera |
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
