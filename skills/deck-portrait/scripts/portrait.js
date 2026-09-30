// 注入到横屏 deck 页面里运行：逐页竖屏重排 + 图太小时追加局部放大页 + 溢出自动缩放 + 字号测量。
// 图（自绘 SVG、论文位图）一律整张保留原结构，不切块、不改排列；放大页只是同一张图的局部裁切。
// 由 deck_portrait.mjs 填入 CSS 与画布尺寸后通过 CDP 执行。
(function(){
  if (window.__pt) return;
  const CSS = __PT_CSS__, W = __PT_W__, H = __PT_H__;
  const style = document.createElement('style');
  style.id = 'pt-style';
  style.textContent = `:root{--pt-w:${W}px;--pt-h:${H}px}\n` + CSS;
  document.head.appendChild(style);           // 放在 deck 自己的 <style> 之后，同优先级时覆盖它

  const MINI_H = 150, MINI_GAP = 22;          // 放大页顶部小地图的高度与间距（px）
  const frames = n => new Promise(r => { const f = () => (--n <= 0 ? r() : requestAnimationFrame(f)); requestAnimationFrame(f); });
  const slides = () => [...document.querySelectorAll('.slide')];
  const activeIdx = () => slides().findIndex(s => s.classList.contains('active'));
  const setI = (e, p, v) => e.style.setProperty(p, v, 'important');

  // ---------- 翻页：优先用 deck 自己的键盘导航（会跑它的 fitFigs / 箭头布局 / 动画初始化） ----------
  async function goto(i) {
    const S = slides();
    let cur = activeIdx(), guard = 0;
    while (cur !== i && guard++ < 500) {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: i > cur ? 'ArrowRight' : 'ArrowLeft', bubbles: true }));
      const n = activeIdx();
      if (n === cur) break;
      cur = n;
    }
    if (cur !== i) S.forEach((s, k) => s.classList.toggle('active', k === i));
    const sl = S[i];
    await Promise.all([...sl.querySelectorAll('img')].map(im => im.complete ? 0 : new Promise(r => { im.onload = im.onerror = r; })));
    await Promise.all([...sl.querySelectorAll('img')].map(im => im.decode ? im.decode().catch(() => 0) : 0));
    await document.fonts.ready;
    sl.querySelectorAll('svg[data-anim] [data-a]').forEach(e => e.classList.add('on'));
    sl.querySelectorAll('video').forEach(v => { try { v.pause(); } catch (e) {} });
    await frames(2);
    return sl;
  }

  // ---------- SVG：元素在根坐标系里的包围盒（用来裁边、找放大页的下刀空隙、算图内字号） ----------
  function svgItems(svg) {
    const vb = svg.viewBox.baseVal;
    const inv = svg.getScreenCTM().inverse();
    const out = [];
    const sel = 'rect,circle,ellipse,line,polyline,polygon,path,text,image,use,foreignObject';
    for (const e of svg.querySelectorAll(sel)) {
      if (e.closest('defs,marker,clipPath,mask,pattern,symbol')) continue;
      const cr = e.getBoundingClientRect();
      if (cr.width < 0.5 && cr.height < 0.5) continue;
      const cs = getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden') continue;
      let b; try { b = e.getBBox(); } catch (err) { continue; }
      const m = inv.multiply(e.getScreenCTM());
      const pts = [[b.x, b.y], [b.x + b.width, b.y], [b.x, b.y + b.height], [b.x + b.width, b.y + b.height]]
        .map(([x, y]) => new DOMPoint(x, y).matrixTransform(m));
      const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
      const it = { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) };
      const tag = e.tagName.toLowerCase();
      if (tag === 'rect' && (it.x1 - it.x0) * (it.y1 - it.y0) > 0.8 * vb.width * vb.height) continue;   // 整张底卡
      const noFill = cs.fill === 'none' || cs.fill === 'rgba(0, 0, 0, 0)';
      it.conn = tag === 'line' || ((tag === 'path' || tag === 'polyline') && noFill);
      if (tag === 'text') it.fs = parseFloat(cs.fontSize) * Math.hypot(m.a, m.b);
      out.push(it);
    }
    return out;
  }

  // 沿一个轴找空隙（实体元素之间没被占住的区间），返回空隙中点
  function gapsOf(items, axis, minGap) {
    const k0 = axis === 'x' ? 'x0' : 'y0', k1 = axis === 'x' ? 'x1' : 'y1';
    const iv = items.filter(t => !t.conn).map(t => [t[k0], t[k1]]).sort((p, q) => p[0] - q[0]);
    const mg = [];
    for (const [s, e] of iv) {
      if (mg.length && s <= mg[mg.length - 1][1] + minGap) mg[mg.length - 1][1] = Math.max(mg[mg.length - 1][1], e);
      else mg.push([s, e]);
    }
    return mg.slice(1).map((m, k) => (mg[k][1] + m[0]) / 2);
  }

  const fitScale = (w, h, bw, bh) => Math.max(0.01, Math.min(bw / w, bh / h));

  // 放大页的裁切：沿图的长边等分成 n 段，每段向两侧多带一点上下文，边缘吸附到最近的空隙，尽量不从字或框中间裁
  function cropsFor(full, axis, n, gaps) {
    const a0 = axis === 'x' ? full.x0 : full.y0, a1 = axis === 'x' ? full.x1 : full.y1, L = a1 - a0;
    const ov = L * 0.06, snap = L * 0.2, out = [];
    for (let k = 0; k < n; k++) {
      let lo = k ? a0 + L * k / n - ov : a0, hi = k < n - 1 ? a0 + L * (k + 1) / n + ov : a1;
      if (k) { const g = gaps.filter(x => x <= lo && x >= lo - snap); if (g.length) lo = Math.max(...g); }
      if (k < n - 1) { const g = gaps.filter(x => x >= hi && x <= hi + snap); if (g.length) hi = Math.min(...g); }
      out.push(axis === 'x' ? { ...full, x0: lo, x1: hi, cutLo: k > 0, cutHi: k < n - 1, axis } : { ...full, y0: lo, y1: hi, cutLo: k > 0, cutHi: k < n - 1, axis });
    }
    return out;
  }

  // 位图的空隙：整列 / 整行接近背景色的地方（容忍面板边框穿过的几个像素）
  function imgGaps(img) {
    const nw = img.naturalWidth, nh = img.naturalHeight;
    const aw = Math.min(nw, 1200), f = aw / nw, ah = Math.max(1, Math.round(nh * f));
    const cv = document.createElement('canvas'); cv.width = aw; cv.height = ah;
    const cx = cv.getContext('2d', { willReadFrequently: true });
    cx.drawImage(img, 0, 0, aw, ah);
    let px; try { px = cx.getImageData(0, 0, aw, ah).data; } catch (e) { return { x: [], y: [] }; }
    const cnt = new Map(); const q = i => ((px[i] >> 4) << 8) | ((px[i + 1] >> 4) << 4) | (px[i + 2] >> 4);
    const bump = i => cnt.set(q(i), (cnt.get(q(i)) || 0) + 1);
    for (let x = 0; x < aw; x++) { bump(x * 4); bump(((ah - 1) * aw + x) * 4); }
    for (let y = 0; y < ah; y++) { bump(y * aw * 4); bump((y * aw + aw - 1) * 4); }
    const bgq = [...cnt.entries()].sort((a, b) => b[1] - a[1])[0][0];
    const bg = [((bgq >> 8) & 15) * 16 + 8, ((bgq >> 4) & 15) * 16 + 8, (bgq & 15) * 16 + 8];
    const colInk = new Array(aw).fill(0), rowInk = new Array(ah).fill(0);
    for (let y = 0, j = 0; y < ah; y++) for (let x = 0; x < aw; x++, j++) {
      const i = j * 4;
      if (Math.abs(px[i] - bg[0]) + Math.abs(px[i + 1] - bg[1]) + Math.abs(px[i + 2] - bg[2]) > 60) { colInk[x]++; rowInk[y]++; }
    }
    const runs = (ink, len, other) => {
      const clean = ink.map(v => v <= Math.max(4, other * 0.012)), out = [];
      for (let x = 0; x < len;) { if (!clean[x]) { x++; continue; } let e = x; while (e < len && clean[e]) e++; if (e - x >= 3) out.push((x + e) / 2 / f); x = e; }
      return out;
    };
    return { x: runs(colInk, aw, ah), y: runs(rowInk, ah, aw) };
  }

  function planBlock(el) {
    const svg = el.classList.contains('diagbox') ? el.querySelector(':scope > svg') : null;
    const media = svg || el.querySelector(':scope > img, :scope > video');
    if (!media) return null;
    const pad = el.classList.contains('diagbox') ? 28 : (el.classList.contains('card') ? 30 : 0);
    const bw = el.clientWidth - 2 * pad, bh = Math.max(200, el.clientHeight - 2 * pad);
    const b = { el, media, svg, pad, bw, bh, gaps: { x: [], y: [] } };
    if (svg) {
      const vb = svg.viewBox.baseVal;
      if (!vb || !vb.width) return null;
      b.full = { x0: vb.x, y0: vb.y, x1: vb.x + vb.width, y1: vb.y + vb.height };
      const items = svgItems(svg);
      if (items.length) {       // 只裁掉四周空白，图本身一点不动
        const p = Math.max(8, vb.width * 0.012);
        b.full = { x0: Math.max(b.full.x0, Math.min(...items.map(t => t.x0)) - p), x1: Math.min(b.full.x1, Math.max(...items.map(t => t.x1)) + p),
                   y0: Math.max(b.full.y0, Math.min(...items.map(t => t.y0)) - p), y1: Math.min(b.full.y1, Math.max(...items.map(t => t.y1)) + p) };
        const g = Math.max(4, vb.width * 0.004);
        b.gaps = { x: gapsOf(items, 'x', g), y: gapsOf(items, 'y', g) };
        const fs = items.filter(t => t.fs).map(t => t.fs).sort((a, c) => a - c);
        b.fsP10 = fs.length ? fs[Math.floor(fs.length * 0.1)] : null;       // 图内文字 10% 分位字号（viewBox 单位）
      }
    } else if (media.tagName === 'IMG') {
      if (!media.naturalWidth) return null;
      b.full = { x0: 0, y0: 0, x1: media.naturalWidth, y1: media.naturalHeight };
      b.gaps = imgGaps(media);
    } else {
      b.full = { x0: 0, y0: 0, x1: media.videoWidth || 16, y1: media.videoHeight || 9 };
    }
    return b;
  }

  // 把图的显示换成「一个视窗」：SVG 改 viewBox，位图用 canvas 裁；放大页复用同一个视窗
  function materialize(b) {
    const box = document.createElement('div'); box.className = 'pt-panels';
    const view = b.svg || (b.media.tagName === 'IMG' ? document.createElement('img') : b.media);
    b.view = view;
    if (b.svg) b.svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    else if (view !== b.media) b.media.style.display = 'none';
    // 小地图：整张图缩略 + 高亮当前放大的区域，只在放大页显示
    if (b.crops) {
      const mini = document.createElement('div'); mini.className = 'pt-mini';
      const thumb = b.svg ? b.svg.cloneNode(true) : document.createElement('img');
      if (b.svg) { thumb.querySelectorAll('[id]').forEach(n => n.removeAttribute('id')); thumb.setAttribute('viewBox', `${b.full.x0} ${b.full.y0} ${b.full.x1 - b.full.x0} ${b.full.y1 - b.full.y0}`); }
      else thumb.src = b.media.currentSrc || b.media.src;
      const hl = document.createElement('div'); hl.className = 'pt-hl';
      mini.append(thumb, hl);
      box.appendChild(mini);
      b.mini = { el: mini, thumb, hl };
    }
    box.appendChild(view);
    b.el.appendChild(box);
    if (b.el.classList.contains('card') && !b.el.classList.contains('diagbox')) setI(b.el, 'padding', '0');
  }

  function showRegion(b, r) {
    if (b.svg) { b.svg.setAttribute('viewBox', `${r.x0} ${r.y0} ${r.x1 - r.x0} ${r.y1 - r.y0}`); return; }
    if (b.media.tagName !== 'IMG') return;
    const key = [r.x0, r.y0, r.x1, r.y1].map(Math.round).join(',');
    if (b.view.dataset.region === key) return;
    const cv = document.createElement('canvas');
    cv.width = Math.round(r.x1 - r.x0); cv.height = Math.round(r.y1 - r.y0);
    cv.getContext('2d').drawImage(b.media, r.x0, r.y0, r.x1 - r.x0, r.y1 - r.y0, 0, 0, cv.width, cv.height);
    try { b.view.src = cv.toDataURL('image/png'); } catch (e) { b.view.src = b.media.currentSrc || b.media.src; }
    b.view.dataset.region = key;
  }

  // 给当前 part 的每个图块定尺寸：part 0 显示整张，part k 显示主块的第 k 个裁切
  async function sizeBlocks(blocks, main, part) {
    for (const b of blocks) {
      const r = b === main && part > 0 ? b.crops[part - 1] : b.full;
      b.cur = r;
      ['width', 'height', 'margin', 'margin-top', 'margin-bottom', 'flex', 'align-self'].forEach(p => b.el.style.removeProperty(p));
      setI(b.el, 'flex', `${Math.max(1, Math.round(1000 * (r.y1 - r.y0) / (r.x1 - r.x0)))} 1 0px`);
      setI(b.el, 'min-height', '0');
      showRegion(b, r);
      if (b.mini) b.mini.el.style.display = b === main && part > 0 ? '' : 'none';
    }
    await Promise.all(blocks.filter(b => b.view.tagName === 'IMG').map(b => b.view.decode().catch(() => 0)));
    void document.body.offsetHeight;
    return blocks.map(b => {
      const r = b.cur, withMini = b.mini && b.mini.el.style.display !== 'none';
      const W0 = b.el.clientWidth - 2 * b.pad, H0 = b.el.clientHeight - 2 * b.pad - (withMini ? MINI_H + MINI_GAP : 0);
      const s = fitScale(r.x1 - r.x0, r.y1 - r.y0, W0, H0);
      const w = (r.x1 - r.x0) * s, h = (r.y1 - r.y0) * s;
      setI(b.view, 'width', w + 'px'); setI(b.view, 'height', h + 'px');
      const F = 56, dir = r.axis === 'y' ? 'to bottom' : 'to right';
      const mask = r.cutLo || r.cutHi ? `linear-gradient(${dir}, ${r.cutLo ? 'transparent 0,#000 ' + F + 'px' : '#000 0'}, ${r.cutHi ? '#000 calc(100% - ' + F + 'px),transparent 100%' : '#000 100%'})` : '';
      b.view.style.webkitMaskImage = mask; b.view.style.maskImage = mask;
      let ch = h, cw = w;
      if (withMini) {
        const f = b.full, ms = Math.min(MINI_H / (f.y1 - f.y0), W0 / (f.x1 - f.x0));
        const mw = (f.x1 - f.x0) * ms, mh = (f.y1 - f.y0) * ms;
        setI(b.mini.thumb, 'width', mw + 'px'); setI(b.mini.thumb, 'height', mh + 'px');
        b.mini.el.style.width = mw + 'px'; b.mini.el.style.height = mh + 'px'; b.mini.el.style.marginBottom = MINI_GAP + 'px';
        Object.assign(b.mini.hl.style, { left: (r.x0 - f.x0) * ms + 'px', top: (r.y0 - f.y0) * ms + 'px', width: (r.x1 - r.x0) * ms + 'px', height: (r.y1 - r.y0) * ms + 'px' });
        ch += mh + MINI_GAP; cw = Math.max(cw, mw);
      }
      setI(b.el, 'flex', 'none');
      setI(b.el, 'height', Math.ceil(ch + 2 * b.pad) + 'px');
      if (!b.el.classList.contains('diagbox')) { setI(b.el, 'width', Math.ceil(cw + 2 * b.pad) + 'px'); setI(b.el, 'align-self', 'center'); }
      if (blocks.length === 1) { setI(b.el, 'margin-top', 'auto'); setI(b.el, 'margin-bottom', 'auto'); }   // 单块时在剩余空间里居中
      return s;
    });
  }

  // ---------- 溢出检测 ----------
  function overflow(sl) {
    const sr = sl.getBoundingClientRect(), cs = getComputedStyle(sl), z = sr.width / sl.offsetWidth || 1;
    const pb = parseFloat(cs.paddingBottom) * z, pr = parseFloat(cs.paddingRight) * z, pl = parseFloat(cs.paddingLeft) * z;
    const lim = { l: sr.left + pl * 0.5, r: sr.right - pr * 0.5, b: sr.bottom - pb * 0.5 };
    const bad = [];
    for (const e of sl.querySelectorAll('*')) {
      if (e.closest('svg') && e.tagName.toLowerCase() !== 'svg') continue;
      if (e.closest('.pt-mini')) continue;
      const r = e.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) continue;
      if (sl.classList.contains('cover') && e.closest('.photos')) continue;
      if (r.bottom > lim.b + 1 || r.right > lim.r + 1 || r.left < lim.l - 1) { bad.push(e); continue; }
      const oc = getComputedStyle(e);
      if (oc.overflow !== 'visible' && !e.closest('.ph') && !['svg', 'img', 'video', 'canvas'].includes(e.tagName.toLowerCase())
          && (e.scrollHeight > e.clientHeight + 2 || e.scrollWidth > e.clientWidth + 2)) bad.push(e);
    }
    return bad;
  }

  // ---------- 字号测量（1080 宽画布上的像素，按字数加权；小地图不算） ----------
  function textStats(sl) {
    const rows = [], seen = new Set();
    const tw = document.createTreeWalker(sl, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = tw.nextNode())) {
      const t = n.nodeValue.replace(/\s+/g, ''); if (!t) continue;
      const p = n.parentElement; if (!p || p.closest('.pt-mini')) continue;
      if (p.closest('svg')) {
        const te = p.closest('text'); if (!te || seen.has(te)) continue; seen.add(te);
        const svg = te.ownerSVGElement; if (!svg) continue;
        const r = te.getBoundingClientRect(), sr = svg.getBoundingClientRect();
        if (r.width < 1 || sr.width < 1) continue;
        const ix = Math.max(0, Math.min(r.right, sr.right) - Math.max(r.left, sr.left)), iy = Math.max(0, Math.min(r.bottom, sr.bottom) - Math.max(r.top, sr.top));
        if (ix * iy < 0.5 * r.width * r.height) continue;          // 放大页视窗外的字不算
        const vb = svg.viewBox.baseVal;
        const s = vb && vb.width ? Math.min(sr.width / vb.width, sr.height / vb.height) : 1;
        const m = te.getCTM(), inner = m ? Math.hypot(m.a, m.b) : 1;
        rows.push([parseFloat(getComputedStyle(te).fontSize) * s * (inner || 1), te.textContent.replace(/\s+/g, '').length, te.textContent.trim().slice(0, 24)]);
        continue;
      }
      if (getComputedStyle(p).visibility === 'hidden') continue;
      const r = p.getBoundingClientRect(); if (r.width < 1 || !p.offsetWidth) continue;
      rows.push([parseFloat(getComputedStyle(p).fontSize) * (r.width / p.offsetWidth), t.length, t.slice(0, 24)]);
    }
    if (!rows.length) return { p10: null, min: null, small: [] };
    const tot = rows.reduce((a, r) => a + r[1], 0);
    const sorted = [...rows].sort((a, b) => a[0] - b[0]);
    let acc = 0, p10 = sorted[0][0];
    for (const r of sorted) { acc += r[1]; if (acc >= tot * 0.1) { p10 = r[0]; break; } }
    return { p10: +p10.toFixed(1), min: +sorted[0][0].toFixed(1), small: sorted.slice(0, 3).map(r => `${r[0].toFixed(1)}px「${r[2]}」`) };
  }

  // ---------- 一页的首次构建：找图块，决定要不要追加放大页 ----------
  function build(sl, override, opts) {
    sl.querySelectorAll('.fig, .fig2, .diagbox').forEach(e => ['flex', 'width', 'height', 'margin', 'align-self', 'justify-content'].forEach(p => e.style.removeProperty(p)));
    void document.body.offsetHeight;
    const els = [...sl.querySelectorAll('.fig, .diagbox')].filter(e => e.classList.contains('diagbox') || e.querySelector(':scope > img, :scope > video'));
    const blocks = els.map(planBlock).filter(Boolean);
    let main = null, crops = 0, why;
    if (blocks.length) {
      main = blocks.reduce((a, b) => (b.bw * b.bh > a.bw * a.bh ? b : a));
      const f = main.full, fw = f.x1 - f.x0, fh = f.y1 - f.y0;
      // 放大页的可用空间：整页减去标题区（主块上方的高度）、底部留白和小地图
      const top = main.el.getBoundingClientRect().top - sl.getBoundingClientRect().top;
      const zbw = main.bw, zbh = H - top - 60 - 2 * main.pad - MINI_H - MINI_GAP;
      const s1 = fitScale(fw, fh, main.bw, main.bh);
      const axis = main.bw / fw < main.bh / fh ? 'x' : 'y';          // 被宽度卡住就沿横向裁
      const scaleN = n => Math.min(...cropsFor(f, axis, n, main.gaps[axis]).map(r => fitScale(r.x1 - r.x0, r.y1 - r.y0, zbw, zbh)));
      if (override.crops !== undefined) crops = override.crops;
      else if (opts.autoCrops && main.svg && main.fsP10 && main.fsP10 * s1 < opts.cropBelow) {
        for (let n = 2; n <= (opts.maxCrops || 2); n++) { crops = n; if (main.fsP10 * scaleN(n) >= opts.cropTarget) break; }
        if (scaleN(crops) / s1 < 1.3) { crops = 0; why = 'zoom-low-gain'; }
      }
      if (crops > 0) { main.crops = cropsFor(f, axis, crops, main.gaps[axis]); main.axis = axis; main.zoomGain = +(scaleN(crops) / s1).toFixed(2); }
    }
    blocks.forEach(materialize);
    // 放大页只保留标题区和主图：主图所在路径上的其他兄弟元素都藏起来
    const hideOnZoom = [];
    if (main && main.crops) {
      for (let e = main.el; e && e !== sl; e = e.parentElement) {
        for (const sib of e.parentElement.children) {
          if (sib === e) continue;
          if (e.parentElement === sl && (sib.classList.contains('kicker') || sib.tagName === 'H1')) continue;
          hideOnZoom.push(sib);
        }
      }
    }
    return { blocks, main, parts: main && main.crops ? 1 + main.crops.length : 1, hideOnZoom, why };
  }

  let extraStyle = null;
  async function render(i, override, opts, part) {
    override = override || {}; opts = opts || {}; part = part || 0;
    const sl = await goto(i);
    if (extraStyle) { extraStyle.remove(); extraStyle = null; }
    if (override.css) { extraStyle = document.createElement('style'); extraStyle.textContent = override.css; document.head.appendChild(extraStyle); }
    await frames(1);
    if (!sl.__pt) sl.__pt = build(sl, override, opts);
    const st = sl.__pt;
    st.hideOnZoom.forEach(e => { e.style.display = part > 0 ? 'none' : ''; });
    let tag = sl.querySelector('.pt-part');
    if (st.parts > 1) {
      if (!tag) { tag = document.createElement('span'); tag.className = 'pt-part'; (sl.querySelector('.kicker') || sl.querySelector('h1') || sl).appendChild(tag); }
      tag.textContent = part > 0 ? ` · 局部放大 ${part}/${st.parts - 1}` : '';
    }
    const minZ = opts.minZoom || 0.75;
    let z = override.zoom || 1, bad = [], scales = [];
    for (;;) {
      sl.style.zoom = z; sl.style.width = (W / z) + 'px'; sl.style.height = (H / z) + 'px';
      sl.style.right = 'auto'; sl.style.bottom = 'auto';
      await frames(1);
      scales = await sizeBlocks(st.blocks, st.main, part);
      await frames(1);
      bad = overflow(sl);
      if (!bad.length || override.zoom || z <= minZ + 1e-6) break;
      z = Math.round((z - 0.05) * 100) / 100;
    }
    return {
      index: i + 1, part, parts: st.parts, sec: sl.dataset.sec || '', title: sl.dataset.title || (sl.querySelector('h1') || {}).textContent || '',
      type: [...sl.classList].filter(c => c !== 'slide' && c !== 'active').join(' '),
      zoom: z, overflow: bad.slice(0, 3).map(e => e.tagName.toLowerCase() + (typeof e.className === 'string' && e.className ? '.' + e.className.split(' ')[0] : '')),
      blocks: st.blocks.map((b, k) => ({ kind: b.svg ? 'svg' : b.media.tagName.toLowerCase(), scale: +scales[k].toFixed(3),
        crops: b.crops ? b.crops.length : 0, axis: b.axis, zoomGain: b.zoomGain })),
      why: st.why,
      text: textStats(sl),
    };
  }

  function info() {
    return { count: slides().length, titles: slides().map(s => s.dataset.title || (s.querySelector('h1') || {}).textContent || '') };
  }

  // 调试：某页每张图的裁边范围、候选空隙和图内字号
  async function debug(i) {
    const sl = await goto(i);
    return [...sl.querySelectorAll('.fig, .diagbox')].map(planBlock).filter(Boolean).map(b => ({
      kind: b.svg ? 'svg' : b.media.tagName.toLowerCase(), box: [Math.round(b.bw), Math.round(b.bh)],
      full: [b.full.x0, b.full.y0, b.full.x1, b.full.y1].map(Math.round), fsP10: b.fsP10,
      gapsX: b.gaps.x.map(Math.round), gapsY: b.gaps.y.map(Math.round) }));
  }
  window.__pt = { render, info, debug };
})();
