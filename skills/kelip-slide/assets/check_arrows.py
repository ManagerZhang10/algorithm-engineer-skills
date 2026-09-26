#!/usr/bin/env python3
"""检查 deck 里自绘 SVG 的箭头：有没有对准块、有没有穿过别的块或文字。

用法:  python3 check_arrows.py deck.html
产物:  终端逐条列出问题（第几页、哪根箭头、差多少），有 ✗ 级问题时退出码 1
依赖:  本机装了 Chrome（或用 CHROME 环境变量指路径）；不改动 deck 本身

它在 headless Chrome 里把每页依次显示出来，按浏览器实际排版量坐标（JS 生成的图、
data-from/data-to 自动连线都算在内），所以查到的就是屏幕上看到的。

判据（SVG 坐标单位，viewBox 宽 1600 时 ≈ 屏幕像素）：
  ✗ 箭头头部悬空：离最近的块 / 文字超过 28
  ✗ 箭头扎进块里：箭头尖进到块内部超过 6
  ✗ 打偏：水平 / 竖直箭头的落点不在块的那条边上（擦着角或完全错开）
  ✗ 穿过别的块 / 文字：箭头路径经过起点块、终点块以外的块或文字
  △ 没对准中心：水平 / 竖直箭头进出一个块时偏离那条边的中点超过 6，
     且这条边上只有这一根箭头（多根箭头扇入扇出时错开是故意的，不报）
  △ 尾部悬空：箭头起点离最近的块超过 28
"""
import json, os, pathlib, re, shutil, subprocess, sys, tempfile

CANDIDATES = [
    os.environ.get("CHROME", ""),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
]
CHROME = next((c for c in CANDIDATES if c and pathlib.Path(c).exists()), None)

