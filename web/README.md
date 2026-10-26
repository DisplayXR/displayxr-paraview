# ParaView Glance in the DisplayXR Browser

ParaView's browser viewer, **ParaView Glance** (shipped with ParaView in
`share/paraview-<ver>/web/glance`), shown in glasses-free 3D in the DisplayXR Browser. The 3D
stays in Glance's 3D view, inside the page, next to anything else that is 3D on the panel.

## Quick start (Windows)

1. ParaView 6.2 (for its Glance copy and `pvpython`), Python 3, the DisplayXR Browser.
2. `web\Launch-Glance-DisplayXR.cmd` (demo: flow around a heated disk), or
   `web\Launch-Glance-DisplayXR.cmd depth_spheres.vtp`. Any file Glance opens (Open button,
   drag and drop) works the same way.
3. The bar at the bottom of the 3D view reads **3D active**. **−** / **+** change the depth in
   25 % steps, **Reset** goes back to 100 %. 100 % is the display's comfort budget filled for
   what is in view; there is no setting above it.

On any other browser Glance is unchanged (2D). `?dxr=off` in the URL turns the adapter off.

## How it works

- Glance renders with vtk.js into its own WebGL canvas. The adapter (`src/displayxr-glance.js`)
  leaves that canvas, Glance's camera and its mouse handling alone. It puts one woven canvas
  (inline-3D, `@displayxr/inline3d` 1.46.0, vendored in `vendor/inline3d`) over the 3D view,
  with `pointer-events: none`, so the mouse still reaches Glance.
- Each inline-3D frame it renders Glance's 3D view once per eye through vtk.js's own per-eye
  path (`computeViewParametersFromViewMatrix` + `setProjectionMatrix`, as vtk.js's WebXR code
  does) and copies each eye into its half of the woven canvas. Glance's CSS view background is
  painted under each eye.
- The runtime gets a **camera rig pinned to Glance's camera** (attach pattern: identity rig pose,
  eyes composed with the current camera). The glass and eye separation come from the depth of
  what the camera sees (a 5×5×5 grid over the visible bounds, kept to the frustum): the glass
  where the front and behind limits meet, the separation that fills the budget,
  0.14 % in front / 0.42 % behind of the **panel** width (`src/coupling.js`).
- Everything that is not a contract (Glance's `glanceInstance` global, the `View3D` proxy name,
  vtk.js camera internals such as `physicalScale`) is in `src/coupling.js`.

## Checks

`tools/cdp.mjs` drives a browser started with `--remote-debugging-port`:
`eval "window.__dxrGlance.state()"` (status, `firstWoven`, glass, K, frame stats),
`sbs out.png` (the side-by-side store that is woven), `drag 200` (a synthetic page drag).
`window.__dxrGlance.testEyes(true)` swaps the runtime's eyes for the camera-rig eyes a nominal
viewer would get, for measuring the depth fit when nobody sits at the panel (the runtime then
returns identical eyes). `tools/make_data.py` (pvpython) writes the demo and test datasets.

## Licences

This folder: Apache-2.0 (see the repo's LICENSE / NOTICE). `vendor/inline3d`: Apache-2.0, the
DisplayXR project. ParaView Glance is not included; `serve.py` copies it from your ParaView
install (BSD-3-Clause, Kitware).
