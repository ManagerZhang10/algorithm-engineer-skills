# 改造模板

框架固定的只有「1920×1080 舞台 + 一页一个主体块 + JS 图卡自适应」。其余都能改，
下面是几件最常改的。改完都跑一遍渲染自查。

## 换主题 / 配色

模板自带两套主题，全部组件（包括自绘图的配色类、箭头 marker、导航面板）都引用 `:root` 变量：

| 主题 | 怎么开 | 样子 |
|---|---|---|
| 暖纸（默认） | 什么都不写 | 暖纸底 `#F3EFE6` + 120px 浅网格、墨字、赭橙强调 `#C2410C`、等宽 kicker |
| keynote（上游原版） | `<html lang="zh-CN" data-theme="keynote">` | 浅灰底 `#F5F5F7`、无网格、苹果蓝强调 `#0071E3` |

只想换颜色，改 `:root` 里这几行就够：

```css
:root{
  --bg:#F3EFE6;    /* 页面底色 */
  --ink:#1C1B19;   /* 正文 */
  --muted:#6E685E; /* 次要文字、注释 */
  --faint:#9A9387; /* 更淡的一层：页码、出处小字 */
  --line:#D9D2C3;  /* 分隔线、表格线 */
  --card:#FBF8F2;  /* 卡片底 */
  --accent:#C2410C;/* 唯一强调色 —— 换品牌色改这一行，再改下一行的浅底 */
  --accent-soft:#C2410C1F; /* 强调色 12% 透明度：高亮行、当前项 */
  --grid:#1C1B1914;/* 舞台网格线；不要网格写 transparent */
}
```

五色语义（`--c-io` … `--c-cond`）是图示模块的底色，换主题时一般不用动；要动就整组换，保证
六种颜色彼此一眼分得开、和 `--accent` 也分得开。

深色版：`--bg` 换 `#141311`、`--ink` 换 `#F3EFE6`、`--muted` 换 `#A8A196`、`--card` 换 `#1F1D1A`、
`--line` 换 `#3A3631`、`--grid` 换 `#F3EFE60F`，`--shadow` 调成 `0 14px 48px rgba(0,0,0,.4)`；
五色语义整体压暗一档。自绘图用的是配色类，会跟着变；写死色值的老图要手改。

## 换字体

`--font` 和 `--mono` 两个变量。全英文的 deck 把 `"PingFang SC"` 拿掉、
`"SF Pro Display"` 打头即可。用 Web 字体要在 `<head>` 里 `@font-face` 内嵌
base64，否则离线打开会掉回系统字体。

## 换画幅

模板是 16:9。要 16:10 或 4:3：

1. `#stage` 的 `width/height` 改成目标像素（如 `1920×1200`）。
2. JS 里 `fit()` 的 `Math.min(innerWidth/1920, innerHeight/1080)` 两个数字跟着改。
3. `render_preview.py` 的 `--window-size` 和拼图 tile 尺寸（`tw=480; th=270`）跟着改。

竖屏（1080×1920，手机端分享）同理，但 `.fig2` 两图并排、`.cx` 代码解读这些横向布局
要改成单列。

## 右下角出处小字

模板已内置 `.src`（右下角 20px 等宽灰字），需要时在页里加一行：

```html
<div class="src">Fig.6 · Sec.IV-A · 估读</div>
```

不想要讲稿块（比如确实要录屏）就把每页的 `.talk` 删掉，CSS 留着无害。

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
- **视频**：直接录屏，`F` 全屏后整页就是画面。

## 一个 deck 多页分步高亮

`startAnim` 里的 `PH` 是全局一张表。多页分步时改成按页查（每张表第 0 项都是 `[]`，即全图无高亮）：

```js
const PHMAP={ 21:[[],['a'],['b']], 34:[[],['x'],['y'],['z']] };  // 键是页序号（0 基）
// startAnim 里： const PH=PHMAP[slides.indexOf(sl)]; if(!PH) return;
```
