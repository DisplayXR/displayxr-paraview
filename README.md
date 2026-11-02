# DisplayXR for ParaView

Glasses-free 3D for [ParaView](https://www.paraview.org) on 3D displays through the
[DisplayXR](https://github.com/DisplayXR) OpenXR runtime (tested on Leia SR).

Press **Start 3D** and ParaView's render view shows in 3D, in place, inside ParaView's
own render view: nothing covers ParaView, so its menus, toolbars and widgets stay on top. The 3D follows ParaView's own camera: rotate, zoom, pick and use widgets with the
mouse as usual, and the panels, pipeline and filters keep working. **Exit 3D** returns to
2D. Other 3D apps (USD Composer, Substance Modeler, Blender, Slicer...) can show 3D in
their own windows at the same time.

> **Preview release (v0.x). Research use only, not for diagnosis.** Research and
> visualization software; not a medical device. The module will move onto the shared
> DisplayXR host library in a later release. No model weights or patient data are bundled.
> Tested on a newer Leia SR runtime; older Leia SR versions are being checked.

## In the browser (ParaView Glance)

ParaView's browser viewer, ParaView Glance, runs in 3D in the DisplayXR Browser: see
[web/README.md](web/README.md).

## Quick start (Windows)

1. ParaView (tested with 6.2), the zip or installer from paraview.org. The launcher uses the
   newest one it finds (see *Launcher options* below).
2. The DisplayXR runtime (v2.55 or later) with its Leia SR plug-in, and PowerShell 7 (`pwsh`).
3. Build the native helpers once: `nativeuild.bat` (Visual Studio 2022, x64 C++; writes
   `pythonin\`). Without them, Start 3D falls back to the OpenXR window (see *Runtime*).
4. Run `Launch-ParaView-DisplayXR.cmd` (demo: flow around a heated disk), or
   `Launch-ParaView-DisplayXR.cmd your.pvsm` for your own state or data.
5. Click **Start 3D** on the Macros toolbar.

### Launcher options

| | |
|---|---|
| default | the **installed** DisplayXR runtime (`%ProgramFiles%\DisplayXR\Runtime`) |
| `--dev` (first argument) or `DXR_RUNTIME=dev` | a dev build of the runtime instead |
| `DXR_DEV_RUNTIME` | the dev build's `DisplayXR_win64.json` (default: a `displayxr-runtime` checkout next to this repo, `..\displayxr-runtime\_package\bin`) |
| `PARAVIEW_EXE` / `PARAVIEW_HOME` | the `paraview.exe` / ParaView install folder to run |
| `DXR_PV_DEPTH` | depth strength at Start 3D: `1.0` (default) fills the comfort budget; e.g. `1.4` for stronger 3D (seated check: "good"), up to `2.0` |
| `DXR_PV_MODE=overlay` | the older OpenXR render window instead of texture mode |

Without `PARAVIEW_EXE` or `PARAVIEW_HOME`, `tools\Find-ParaView.ps1` picks the newest ParaView
in `%ProgramFiles%\ParaView *`, `%LOCALAPPDATA%\Programs\ParaView*`, a zip unpacked as
`%USERPROFILE%\ParaView-*`, or the ParaView installers' uninstall entries; run it on its own to
see which. The runtime is chosen for ParaView only (`XR_RUNTIME_JSON`); the machine's active
OpenXR runtime is left alone. `displayxr-cli` (display info) is the installed one, or the
dev build's with `--dev`.

The launcher runs the helper scripts in this folder (`Install-Macros.ps1`,
`Follow-ParaView.ps1`, `tools\*.ps1`) under PowerShell's own execution policy and never
bypasses it. If you downloaded the repo as a zip, Windows marks the scripts as from the
internet; unblock the folder once with
`Get-ChildItem -Recurse -LiteralPath <folder> | Unblock-File`.

Depth stays inside the display's comfort budget as you zoom or change the data: the scene
moves forward or back to fit, and when you zoom into a very deep region the 3D is shown
smaller than the 2D view rather than too strong. Click **Start 3D** again to re-fit the
eye separation to the current view, for
example after zooming far in or out.

The **Depth / Focus** slider at the right end of the menu bar changes the 3D live (the
shared DisplayXR depth slider, vendored as `tools\DisplayXR-DepthSlider.ps1`):

- Depth 100 % means the comfort budget is filled for what's in view. Lower is flatter.
  The slider stops at 100 %, as in every DisplayXR app; for stronger 3D set `DXR_PV_DEPTH`
  (it applies from Start 3D until the slider is moved).
- Focus 0.60 m puts the screen plane where the visible content fills the in-front and the
  behind budget together. Farther sinks the scene into the screen.

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

**Texture mode (default).** `python/displayxr_viewport.py` renders two off-axis eyes with
ParaView's own renderer (plain `vtkCamera`s with an explicit projection from the runtime's
eye tangents). The host core (`native/core`, the app-neutral core shared with the DisplayXR
adapters for 3D Slicer, MotionBuilder, Nuke and Houdini, built as `pythonin\displayxr_host.dll`)
hands them to the runtime through `XR_DXR_win32_window_binding` and fits the eye
separation to the comfort budget from the screen plane and the visible depth that ParaView
reports each frame. The display's plug-in weaves, and `displayxr_paraview_gl.dll` blits the
woven frame back into the render view in the last `vtkRenderer`'s `EndEvent`, before VTK
copies the frame out (WGL_NV_DX_interop2, one texel per pixel). The eye passes call the
render window directly: the view's `StillRender()` would render the same eye twice.
`Follow-ParaView.ps1` publishes where the render view is in ParaView's window; its size
comes from VTK, so the weave is phased for exactly the pixels VTK draws.

**OpenXR window (`DXR_PV_MODE=overlay`, or without the native helpers).** ParaView ships
VTK's OpenXR module in its Python. `python/displayxr_paraview.py`:

- opens a `vtkOpenXRRenderWindow` that renders in ParaView's own OpenGL context (as a
  helper window) with the render view's props, so nothing is copied or re-loaded;
- drives frames from a Qt timer on the render view's interactor, so ParaView stays
  interactive (no blocking XR loop);
- every frame, sets the physical-to-world matrix from ParaView's camera: the focal region
  sits on the glass, at the size the 2D view shows it, seen from the panel's nominal viewing
  distance (from the display info). Head tracking adds look-around parallax on top;
- fits depth to the display's comfort budget at Start 3D: it slides the glass through the
  scene and sets the eye separation so the nearest point uses the in-front budget
  (0.14 % of panel width) and the farthest the behind budget (0.42 %). The camera rig is
  written to `DXR_LEGACY_CAMERA_RIG`, which DisplayXR reads for each new session.

In this mode DisplayXR runs ParaView as a *hosted legacy* OpenXR app. The runtime's window is embedded
over ParaView's main window. `Follow-ParaView.ps1` publishes the render view's rect
(`DXR_HostedViewRect`) so the 3D covers exactly the render view and follows layout changes.
With `DXR_HOSTED_INPUT=app` the 3D window never takes focus and passes the mouse
to ParaView underneath.

We don't use ParaView's XRInterface "Send to XR". It frames the scene for a standing
headset user (a 1.6 m scene around the viewer), runs a blocking loop, and always starts on
OpenVR.

## Runtime

Texture mode needs the released runtime v2.55 or later (seated-verified on v2.57.1 with the
Leia SR plug-in 2.19.1). The OpenXR-window mode embedded in ParaView's window needs a dev
build:

| Needs | Where |
|---|---|
| 3D inside ParaView's window, `DXR_HostedViewRect` | DisplayXR PR #2332 (draft) |
| Mouse pass-through `DXR_HOSTED_INPUT=app` | branch `hosted/input-passthrough` on #2332 |

Launch with `--dev` (or `DXR_RUNTIME=dev`) to use such a build. With the installed (released)
runtime, the default, the 3D covers the whole panel, but navigation still works from the 2D
view (the 3D follows the camera).

The overlay window (#2332 / #2350 / #2353) is a stop-gap for testing and measurements.
Texture mode is DisplayXR's direction, and the host core in `native/` is the seed of the
shared host library; this module is the thin ParaView adapter around it.

Panel size and viewing distance come from DisplayXR's display info (`displayxr-cli status
--json`; the log notes when it falls back to a default panel). The comfort budget is still a
calibrated fraction of panel width, a named constant, because the display info has no comfort
field yet (DisplayXR runtime issue #2388). Why the 3D lives in ParaView's own window: the
[target classes](https://github.com/DisplayXR/displayxr-runtime/discussions/2331#discussioncomment-19185165)
and the [ParaView proposal](https://github.com/orgs/DisplayXR/discussions/2360).

## Files

| File | |
|---|---|
| `Launch-ParaView-DisplayXR.cmd` | launcher: ParaView and runtime selection, env, macros, follower, slider |
| `python/displayxr_paraview.py` | Start/Exit 3D, camera sync, depth fit |
| `python/gamepad.py` | gamepad navigation of ParaView's camera |
| `python/coupling.py` | every DisplayXR / ParaView internal relied on ("not a contract") |
| `Follow-ParaView.ps1` | publishes the render view rect to the runtime |
| `Install-Macros.ps1` | adds Start 3D / Exit 3D to ParaView's Macros toolbar |
| `tools/Find-ParaView.ps1` | finds the newest ParaView (or `PARAVIEW_EXE` / `PARAVIEW_HOME`) |
| `tools/DisplayXR-DepthSlider.ps1` | Depth / Focus slider, vendored from the shared DisplayXR depth slider (Apache-2.0) |
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
