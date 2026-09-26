# 自绘 SVG

现成的图讲不清机制的时候自己画。实测比例：讲论文的 deck 42 页里 8 页自绘；
讲产品 / 新闻 / 自家工作的 deck 42 页里 16 页自绘——**没有现成图可用时，自绘是主力**。

## 坐标系：viewBox 宽 1600，SVG 里的字号就是屏幕像素

白卡（`.diagbox.pad`）里的可用区域 ≈ 1576 × 650（1920 减两边 128 padding，再减内边距）。所以：

```html
<div class="diagbox pad"><svg class="sv" viewBox="0 0 1600 560"
     xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet">
```

- **viewBox 用 `1600 × 540~600`**，内容宽的用 `1760 × 640`。缩放比接近 1:1，
  写 `font-size="22"` 屏幕上就是 22px，和页面其它字号自然对齐。
- `preserveAspectRatio="xMidYMid meet"` 必须写，否则窄图会被拉伸。
- `class="sv"` 给 `<text>` 套上中文字体；等宽数字再加 `class="mono"`。

## 字号与颜色

照抄这张表，图和页面就是一套东西：

| 元素 | 写法 |
|---|---|
| 列头 / 分区标 | `font-size="20" fill="#6E6E73" font-weight="500" letter-spacing="2"` |
| 行标题（方案名 / 论文名） | `font-size="30" font-weight="600" fill="#1D1D1F"` + 下面一行 `20` 灰日期 |
| 框内主字 | `font-size="22~24" fill="#1D1D1F"`，重点框 `font-weight="600"` |
| 框内副字 | `font-size="17~19" fill="#6E6E73"` |
| 普通方块 | `rx="14~16" fill="#F5F5F7"` |
| 重点方块（这页的主角） | `fill="#E8F0FE" stroke="#0071E3" stroke-width="2"`，字 `fill="#0071E3"` |
| 外挂 / 不确定的块 | `fill="#FFFFFF" stroke="#A1A1A6" stroke-width="2" stroke-dasharray="7 5"` |
| 箭头 | `stroke="#8E8E93" stroke-width="3" marker-end="url(#ar)"`；蓝箭头 `url(#arB)` |
| 行分隔线 | `stroke="#E5E5EA" stroke-width="1.5"` |
| 警示 / 被否定的 | `#D0342C`，一页最多一处 |

换了 `--accent` 的话，蓝块那两个色跟着换：强调色本身 + 它 12% 透明度的浅底
（`#0071E3` 对应的浅底是 `#E8F0FE`）。

一张图里**只让一件事是强调色**——这页要讲的那个。其余全灰。

## 四种画法

1. **同构多行**：每行一个方案 / 一篇论文，从左到右 `条件 → 模型 → 输出`，最右一列一句话结论，
   行间 `#E5E5EA` 细线分隔。适合「把五个放在一起看」，也适合开头放一次、讲到对应段时再放一次。
2. **一条流水线**：上面一行步骤方块，下面一行每步的数字 / 配比。
3. **上下对照**：上行「常规做法」，下行「这篇的反常做法」，下行用强调色。
4. **柱状 / 折线**：自己用 `<rect>` `<polyline>` 画，别为一张图引图表库。轴标注 20px 灰。

## 箭头：按块 id 自动连线，别手写坐标

手算 `x1 y1 x2 y2` 是箭头对不齐、扎进块里、穿过别的块的根源——块一挪、字一改，箭头就错位。
给块加 `id`，箭头只声明「从哪到哪」，模板 JS（`layoutArrows`）按块的实际位置算端点：

```html
<rect id="p6-in" x="60" y="230" width="220" height="80" rx="16" fill="#F5F5F7"/>
<rect id="p6-model" x="580" y="222" width="240" height="96" rx="18" fill="#F5F5F7"/>
<path data-from="p6-in" data-to="p6-model" stroke="#8E8E93" stroke-width="3" marker-end="url(#ar)"/>
```

- 必须用 `<path>`（JS 写它的 `d`），不用 `<line>`。`id` 在同一个 svg 里唯一即可，建议加页号前缀。
- `id` 挂在 `<rect>` 上；没有框的纯文字标签，把几行 `<text>` 包进 `<g id>`，按整组的包围盒连。
- `data-route` 选走法：

| 值 | 走法 | 什么时候用 |
|---|---|---|
| 不写（`auto`） | 两块左右错开且上下有重叠 → 水平直线；上下错开且左右有重叠 → 竖直直线；否则斜线 | 大多数情况 |
| `hv` / `vh` | 先横后竖 / 先竖后横的直角折线，落在目标块边的中点 | 目标在斜对角，又不想要斜线 |
| `hvh` + `data-mid="x"` | 横 → 在 x 处竖 → 横 | 中间有块挡路，从旁边绕 |
| `vhv` + `data-mid="y"` | 竖 → 在 y 处横 → 竖 | 从上方 / 下方绕过一排块 |
| `straight` | 两块中心连线，裁到边框 | 扇入扇出的斜线 |