CHECK_JS = r"""
<script>
window.addEventListener('load',()=>setTimeout(()=>{
const NEAR=28, DEEP=6, OFF=6, SHRINK=2;
const issues=[];
const slides=[...document.querySelectorAll('.slide')];
function toSvg(el,svg){ return svg.getScreenCTM().inverse().multiply(el.getScreenCTM()); }
function boxOf(el,svg){
  let bb; try{ bb=el.getBBox(); }catch(e){ return null; }
  if(!bb.width&&!bb.height) return null;
  const m=toSvg(el,svg);
  const ps=[[bb.x,bb.y],[bb.x+bb.width,bb.y],[bb.x,bb.y+bb.height],[bb.x+bb.width,bb.y+bb.height]].map(([x,y])=>new DOMPoint(x,y).matrixTransform(m));
  const xs=ps.map(p=>p.x), ys=ps.map(p=>p.y);
  return {l:Math.min(...xs),t:Math.min(...ys),r:Math.max(...xs),b:Math.max(...ys)};
}
function visible(el){ const cs=getComputedStyle(el); return cs.display!=='none'&&cs.visibility!=='hidden'&&parseFloat(cs.opacity)>0; }
function painted(el){ const cs=getComputedStyle(el); return (cs.fill!=='none'&&parseFloat(cs.fillOpacity)>0)||(cs.stroke!=='none'&&parseFloat(cs.strokeWidth)>0); }
function sdist(p,b){ // 到矩形边界的有符号距离：外正内负
  const dx=Math.max(b.l-p.x,0,p.x-b.r), dy=Math.max(b.t-p.y,0,p.y-b.b);
  if(dx||dy) return Math.hypot(dx,dy);
  return -Math.min(p.x-b.l,b.r-p.x,p.y-b.t,b.b-p.y);
}
function inside(p,b,s){ return p.x>b.l+s&&p.x<b.r-s&&p.y>b.t+s&&p.y<b.b-s; }
function contains(a,b){ return a!==b&&a.l<=b.l+1&&a.t<=b.t+1&&a.r>=b.r-1&&a.b>=b.b-1; }
function snip(el){ return el.outerHTML.replace(/\s+/g,' ').slice(0,110); }
slides.forEach((sl,si)=>{
  if(window.deckShow) window.deckShow(si); else slides.forEach(s=>s.classList.toggle('active',s===sl));
  const title=sl.dataset.title||(sl.querySelector('h1')||{}).textContent||'';
  sl.querySelectorAll('svg').forEach((svg,vi)=>{
    const arrows=[...svg.querySelectorAll('line,path,polyline')].filter(e=>(e.getAttribute('marker-end')||e.getAttribute('marker-start')||getComputedStyle(e).markerEnd!=='none')&&visible(e));
    if(!arrows.length) return;
    const vb=svg.viewBox.baseVal, W=vb&&vb.width||svg.clientWidth;
    let shapes=[...svg.querySelectorAll('rect,circle,ellipse,polygon')].filter(e=>visible(e)&&painted(e))
      .map(e=>({el:e,kind:'块',b:boxOf(e,svg)})).filter(s=>s.b&&(s.b.r-s.b.l)<W*0.9&&(s.b.r-s.b.l)>8&&(s.b.b-s.b.t)>8);
    shapes.forEach(s=>{ s.container=shapes.some(o=>contains(s.b,o.b)); });
    const texts=[...svg.querySelectorAll('text')].filter(visible).map(e=>({el:e,kind:'文字',b:boxOf(e,svg),text:e.textContent.trim().slice(0,16)})).filter(s=>s.b&&s.text);
    const targets=shapes.concat(texts);
    const geo=arrows.map(a=>{
      const m=toSvg(a,svg); let L=0; try{ L=a.getTotalLength(); }catch(e){}
      const n=Math.max(2,Math.ceil(L/3)), pts=[];
      for(let i=0;i<=n;i++){ const q=a.getPointAtLength(L*i/n); pts.push(new DOMPoint(q.x,q.y).matrixTransform(m)); }
      const headAtStart=!a.getAttribute('marker-end')&&!!a.getAttribute('marker-start');
      if(headAtStart) pts.reverse();
      return {a,pts};
    });
    // 分组框（里面还套着别的块）按到边框的距离算：箭头从外面指进分组框、落在里面的块上是正常画法
    const near=p=>{ let best=null,bd=1e9; targets.forEach(t=>{ let d=sdist(p,t.b); if(t.container) d=Math.abs(d)+0.5; const ad=d<0?0:d; if(ad<bd||(ad===bd&&t.kind==='块')){ bd=ad; best={t,d}; } }); return best; };
    const dirOf=(p,q)=>{ const dx=q.x-p.x, dy=q.y-p.y; if(Math.abs(dy)<=Math.abs(dx)*0.05) return 'h'; if(Math.abs(dx)<=Math.abs(dy)*0.05) return 'v'; return null; };
    // 水平箭头只在块的左右两侧才算「进出这条边」，竖直的同理；从分叉线中段出发的不算
    const facing=(p,b,dir)=>dir==='h'?(p.x<=b.l+DEEP||p.x>=b.r-DEEP):(p.y<=b.t+DEEP||p.y>=b.b-DEEP);
    const ends=[]; // 用来判「同一条边上几根箭头」
    geo.forEach(g=>{
      const P=g.pts, tail=P[0], tip=P[P.length-1];
      const k=Math.max(1,Math.min(P.length-1,6));
      g.tipDir=dirOf(P[P.length-1-k],tip); g.tailDir=dirOf(tail,P[k]);
      g.tip=near(tip); g.tail=near(tail);
      [['tip',g.tip,g.tipDir,tip],['tail',g.tail,g.tailDir,tail]].forEach(([w,n,dir,p])=>{
        if(n&&n.t.kind==='块'&&!n.t.container&&dir&&n.d<=NEAR&&facing(p,n.t.b,dir)){ const b=n.t.b; const side=dir==='h'?(p.x<(b.l+b.r)/2?'L':'R'):(p.y<(b.t+b.b)/2?'T':'B'); ends.push({g,w,el:n.t.el,side}); g[w+'Side']=side; }
      });
    });
    geo.forEach(g=>{
      const P=g.pts, tail=P[0], tip=P[P.length-1], out=(lvl,msg)=>issues.push({slide:si+1,title,svg:vi+1,lvl,msg,el:snip(g.a)});
      if(!g.tip||g.tip.d>NEAR) out('✗',`箭头头部悬空：离最近的块/文字 ${g.tip?Math.round(g.tip.d):'∞'}`);
      else if(g.tip.d<-DEEP&&!g.tip.t.container) out('✗',`箭头扎进${g.tip.t.kind}里 ${Math.round(-g.tip.d)}（${g.tip.t.text||g.tip.t.el.tagName}）`);
      if(!g.tail||g.tail.d>NEAR) out('△',`尾部悬空：离最近的块/文字 ${g.tail?Math.round(g.tail.d):'∞'}`);
      [['tip',g.tip,g.tipDir,tip,'头部'],['tail',g.tail,g.tailDir,tail,'尾部']].forEach(([w,n,dir,p,name])=>{
        if(!n||n.t.kind!=='块'||n.t.container||!dir||n.d>NEAR||!facing(p,n.t.b,dir)) return;
        const b=n.t.b, c=dir==='h'?p.y:p.x, lo=dir==='h'?b.t:b.l, hi=dir==='h'?b.b:b.r, mid=(lo+hi)/2, half=(hi-lo)/2;
        if(c<lo+2||c>hi-2){ out('✗',`${name}打偏：${dir==='h'?'y':'x'}=${Math.round(c)}，块的那条边在 ${Math.round(lo)}–${Math.round(hi)}`); return; }
        const same=ends.filter(e=>e.el===n.t.el&&e.side===g[w+'Side']).length;
        if(same===1&&Math.abs(c-mid)>OFF) out('△',`${name}没对准中心：偏 ${Math.round(c-mid)}（块中线 ${dir==='h'?'y':'x'}=${Math.round(mid)}，半宽 ${Math.round(half)}）${g.a.dataset.from?'——自动连线也对不齐说明两个块本身没对齐，挪块':''}`);
      });
      const skip=new Set([g.tip&&g.tip.t,g.tail&&g.tail.t].filter(Boolean));
      targets.forEach(t=>{
        if(skip.has(t)||t.container) return;
        // 起终点块里的文字也跳过
        if(t.kind==='文字'&&[...skip].some(s=>s.kind==='块'&&contains(s.b,t.b))) return;
        const hit=P.slice(2,-2).find(p=>inside(p,t.b,SHRINK));
        if(hit) out('✗',`穿过${t.kind}「${t.text||t.el.tagName}」于 (${Math.round(hit.x)},${Math.round(hit.y)})`);
      });
    });
  });
});
const pre=document.createElement('pre'); pre.id='__arrowcheck'; pre.textContent=JSON.stringify(issues); document.body.appendChild(pre);
},600));
</script>
"""

