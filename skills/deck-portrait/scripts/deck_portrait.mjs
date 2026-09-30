#!/usr/bin/env node
// 横屏 HTML deck → 竖屏 PNG（默认 1080×1440，3:4）。
// 零依赖：Node ≥ 22（内置 WebSocket）+ 本机 Chrome，走 DevTools 协议。
//
// 用法:
//   deck_portrait.mjs <deck.html> [--out DIR] [--pages 1-9,12] [--size 1080x1440] [--scale 2]
//                     [--config portrait.json] [--min-zoom 0.75] [--chrome PATH]
//                     [--no-crops] [--max-crops 2] [--crop-below 16] [--crop-target 20]
//                     [--debug N]   只打印第 N 页每张图的裁边范围、候选空隙和图内字号
// 图一律整张保留原结构；图内字太小时，在该页后面追加同一张图的局部放大页（slide-NNb、NNc…）。
// 产物:  DIR/slide-NN.png、DIR/contact.png（缩略图总览）、DIR/report.json（每页的缩放、放大页、字号）
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fs.realpathSync(fileURLToPath(import.meta.url)));
const argv = process.argv.slice(2);
const flag = (name, def) => { const i = argv.indexOf(name); if (i < 0) return def; const v = argv[i + 1]; argv.splice(i, 2); return v; };
const bool = name => { const i = argv.indexOf(name); if (i < 0) return false; argv.splice(i, 1); return true; };
if (argv.includes('-h') || argv.includes('--help') || !argv.length) {
  const src = fs.readFileSync(fileURLToPath(import.meta.url), 'utf8').split('\n').slice(1);
  console.log(src.slice(0, src.findIndex(l => !l.startsWith('//'))).map(l => l.replace(/^\/\/ ?/, '')).join('\n'));
  process.exit(0);
}
const outArg = flag('--out'), pagesArg = flag('--pages'), sizeArg = flag('--size', '1080x1440');
const scale = parseFloat(flag('--scale', '2')), minZoom = parseFloat(flag('--min-zoom', '0.75'));
const configArg = flag('--config'), chromeArg = flag('--chrome');
const noCrops = bool('--no-crops');
const cropBelow = parseFloat(flag('--crop-below', '16')), cropTarget = parseFloat(flag('--crop-target', '20'));
const maxCrops = parseInt(flag('--max-crops', '2'), 10);
const debugPage = flag('--debug');
const deck = path.resolve(argv[0] || '');
if (!fs.existsSync(deck)) { console.error(`找不到 deck：${deck}`); process.exit(2); }
const [W, H] = sizeArg.split('x').map(Number);
const outDir = path.resolve(outArg || path.join(path.dirname(deck), 'portrait'));
fs.mkdirSync(outDir, { recursive: true });

const cfgPath = configArg ? path.resolve(configArg) : path.join(path.dirname(deck), 'portrait.json');
const cfg = fs.existsSync(cfgPath) ? JSON.parse(fs.readFileSync(cfgPath, 'utf8')) : {};
if (fs.existsSync(cfgPath)) console.log(`配置：${cfgPath}`);

const CHROMES = [chromeArg, process.env.CHROME,
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
  '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser'];
const chrome = CHROMES.find(c => c && fs.existsSync(c));
if (!chrome) { console.error('找不到 Chrome，用 --chrome 或 CHROME 环境变量指定路径'); process.exit(2); }

function parsePages(spec, n) {
  if (!spec) return [...Array(n).keys()];
  const s = new Set();
  for (const part of String(spec).split(',')) {
    const [a, b] = part.split('-').map(x => parseInt(x, 10));
    for (let k = a; k <= (isNaN(b) ? a : b); k++) if (k >= 1 && k <= n) s.add(k - 1);
  }
  return [...s].sort((x, y) => x - y);
}

