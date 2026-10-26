// DisplayXR for ParaView Glance: glasses-free 3D of Glance's 3D view in the DisplayXR Browser.
//
// Glance renders with vtk.js into its own WebGL canvas. This adapter leaves that canvas, its
// mouse interaction and its camera alone, and adds ONE woven canvas on top of it (same box,
// pointer-events: none). Each inline-3D session frame it renders Glance's 3D view once per eye
// (vtk.js's own per-eye path: view matrix + projection from the runtime's views) and copies
// each eye into its half of the woven canvas. Glance's camera is the single source of truth;
// the runtime gets a camera rig pinned to it (attach pattern), with the eye separation fitted
// to the comfort budget for the content in view.
//
// Not a DisplayXR Browser: nothing is added and Glance stays exactly as it was.

import { createInline3D, inline3dViewRigSupported } from '../vendor/inline3d/inline3d.js';
import * as C from './coupling.js';

const LOG = '[DisplayXR Glance]';
const st = {
  wall: null, handle: null, view: null, vtkCanvas: null,
  wc: null, ctx: null, cover: null, bar: null,
  depth: 1.0, // user depth, 0..1 of the budget
  K: 0, g: 1, near: 1, far: 1, ipd: 0, inView: 0,
  tileFrac: 1, metricsAt: 0, woven: null, status: 'starting',
  frames: 0, eyeFrames: 0, lastRange: [0, 0],
  good: [null, null], // copies of the last good eye matrices, for replay
};
window.__dxrGlance = {
  state: () => ({
    status: st.status, woven: st.woven, depth: st.depth, K: st.K, glass: st.g,
    near: st.near, far: st.far, ipdFactor: st.ipd, samplesInView: st.inView,
    tileFrac: st.tileFrac, frames: st.frames, eyeFrames: st.eyeFrames,
    sbs: st.wc ? [st.wc.width, st.wc.height] : null,
    stats: st.handle ? st.handle.stats() : null,
    rigSupported: inline3dViewRigSupported(), eyeX: st.eyeX,
  }),
  setDepth: (d) => setDepth(d),
  // Diagnostic only: replace the runtime's eyes with the camera-rig eyes it would give a viewer at
  // the nominal position (b apart, off-axis frusta converging at the glass). For measuring the
  // depth fit when nobody is in front of the panel (the runtime then returns identical eyes).
  testEyes: (on) => { st.testEyes = !!on; return st.testEyes; },
  sbsDataURL: () => (st.wc ? st.wc.toDataURL('image/png') : null),
};

// ---------------------------------------------------------------- small 4x4 helpers (column-major)
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a) => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
function mul(a, b) {
  const o = new Float64Array(16);
  for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
    let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k]; o[c * 4 + r] = s;
  }
  return o;
}
function rigidInverse(m) { // rotation + translation (the runtime's eye poses are rigid)
  const o = new Float64Array(16);
  for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) o[c * 4 + r] = m[r * 4 + c];
  for (let r = 0; r < 3; r++) o[12 + r] = -(o[r] * m[12] + o[4 + r] * m[13] + o[8 + r] * m[14]);
  o[15] = 1;
  return o;
}

// The mono camera's frame: right, up, -direction of projection, position (camera-to-world).
function cameraFrame(cam) {
  const pos = cam.getPosition(), fp = cam.getFocalPoint();
  const dop = norm(sub(fp, pos));
  const right = norm(cross(dop, cam.getViewUp()));
  const up = cross(right, dop);
  const m = new Float64Array([
    right[0], right[1], right[2], 0, up[0], up[1], up[2], 0,
    -dop[0], -dop[1], -dop[2], 0, pos[0], pos[1], pos[2], 1]);
  return { m, pos, dop, right, up, dist: Math.hypot(...sub(fp, pos)) };
}