def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if not CHROME:
        sys.exit("找不到 Chrome，用 CHROME=/path/to/chrome 指定")
    deck = pathlib.Path(sys.argv[1]).resolve()
    html = deck.read_text(encoding="utf-8")
    html = html.replace("</body>", CHECK_JS + "</body>") if "</body>" in html else html + CHECK_JS
    # 放在 deck 同目录，保证 media/ 相对路径照常能加载；用完就删
    fd, tmp = tempfile.mkstemp(prefix=".arrowcheck-", suffix=".html", dir=deck.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(html)
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                            "--window-size=1920,1080", "--virtual-time-budget=8000",
                            "--dump-dom", pathlib.Path(tmp).as_uri()],
                           capture_output=True, text=True, timeout=180)
    finally:
        os.unlink(tmp)
    m = re.search(r'<pre id="__arrowcheck">(.*?)</pre>', r.stdout, re.S)
    if not m:
        sys.exit("检查脚本没有跑完（deck 的 JS 报错了？）用 Chrome 打开 deck 看控制台")
    issues = json.loads(m.group(1).replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&"))
    if not issues:
        print("箭头检查通过：没有悬空、打偏、没对准或穿块的箭头")
        return
    cur = None
    for it in issues:
        key = (it["slide"], it["svg"])
        if key != cur:
            cur = key
            print(f"\n第 {it['slide']} 页「{it['title'].strip()}」第 {it['svg']} 张图")
        print(f"  {it['lvl']} {it['msg']}\n      {it['el']}")
    bad = sum(it["lvl"] == "✗" for it in issues)
    print(f"\n共 {len(issues)} 条，✗ {bad} 条，△ {len(issues) - bad} 条")
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
