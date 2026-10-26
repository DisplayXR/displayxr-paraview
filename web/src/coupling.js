// Everything this adapter depends on that is NOT a published contract, in one place.
// None of it is a contract: Glance or vtk.js updates may change any of it.

// --- DisplayXR display values -------------------------------------------------------------
// Comfort budget as a fraction of the WHOLE panel's width (PLAYBOOK §3; DisplayXR #2388 asks
// for it in display info). Physical, so a small tile gets a larger share of its own width.
export const COMFORT_FRONT_FRAC = 0.0014; // in front of the glass
export const COMFORT_BEHIND_FRAC = 0.0042; // behind the glass
// The SDK's displayMetrics() fills the panel size from XRDisplayInfo; this is only its fallback.
export const FALLBACK_PANEL_WIDTH_M = 0.344;
export const EYE_SEPARATION_M = 0.063; // the camera rig's ipdFactor unit (63 mm x ipdFactor)

// Depth control: 25 % steps, 100 % = the comfort budget filled for the content in view.
export const DEPTH_STEP = 0.25;
export const DEPTH_MAX = 1.0;

// --- ParaView Glance internals (Glance 4.25.0, shipped in ParaView 6.2 share/paraview-6.2/web/glance)
// `glanceInstance` is a top-level const in Glance's index.html; the module script reads it by name.
export function glanceProxyManager() {
  // eslint-disable-next-line no-undef
  return typeof glanceInstance !== 'undefined' ? glanceInstance.proxyManager : null;
}
// Glance's 3D view proxy is named 'View3D' (the slice views are ViewX / ViewY / ViewZ).
export const GLANCE_3D_VIEW = 'View3D';

// --- vtk.js internals (the version bundled with Glance 4.25) ------------------------------
// view proxy: getRenderer(), getCamera(), getOpenGLRenderWindow()
// OpenGLRenderWindow.traverseAllPasses(): renders every renderer synchronously, without the
//   render-window events (what vtk.js's own WebXR xrRender calls per eye).
// Camera.computeViewParametersFromViewMatrix(colMajorViewMatrix) and
// Camera.setProjectionMatrix(colMajorWebXRProjection | null): what vtk.js's xrRender uses.
export function vtkCanvasOf(view) {
  return view.getOpenGLRenderWindow().getCanvas();
}
export function renderEye(view) {
  view.getOpenGLRenderWindow().traverseAllPasses();
}