// ---------------------------------------------------------------- depth fit (comfort budget)
// Depth range of what the camera SEES: a 5x5x5 grid over the visible prop bounds, kept to the
// points inside the frustum. Then the glass where the front and behind limits meet, and the
// eye separation that fills the budget there: p(z) = K (1 - g/z) of the tile width.
function fitDepth(view, f) {
  const ren = view.getRenderer(), cam = ren.getActiveCamera();
  const b = ren.computeVisiblePropBounds();
  const canvas = st.vtkCanvas;
  const aspect = canvas.width / Math.max(1, canvas.height);
  const tanV = Math.tan((cam.getViewAngle() * Math.PI) / 360), tanH = tanV * aspect;
  let near = Infinity, far = -Infinity, nIn = 0, allNear = Infinity, allFar = -Infinity;
  if (b && b[1] >= b[0]) {
    for (let i = 0; i < 5; i++) for (let j = 0; j < 5; j++) for (let k = 0; k < 5; k++) {
      const p = [b[0] + (b[1] - b[0]) * i / 4, b[2] + (b[3] - b[2]) * j / 4, b[4] + (b[5] - b[4]) * k / 4];
      const d = sub(p, f.pos), z = dot(d, f.dop);
      allNear = Math.min(allNear, z); allFar = Math.max(allFar, z);
      if (z <= 0) continue;
      if (Math.abs(dot(d, f.right)) > z * tanH * 1.05 || Math.abs(dot(d, f.up)) > z * tanV * 1.05) continue;
      near = Math.min(near, z); far = Math.max(far, z); nIn++;
    }
  }
  if (nIn < 2) { near = allNear; far = allFar; }
  if (!isFinite(near) || !isFinite(far)) { near = far = f.dist; }
  near = Math.max(near, f.dist * 0.05); far = Math.max(far, near);
  const F = C.COMFORT_FRONT_FRAC / st.tileFrac, B = C.COMFORT_BEHIND_FRAC / st.tileFrac;
  // Never more separation than true geometry would give (63 mm on the tile's physical width).
  const Kcap = C.EYE_SEPARATION_M / Math.max(0.01, st.tileFrac * st.panelW);
  let g, K;
  if (far / near < 1.0005) { g = near; K = Kcap; } else {
    g = (F + B) / (B / near + F / far);
    K = Math.min(Kcap, F / (g / near - 1));
  }
  return { near, far, g, K, nIn, tanV, aspect };
}

// ---------------------------------------------------------------- per-eye render
function eyeMatrices(f, view) {
  const L = view.transform.matrix; // eye pose in rig space (identity rig = Glance's camera)
  const E = mul(f.m, L);
  return { V: rigidInverse(E), P: Float64Array.from(view.projectionMatrix) };
}

function syntheticEyes(f, fit, Wg, n, far) {
  const b = st.K * Wg, h = st.g * fit.tanV, w = h * fit.aspect;
  return [-1, 1].map((sgn) => {
    const ex = (sgn * b) / 2;
    const L = new Float64Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, ex, 0, 0, 1]);
    const l = ((-w - ex) * n) / st.g, r = ((w - ex) * n) / st.g, bt = (-h * n) / st.g, tp = (h * n) / st.g;
    const P = new Float64Array(16);
    P[0] = (2 * n) / (r - l); P[5] = (2 * n) / (tp - bt); P[8] = (r + l) / (r - l); P[9] = (tp + bt) / (tp - bt);
    P[10] = -(far + n) / (far - n); P[11] = -1; P[14] = (-2 * far * n) / (far - n);
    return { V: rigidInverse(mul(f.m, L)), P };
  });
}

