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

## 字号与颜色：用配色类，不写死色值

模板 CSS 给 `.sv` 里的元素准备了一组配色类，颜色全部引用 `:root` 变量——换主题（`data-theme="keynote"`）
或改一个变量，所有自绘图跟着变。**新画的图一律用类**，不要再写 `fill="#F5F5F7"` 这种写死的色值。

**五色语义**：一种颜色只代表一类模块，全篇一致，图上或 sub 里写图例。

| 类 | 变量 | 代表什么 |
|---|---|---|
| `b-io` | `--c-io` 暖灰 | 输入 / 输出 / 外部模块（原始图像、文本、LLM 整体） |
| `b-norm` | `--c-norm` 浅蓝 | Norm / 位置编码 / 编码器 / 从侧面注入的信息 |
| `b-cond` | `--c-cond` 浅紫 | 条件 / 时间步 / 调制 / 路由 / 参考模型 |
| `b-core` | `--c-core` 橙黄 | 核心机制本身（注意力、合并、采样、更新） |
| `b-ffn` | `--c-ffn` 浅绿 | FFN / 专家 / 输出头 / 奖励 |
| `b-lin` | `--c-linear` 浅橙 | 线性层 / 投影 / 普通计算 |

**其余元素**：

| 元素 | 写法 |
|---|---|
| 列头 / 分区标 | `<g class="t-lab">`（22px 等宽灰） |
| 框内主字 | `font-size="26~30" class="t-ink"`，重点框加 `font-weight="600"` |
| 框下标注（形状、数量） | `font-size="22~26" class="t-mute"`，要强调的那个用 `t-acc` |
| 这页的主角 | 在它的色块上再加 `hot`（强调色粗边框）——**一张图只有一个 hot** |
| 外挂 / 不确定的块 | `class="ext"`（卡片底 + 灰虚线边） |
| 箭头 | `<path class="ar" marker-end="url(#ar)">`；主线箭头 `class="ar acc" marker-end="url(#arB)"` |
| 行分隔线 | `class="sep"` |
| 警示 / 被否定的 | `style="fill:var(--bad)"`，一页最多一处 |

字号下限：**图内任何文字 ≥ 22px**（viewBox 宽 1600 时 SVG 字号 ≈ 屏幕像素）。块内只放模块名、编号、短标签，
不写句子——解释放 sub 和 talk。

## 四种画法

1. **同构多行**：每行一个方案 / 一篇论文，从左到右 `条件 → 模型 → 输出`，最右一列一句话结论，
   行间 `sep` 细线分隔。适合「把五个放在一起看」，也适合开头放一次、讲到对应段时再放一次。
2. **一条流水线**：上面一行步骤方块，下面一行每步的数字 / 配比。
3. **上下对照**：上行「常规做法」，下行「这篇的反常做法」，下行的关键块加 `hot`。
4. **柱状 / 折线**：自己用 `<rect>` `<polyline>` 画，别为一张图引图表库。轴标注 22px 灰。只是两三个数比大小的，直接用模板的 `.bars` 长度条页。

## 箭头：按块 id 自动连线，别手写坐标

手算 `x1 y1 x2 y2` 是箭头对不齐、扎进块里、穿过别的块的根源——块一挪、字一改，箭头就错位。
给块加 `id`，箭头只声明「从哪到哪」，模板 JS（`layoutArrows`）按块的实际位置算端点：

```html
<rect id="p6-in" class="b-io" x="60" y="230" width="220" height="80" rx="16"/>
<rect id="p6-model" class="b-core" x="580" y="222" width="240" height="96" rx="18"/>
<path data-from="p6-in" data-to="p6-model" class="ar" marker-end="url(#ar)"/>
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
    t.setAttribute('x',x);t.setAttribute('y',y);t.setAttribute('font-size',size);t.style.fill=fill;
    if(weight)t.setAttribute('font-weight',weight); if(anchor)t.setAttribute('text-anchor',anchor);
    t.textContent=s; g.appendChild(t);};
  rows.forEach((row,i)=>{
    const y=120+i*100;
    txt(0,y+8,row.name,26,'var(--ink)','600');
    row.cells.forEach((clean,k)=>{
      const r=document.createElementNS(NS,'rect');
      r.setAttribute('x',300+k*80); r.setAttribute('y',y-22);
      r.setAttribute('width',70); r.setAttribute('height',44); r.setAttribute('rx',10);
      r.setAttribute('class', clean ? 'b-core hot' : 'ext');   // 用配色类，换主题时跟着变
      g.appendChild(r);
    });
    txt(800,y+8,row.note,22,'var(--muted)');
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

## 分步高亮页：图先全出，再逐项高亮

规则：**图一出现就是完整的**，按 `J` 只是把高亮移到下一项，不是让元素一批批冒出来。
说明文字（右侧 `.stepcol`）跟着高亮走，不能先于它描述的那部分图。

- 每一组要一起高亮的元素包一层 `<g data-a="名字">`；当前步的组加 `.on`，里面的 `rect` 换成强调色粗边框，`text` 变强调色。
  不在当前步的元素照常显示，不变淡、不隐藏。
- 那一页的 `svg` 加 `data-anim`，右侧 `.stepcol` 里每步一个 `.step-item`（`<b>` 标题 + 一句这步解决什么）。
- 脚本顶部 `const PH=[ [], ['s1'], ['s2'], ['s3'] ]`：第 0 项是「全图、无高亮」（翻到这页时的状态），
  第 k 项是第 k 步要高亮的名字，同时右侧第 k 个 `.step-item` 变成当前项。步数由 `PH.length` 决定。
- **不自动播**：`J` 下一步、`K` 上一步，到底再按 `J` 回到全图。地址栏 `?anim=2#14` 直接停在第 2 步（截图用）。
- 步数 3–6 步。
- 一个 deck 里多页分步时，`PH` 要按页取——把表做成 `{页序号: PH}` 的字典，
  在 `startAnim` 里按 `slides.indexOf(sl)` 查（见 `customize.md`）。

## 两个必踩的坑

- **`<marker>` 定义放全局**：`#stage` 开头那个 `width="0" height="0"` 的 svg 里。放进某一页的 svg，
  那页 `display:none` 时所有页的箭头会一起消失。
- **`.diagbox.pad` 的留边**只能写 `inset:0;margin:auto;width:calc(100% - 88px);height:calc(100% - 68px)`。
  写成 `inset:34px 44px` + `width:100%` 的话，右边距被顶掉、图向右溢出 44px——顶到边框的图会暴露这个问题。