// ---------- 启动 Chrome + CDP ----------
const udd = fs.mkdtempSync(path.join(os.tmpdir(), 'deck-portrait-'));
const proc = spawn(chrome, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${udd}`,
  '--allow-file-access-from-files', '--hide-scrollbars', '--no-first-run', '--no-default-browser-check',
  '--mute-audio', '--disable-gpu', 'about:blank'], { stdio: 'ignore' });
const cleanup = () => { try { proc.kill(); } catch (e) {} try { fs.rmSync(udd, { recursive: true, force: true }); } catch (e) {} };
process.on('exit', cleanup);
process.on('SIGINT', () => process.exit(130));

const sleep = ms => new Promise(r => setTimeout(r, ms));
async function devtoolsPort() {
  const f = path.join(udd, 'DevToolsActivePort');
  for (let k = 0; k < 100; k++) { if (fs.existsSync(f)) { const p = fs.readFileSync(f, 'utf8').split('\n')[0]; if (p) return p; } await sleep(100); }
  throw new Error('Chrome 没有启动 DevTools 端口');
}
const port = await devtoolsPort();
const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page = targets.find(t => t.type === 'page');
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let seq = 0; const pending = new Map(), waiters = [];
ws.onmessage = ev => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { const { res, rej } = pending.get(m.id); pending.delete(m.id); m.error ? rej(new Error(m.error.message)) : res(m.result); }
  else if (m.method) for (const w of [...waiters]) if (w.method === m.method) { waiters.splice(waiters.indexOf(w), 1); w.res(m.params); }
};
const send = (method, params = {}) => new Promise((res, rej) => { const id = ++seq; pending.set(id, { res, rej }); ws.send(JSON.stringify({ id, method, params })); });
const once = method => new Promise(res => waiters.push({ method, res }));
async function evaluate(expr) {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
  return r.result.value;
}

await send('Page.enable'); await send('Runtime.enable');
await send('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: scale, mobile: false });
const loaded = once('Page.loadEventFired');
await send('Page.navigate', { url: pathToFileURL(deck).href + '#1' });
await loaded;
await evaluate('document.fonts.ready.then(() => 1)');

const css = fs.readFileSync(path.join(HERE, 'portrait.css'), 'utf8');
const js = fs.readFileSync(path.join(HERE, 'portrait.js'), 'utf8')
  .replace('__PT_CSS__', JSON.stringify(css)).replace('__PT_W__', String(W)).replace('__PT_H__', String(H));
await evaluate(js);
const { count } = await evaluate('window.__pt.info()');
if (debugPage) {
  console.log(JSON.stringify(await evaluate(`window.__pt.debug(${parseInt(debugPage, 10) - 1})`), null, 1));
  process.exit(0);
}
const pages = parsePages(pagesArg || cfg.pages, count);
console.log(`${path.basename(deck)}：共 ${count} 页，导出 ${pages.length} 页 → ${outDir}  (${W}×${H} ×${scale})`);

// ---------- 逐页渲染 ----------
const report = [];
const pad2 = n => String(n).padStart(2, '0');
const opts = { minZoom, autoCrops: !noCrops && maxCrops >= 2, maxCrops, cropBelow, cropTarget };
for (const i of pages) {
  const ov = (cfg.slides || {})[String(i + 1)] || {};
  for (const f of fs.readdirSync(outDir)) if (new RegExp(`^slide-${pad2(i + 1)}[a-z]?\\.png$`).test(f)) fs.rmSync(path.join(outDir, f));
  for (let part = 0, parts = 1; part < parts; part++) {
    const r = await evaluate(`window.__pt.render(${i}, ${JSON.stringify(ov)}, ${JSON.stringify(opts)}, ${part})`);
    parts = r.parts;
    const shot = await send('Page.captureScreenshot', { format: 'png', clip: { x: 0, y: 0, width: W, height: H, scale: 1 } });
    const suffix = parts > 1 ? String.fromCharCode(97 + part) : '';
    const file = path.join(outDir, `slide-${pad2(i + 1)}${suffix}.png`);
    fs.writeFileSync(file, Buffer.from(shot.data, 'base64'));
    r.file = path.basename(file);
    const flags = [];
    if (r.overflow.length) flags.push('溢出');
    if (r.zoom < 1) flags.push(`缩到${r.zoom}`);
    if (r.text.p10 !== null && r.text.p10 < 20 && !(parts > 1 && part === 0)) flags.push(`小字 p10=${r.text.p10}px`);   // 总览页的小字由后面的放大页兜底
    if (parts > 1 && part === 0) { const b = r.blocks.find(x => x.crops); flags.push(`追加${parts - 1}张局部放大(×${b ? b.zoomGain : '?'})`); }
    if (part > 0) flags.push(`局部放大 ${part}/${parts - 1}`);
    r.flags = flags;
    report.push(r);
    console.log(`${r.file.replace('slide-', '').replace('.png', '').padEnd(4)} ${(r.title || '').slice(0, 20).padEnd(20, '　')}  ${flags.join(' · ') || 'ok'}`);
  }
}
fs.writeFileSync(path.join(outDir, 'report.json'), JSON.stringify(report, null, 2));

// ---------- 缩略图总览 ----------
const cols = 6, tw = 300, th = Math.round(tw * H / W);
const cells = report.map(r => `<figure><img src="${r.file}"><figcaption><b>${r.file.replace('slide-', '').replace('.png', '')}</b> ${r.flags.map(f => `<i>${f}</i>`).join(' ')}</figcaption></figure>`).join('');
const html = `<!doctype html><meta charset="utf-8"><style>
body{margin:0;background:#C8CDD4;font:13px -apple-system,"PingFang SC",sans-serif}
main{display:grid;grid-template-columns:repeat(${cols},${tw}px);gap:14px;padding:14px}
figure{margin:0} img{width:${tw}px;height:${th}px;display:block;background:#fff}
figcaption{padding:4px 2px;color:#1D1D1F;line-height:1.35} i{font-style:normal;color:#B3261E;margin-right:4px}
</style><main>${cells}</main>`;
const contactHtml = path.join(outDir, 'contact.html');
fs.writeFileSync(contactHtml, html);
const rows = Math.ceil(report.length / cols), cw = cols * (tw + 14) + 14, ch = rows * (th + 60) + 14;
await send('Emulation.setDeviceMetricsOverride', { width: cw, height: ch, deviceScaleFactor: 1, mobile: false });
const l2 = once('Page.loadEventFired');
await send('Page.navigate', { url: pathToFileURL(contactHtml).href });
await l2; await sleep(300);
const dims = await evaluate('({w: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight})');
const sheet = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: 0, width: dims.w, height: dims.h, scale: 1 } });
fs.writeFileSync(path.join(outDir, 'contact.png'), Buffer.from(sheet.data, 'base64'));
fs.rmSync(contactHtml);

const flagged = report.filter(r => r.flags.some(f => f === '溢出' || f.startsWith('小字')));
console.log(`\n完成：${pages.length} 页 → ${report.length} 张 PNG + contact.png + report.json`);
if (flagged.length) console.log(`需要人工看的：${flagged.map(r => r.file.replace('slide-', '').replace('.png', '')).join(', ')}（溢出或 10% 分位字号 < 20px）`);
ws.close();
process.exit(0);