function renderEyes(eyes, vps) {
  const cam = st.view.getCamera();
  const saved = { p: cam.getPosition().slice(), f: cam.getFocalPoint().slice(), u: cam.getViewUp().slice(),
    ps: cam.getPhysicalScale() };
  // vtk.js divides an explicit projection by the camera's physicalScale (meant for its own XR
  // physical space); Glance's resetCamera sets it from the data size. Our views are in world units.
  if (saved.ps !== 1) cam.setPhysicalScale(1);
  const W = st.vtkCanvas.width, H = st.vtkCanvas.height;
  try {
    for (let i = 0; i < 2; i++) {
      cam.computeViewParametersFromViewMatrix(eyes[i].V);
      cam.setProjectionMatrix(eyes[i].P);
      C.renderEye(st.view);
      const vp = vps[i];
      const y0 = st.wc.height - vp.y - vp.height;
      paintBackground(vp.x, y0, vp.width, vp.height);
      st.ctx.drawImage(st.vtkCanvas, 0, 0, W, H, vp.x, st.wc.height - vp.y - vp.height, vp.width, vp.height);
      if (i === 0 && st.cover && !st.cover.hidden) {
        const cc = st.cover.getContext('2d');
        if (st.cover.width !== W || st.cover.height !== H) { st.cover.width = W; st.cover.height = H; }
        cc.drawImage(st.vtkCanvas, 0, 0);
      }
    }
    st.eyeFrames++;
  } finally {
    cam.setProjectionMatrix(null);
    if (saved.ps !== 1) cam.setPhysicalScale(saved.ps);
    cam.setPosition(...saved.p); cam.setFocalPoint(...saved.f); cam.setViewUp(...saved.u);
  }
}

// Glance draws its view background (a CSS gradient) BEHIND a transparent WebGL canvas, so the
// eye images carry no background: paint the page's own background under each eye.
let bgCache = { at: 0, stops: ['#000'] };
function backgroundStops() {
  if (Date.now() - bgCache.at < 1000) return bgCache.stops;
  let stops = ['#000'];
  for (let e = st.vtkCanvas; e; e = e.parentElement) {
    const cs = getComputedStyle(e);
    const m = cs.backgroundImage.startsWith('linear-gradient') && cs.backgroundImage.match(/rgba?\([^)]*\)/g);
    if (m && m.length) { stops = m; break; }
    if (cs.backgroundColor && !/rgba\(0, 0, 0, 0\)|transparent/.test(cs.backgroundColor)) { stops = [cs.backgroundColor]; break; }
  }
  bgCache = { at: Date.now(), stops };
  return stops;
}
function paintBackground(x, y, w, h) {
  const stops = backgroundStops();
  if (stops.length === 1) { st.ctx.fillStyle = stops[0]; } else {
    const g = st.ctx.createLinearGradient(0, y, 0, y + h); // CSS default: to bottom
    stops.forEach((c, i) => g.addColorStop(i / (stops.length - 1), c));
    st.ctx.fillStyle = g;
  }
  st.ctx.fillRect(x, y, w, h);
}

// ---------------------------------------------------------------- layout: woven canvas over Glance's
function syncBox() {
  const c = st.vtkCanvas, parent = c.parentElement;
  if (!parent) return;
  for (const el of [st.wc, st.cover, st.bar]) if (el && el.parentElement !== parent) parent.appendChild(el);
  if (getComputedStyle(parent).position === 'static') parent.style.position = 'relative';
  const pr = parent.getBoundingClientRect(), r = c.getBoundingClientRect();
  for (const el of [st.wc, st.cover]) {
    const s = el.style, l = `${r.left - pr.left + parent.scrollLeft}px`, t = `${r.top - pr.top + parent.scrollTop}px`;
    if (s.left !== l) s.left = l; if (s.top !== t) s.top = t;
    if (s.width !== `${r.width}px`) s.width = `${r.width}px`;
    if (s.height !== `${r.height}px`) s.height = `${r.height}px`;
  }
  const W = c.width, H = c.height;
  if (st.wc.width !== 2 * W || st.wc.height !== H) {
    st.wc.width = 2 * W; st.wc.height = H; // SBS store: two full-resolution eyes
    st.metricsAt = 0; // re-read the tile's physical size
  }
}

function makeCanvas(z) {
  const el = document.createElement('canvas');
  Object.assign(el.style, { position: 'absolute', pointerEvents: 'none', zIndex: String(z), display: 'block',
    willChange: 'transform' }); // rule 4: from the first paint
  return el;
}

