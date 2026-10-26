// Minimal Chrome DevTools Protocol driver for checking the page (no dependencies; Node >= 22).
//   node web/tools/cdp.mjs <port> eval "<js expression>"      -> prints the JSON result
//   node web/tools/cdp.mjs <port> console <ms>                 -> prints console lines for <ms>
//   node web/tools/cdp.mjs <port> sbs <out.png>                -> saves the woven canvas's SBS store
//   node web/tools/cdp.mjs <port> shot <out.png>               -> page screenshot (the page's own raster)
import { writeFileSync } from 'node:fs';

const [port, cmd, arg] = process.argv.slice(2);
const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
const page = targets.find((t) => t.type === 'page' && /127\.0\.0\.1:8765/.test(t.url)) || targets.find((t) => t.type === 'page');
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
let id = 0;
const pending = new Map();
ws.addEventListener('message', (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  else if (m.method === 'Runtime.consoleAPICalled') {
    console.log(m.params.type, m.params.args.map((a) => a.value ?? a.description ?? '').join(' '));
  } else if (m.method === 'Runtime.exceptionThrown') {
    console.log('EXC', JSON.stringify(m.params.exceptionDetails).slice(0, 400));
  }
});
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 500));
  return r.result.result.value;
};
if (cmd === 'eval') console.log(JSON.stringify(await evaluate(arg), null, 1));
else if (cmd === 'console') { await send('Runtime.enable'); await new Promise((r) => setTimeout(r, Number(arg) || 3000)); }
else if (cmd === 'sbs') {
  const url = await evaluate('window.__dxrGlance && window.__dxrGlance.sbsDataURL()');
  if (!url) throw new Error('no woven canvas');
  writeFileSync(arg, Buffer.from(url.split(',')[1], 'base64')); console.log('saved', arg);
} else if (cmd === 'shot') {
  const r = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(arg, Buffer.from(r.result.data, 'base64')); console.log('saved', arg);
} else if (cmd === 'drag') {
  // Synthetic page-level drag (CDP input, not the OS cursor): from the woven tile's centre, dx CSS px.
  const r = await evaluate('(()=>{const b=document.querySelectorAll("canvas")[0].getBoundingClientRect();return [b.left+b.width/2,b.top+b.height/2]})()');
  const [x, y] = r, dx = Number(arg) || 150;
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
  for (let i = 1; i <= 10; i++) await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: x + (dx * i) / 10, y, button: 'left', buttons: 1 });
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: x + dx, y, button: 'left', clickCount: 1 });
  console.log('dragged', dx);
} else if (cmd === 'nav') { await send('Page.navigate', { url: arg }); console.log('navigated'); }
ws.close();
process.exit(0);