- 直线优先对准终点块的中线，其次起点块的中线；两个都对不上说明**块本身没对齐**，去改块的 y / x，
  别去挪箭头。
- `data-gap1` / `data-gap2` 是尾部 / 头部离块的距离，默认 6 / 8。
- 自动连线不会自己躲障碍：画完跑 `check_arrows.py deck.html`，报「穿过块」就换 `data-route` 绕开。

改旧 deck 时，手写的 `<line>` 箭头不用全改，先跑 `check_arrows.py`，只把报错的那几根换成自动连线。

## 重复元素用 JS 生成

八个候选框、五行 token、九个百分比——不要手写 80 个 `<rect>`。留一个空的 `<g id="rows">`，
用表驱动生成，改数据不用重算坐标：

```html
<div class="diagbox pad"><svg class="sv" viewBox="0 0 1600 560" ...>
  <g id="modeRows"></g>
</svg></div>
<script>
(function(){
  const g=document.getElementById('modeRows'); if(!g) return;
  const NS='http://www.w3.org/2000/svg';
  const rows=[
    {name:'图生视频', cells:[1,0,0,0,0], note:'首帧干净，续写后面的帧'},
    {name:'策略',     cells:[1,0,0,0,0], note:'只有首帧干净，其余一起去噪'},
  ];
  const txt=(x,y,s,size,fill,weight,anchor)=>{const t=document.createElementNS(NS,'text');
    t.setAttribute('x',x);t.setAttribute('y',y);t.setAttribute('font-size',size);t.setAttribute('fill',fill);
    if(weight)t.setAttribute('font-weight',weight); if(anchor)t.setAttribute('text-anchor',anchor);
    t.textContent=s; g.appendChild(t);};
  rows.forEach((row,i)=>{
    const y=120+i*100;
    txt(0,y+8,row.name,24,'#1D1D1F','600');
    row.cells.forEach((clean,k)=>{
      const r=document.createElementNS(NS,'rect');
      r.setAttribute('x',300+k*80); r.setAttribute('y',y-22);
      r.setAttribute('width',70); r.setAttribute('height',44); r.setAttribute('rx',10);
      if(clean){ r.setAttribute('fill','#E8F0FE'); r.setAttribute('stroke','#0071E3'); r.setAttribute('stroke-width','2'); }
      else { r.setAttribute('fill','#F5F5F7'); r.setAttribute('stroke','#A1A1A6');
             r.setAttribute('stroke-width','2'); r.setAttribute('stroke-dasharray','6 4'); }
      g.appendChild(r);
    });
    txt(800,y+8,row.note,18,'#6E6E73');
  });
})();
</script>
```

同一张总图要在两处各出现一次时，**别复制 HTML**，用 JS 拷贝：

```js
const src=document.querySelectorAll('.slide')[2].querySelector('svg');
const dst=document.getElementById('overviewCopy');
if(src&&dst) dst.innerHTML=src.innerHTML;    // 以后只改第一处
```

## 分步动画页

- 每一组要一起点亮的元素包一层 `<g data-a="名字">`；CSS 里默认 `opacity:.08`，加 `.on` 变 1。
- 那一页的 `svg` 加 `data-anim`，右侧 `.stepcol` 里每步一个 `.step-item`。
- 脚本顶部改 `const PH=[['a'],['a','b'],['a','b','c']]`——第 k 项是第 k 步要亮的名字集合，
  步数由 `PH.length` 决定。
- **不自动播**：翻到这页停在第 1 步，`J` 下一步、`K` 上一步，到底再按 `J` 回第 1 步。
  地址栏 `?anim=3#22` 可以直接停在第 4 步（截图用）。
- 步数控制在 4–6 步，右侧每步一句话（`<b>` 标题 + 一行说明）。
- 一个 deck 里多页动画时，`PH` 要按页取——简单做法是把表做成 `{页序号: PH}` 的字典，
  在 `startAnim` 里按 `slides.indexOf(sl)` 查。

## 两个必踩的坑

- **`<marker>` 定义放全局**：`#stage` 开头那个 `width="0" height="0"` 的 svg 里。放进某一页的 svg，
  那页 `display:none` 时所有页的箭头会一起消失。
- **`.diagbox.pad` 的留边**只能写 `inset:0;margin:auto;width:calc(100% - 88px);height:calc(100% - 68px)`。
  写成 `inset:34px 44px` + `width:100%` 的话，右边距被顶掉、图向右溢出 44px——顶到边框的图会暴露这个问题。