// ---------------------------------------------------------------- UI: status + depth control
function makeBar() {
  const bar = document.createElement('div');
  bar.setAttribute('data-inline3d-overlay', ''); // legacy browsers; inert on draw-order browsers
  Object.assign(bar.style, {
    position: 'absolute', left: '72px', bottom: '8px', zIndex: '3', display: 'flex', gap: '6px',
    alignItems: 'center', padding: '4px 8px', borderRadius: '6px', background: 'rgba(18,18,18,0.88)',
    color: '#f4f4f4', font: '600 16px/1.2 system-ui, sans-serif', userSelect: 'none',
  });
  const label = document.createElement('span');
  const depth = document.createElement('span');
  depth.style.minWidth = '7.5em';
  const btn = (txt, title, fn) => {
    const b = document.createElement('button');
    b.textContent = txt; b.title = title;
    Object.assign(b.style, { font: 'inherit', color: '#fff', background: '#3a3a3a', border: '0',
      borderRadius: '4px', minWidth: '30px', height: '28px', cursor: 'pointer' });
    b.addEventListener('click', (e) => { e.stopPropagation(); fn(); });
    return b;
  };
  bar.append(label, depth,
    btn('−', 'Less depth', () => setDepth(st.depth - C.DEPTH_STEP)),
    btn('+', 'More depth (100 % = comfort budget)', () => setDepth(st.depth + C.DEPTH_STEP)),
    btn('Reset', 'Depth back to 100 %', () => setDepth(C.DEPTH_MAX)));
  bar._label = label; bar._depth = depth;
  return bar;
}
function setDepth(d) {
  st.depth = Math.min(C.DEPTH_MAX, Math.max(0, Math.round(d / C.DEPTH_STEP) * C.DEPTH_STEP));
  updateBar();
  return st.depth;
}
function updateBar() {
  if (!st.bar) return;
  const txt = { starting: '3D starting…', active: '3D active', paused: '3D paused', off: '3D unavailable' };
  st.bar._label.textContent = txt[st.status] || st.status;
  st.bar._depth.textContent = `Depth ${Math.round(st.depth * 100)} %`;
}

// ---------------------------------------------------------------- frame
function onFrame(views, layer) {
  st.frames++;
  if (!st.view || !st.vtkCanvas.isConnected) return;
  syncBox();
  const cam = st.view.getCamera();
  const f = cameraFrame(cam);
  const fit = fitDepth(st.view, f);
  // Ease toward the target; never above it (the budget is a ceiling).
  const Kt = fit.K * st.depth;
  st.K = Kt < st.K ? Kt : st.K + (Kt - st.K) * 0.15;
  st.g = st.g + (fit.g - st.g) * (Math.abs(fit.g - st.g) / fit.g > 0.5 ? 1 : 0.25);
  st.near = fit.near; st.far = fit.far; st.inView = fit.nIn;
  const Wg = 2 * st.g * fit.tanV * fit.aspect; // view width at the glass, world units
  st.ipd = (st.K * Wg) / C.EYE_SEPARATION_M;
  // The rig drives the NEXT locate: push it before any early return.
  st.handle.setViewRig({
    type: 'camera', position: { x: 0, y: 0, z: 0 }, orientation: { x: 0, y: 0, z: 0, w: 1 },
    verticalFov: (cam.getViewAngle() * Math.PI) / 180, convergenceDiopters: 1 / st.g,
    ipdFactor: st.ipd, parallaxFactor: st.ipd, metersToVirtual: 1,
  });
  // Session depth range from Glance's own clipping range (the eyes' projections use it).
  const cr = cam.getClippingRange();
  const dn = cr[0] * 0.8, df = cr[1] * 1.25;
  if (Math.abs(dn - st.lastRange[0]) > dn * 0.05 || Math.abs(df - st.lastRange[1]) > df * 0.05) {
    try { st.wall.session.updateRenderState({ depthNear: dn, depthFar: df }); st.lastRange = [dn, df]; } catch { /* ending */ }
  }
  // Validate before drawing; replay the last good eyes on a short frame (never skip a frame).
  let eyes = null, vps = null;
  if (views && views.length >= 2 && layer) {
    vps = views.slice(0, 2).map((v) => layer.getViewport(v));
    if (vps.every((vp) => vp && vp.width > 0 && vp.height > 0)) {
      eyes = st.testEyes ? syntheticEyes(f, fit, Wg, dn, df) : views.slice(0, 2).map((v) => eyeMatrices(f, v));
      st.eyeX = views.slice(0, 2).map((v) => v.transform.matrix[12]); // rig-space eye x (diagnostic)
      st.good = eyes.map((e, i) => ({ L: Float64Array.from(views[i].transform.matrix), P: e.P, vp: { ...vps[i] } }));
    }
  }
  if (!eyes) {
    if (!st.good[0]) { st.ctx.fillStyle = '#000'; st.ctx.fillRect(0, 0, st.wc.width, st.wc.height); return; }
    eyes = st.good.map((g) => ({ V: rigidInverse(mul(f.m, g.L)), P: g.P }));
    vps = st.good.map((g) => g.vp);
  }
  renderEyes(eyes, vps);
  if (Date.now() - st.metricsAt > 2000) refreshMetrics();
}

