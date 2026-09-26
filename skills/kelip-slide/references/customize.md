# 改造模板

框架固定的只有「1920×1080 舞台 + 一页一个主体块 + JS 图卡自适应」。其余都能改，
下面是几件最常改的。改完都跑一遍渲染自查。

## 换配色

`:root` 里改这几行就够，所有组件都是引用变量的：

```css
:root{
  --bg:#F5F5F7;    /* 页面底色 */
  --ink:#1D1D1F;   /* 正文 */
  --muted:#6E6E73; /* 次要文字、kicker、注释 */
  --faint:#A1A1A6; /* 更淡的一层：页码、dim 状态 */
  --line:#D2D2D7;  /* 分隔线、表格线 */
  --card:#FFFFFF;  /* 白卡 */
  --accent:#0071E3;/* 唯一强调色 —— 换品牌色改这一行 */
}
```

深色版：把 `--bg` 换成 `#0B0B0C`、`--ink` 换 `#F5F5F7`、`--card` 换 `#1C1C1E`，
把白卡阴影 `rgba(0,0,0,.06)` 调成 `rgba(0,0,0,.4)`。注意自绘 SVG 里的色值是写死的，
深色版要一起改（见 `svg.md` 的配色表）。

## 换字体

`--font` 和 `--mono` 两个变量。全英文的 deck 把 `"PingFang SC"` 拿掉、
`"SF Pro Display"` 打头即可。用 Web 字体要在 `<head>` 里 `@font-face` 内嵌
base64，否则离线打开会掉回系统字体。

## 换画幅

模板是 16:9。要 16:10 或 4:3：

1. `#stage` 的 `width/height` 改成目标像素（如 `1920×1200`）。
2. JS 里 `fit()` 的 `Math.min(innerWidth/1920, innerHeight/1080)` 两个数字跟着改。
3. `render_preview.py` 的 `--window-size` 和拼图 tile 尺寸（`tw=480; th=270`）跟着改。

竖屏（1080×1920，手机端分享）同理，但 `.fig2` 两图并排、`.stats` 三列这些横向布局
要改成单列。

## 把页脚小字 / 底部注释行加回来

模板默认不放，因为一页只留小标 + 标题 + 图最干净。要的话把这两段加进 `<style>`：

```css
/* 底部一句注释 */
.note{margin-top:30px;font-size:29px;color:var(--muted);text-align:center;line-height:1.45}
.note b{color:var(--ink);font-weight:600}
/* 右下角出处小字 */
.src{position:absolute;right:128px;bottom:40px;font-family:var(--mono);
     font-size:17px;color:var(--faint);letter-spacing:.06em}
```

```html
<div class="note">一句话把这页的结论说完，<b>加粗关键词</b></div>
<div class="src">Fig.6 · Sec.IV-A · 估读</div>
```

加了 `.note` 的话，`.slide` 的下 padding 要从 96px 收到 84px，不然图会被挤矮。

## 常驻页码

模板里的 `#hud` 默认隐藏，按 `C` 才显示。想一直显示，把初始化末尾的
`hud.classList.add('show'); setTimeout(...)` 换成 `showCounter=true; hud.classList.add('show'); updateHud();`。

## 改键位

键盘处理集中在 `addEventListener('keydown', ...)` 一处，照着加分支即可。
模板默认**点击页面不翻页**（录屏时误触会跳页），点击只用来收起页面列表。确实想要点击翻页，
把 `addEventListener('click', ...)` 里的 `toggleNav(false);` 换成
`if(panel.classList.contains('open')){ toggleNav(false); return; } if(e.clientX/innerWidth<0.2) prev(); else next();`。

## 导出 PDF / 图片

- **PDF**：Chrome 里 `F` 全屏逐页 `Cmd+P` 不好用。用 `render_preview.py` 出单页 PNG，
  再 `python3 -c "from PIL import Image; ..."` 合成 PDF，或
  `img2pdf /tmp/deck-render/slide-*.png -o deck.pdf`。
- **单页高清图**（发社交媒体）：`--force-device-scale-factor=2` 重跑那一页。
- **视频**：直接录屏，这个框架就是为录屏设计的。

## 一个 deck 多页动画

`startAnim` 里的 `PH` 是全局一张表。多页动画时改成按页查：

```js
const PHMAP={ 21:[['a'],['a','b']], 34:[['x'],['x','y'],['x','y','z']] };  // 键是页序号（0 基）
// startAnim 里： const PH=PHMAP[slides.indexOf(sl)]; if(!PH) return;
```