async function refreshMetrics() {
  st.metricsAt = Date.now();
  try {
    const m = await st.handle.displayMetrics();
    st.panelW = m.displaySizeM[0] || C.FALLBACK_PANEL_WIDTH_M;
    st.tileFrac = Math.min(1, Math.max(0.05, m.canvasSizeM[0] / st.panelW));
  } catch { /* keep the last */ }
}

// ---------------------------------------------------------------- attach to Glance's 3D view
async function attach(view) {
  st.view = view;
  st.vtkCanvas = C.vtkCanvasOf(view);
  st.panelW = C.FALLBACK_PANEL_WIDTH_M;
  st.wc = makeCanvas(1);
  st.ctx = st.wc.getContext('2d', { alpha: false });
  st.cover = makeCanvas(2); // rule 5: the mono picture over the woven canvas until it is woven
  st.bar = makeBar();
  syncBox();
  st.ctx.fillStyle = '#000'; st.ctx.fillRect(0, 0, st.wc.width, st.wc.height);
  updateBar();
  // Rule 4: commit the canvas before registering it.
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  st.handle = st.wall.addScene(st.wc, onFrame, {
    bufferClamped: true, rectCover: 'auto',
    viewRig: { type: 'camera', convergenceDiopters: 1, verticalFov: 0.5, ipdFactor: 0, parallaxFactor: 0 },
    onLayerLost: () => { st.status = 'paused'; st.wc.hidden = true; st.cover.hidden = true; updateBar(); },
  });
  refreshMetrics();
  const r = await st.handle.firstWoven;
  st.woven = r;
  st.cover.hidden = true; // hard cut
  if (r.woven) { st.status = 'active'; } else { st.status = 'off'; st.wc.hidden = true; }
  console.log(LOG, `firstWoven: woven=${r.woven} confirmed=${r.confirmed} reason=${r.reason} ${Math.round(r.ms)} ms`);
  updateBar();
}

async function main() {
  // ?dxr=off: plain Glance (to compare with the browser's own auto-3D, or to opt out).
  if (new URLSearchParams(location.search).get('dxr') === 'off') { console.log(LOG, 'off (?dxr=off)'); return; }
  // One inline-3D session per document (rule 1). Not a DisplayXR Browser: Glance stays 2D.
  const wall = await createInline3D({ lazy: false });
  if (!wall.supported) { console.log(LOG, 'no inline-3D session: Glance stays 2D'); return; }
  st.wall = wall;
  console.log(LOG, `inline-3D session up; camera rigs ${inline3dViewRigSupported() ? 'supported' : 'NOT supported'}`);
  // Glance creates its 3D view once data is loaded; wait for it.
  const poll = setInterval(() => {
    const pm = C.glanceProxyManager();
    if (!pm || st.view) return;
    const v = pm.getViews().find((x) => x.getProxyName && x.getProxyName() === C.GLANCE_3D_VIEW);
    if (v && C.vtkCanvasOf(v) && C.vtkCanvasOf(v).isConnected && C.vtkCanvasOf(v).width > 0) {
      clearInterval(poll);
      attach(v).catch((e) => console.warn(LOG, 'attach failed', e));
    }
  }, 300);
}

main().catch((e) => console.warn(LOG, e));
