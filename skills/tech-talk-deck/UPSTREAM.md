# 上游来源

本 skill **基于 skJack/kelip-slide（MIT）改造，原名 kelip-slide**；2026-10 起改名 `tech-talk-deck`，
因为视觉和写页规则已经换成作者自己的风格，和上游的苹果 keynote 风差别较大。

## 来源

- **类型**：公开 GitHub 仓库。
- **出处**：[skJack/kelip-slide](https://github.com/skJack/kelip-slide)
- **取得方式**：2026-09-25 clone，基线为上游 `main` 的 `ab4d15a`（2026-09-23）。
- **上游许可证**：MIT，版权 `Copyright (c) 2026 skJack`。原始 `LICENSE` 文件原样保留在本目录。

## 本地改了什么

按时间先后：

1. **箭头自动连线 + 对齐/穿块检查**（已作为
   [skJack/kelip-slide#1](https://github.com/skJack/kelip-slide/pull/1) 提回上游，截至 2026-09-26 未合并）：
   - `assets/deck-template.html` 新增 `layoutArrows`：块加 `id`，箭头写 `<path data-from data-to>`，
     端点按块实际位置现算；`data-route` 支持 `hv` / `vh` / `hvh` / `vhv` / `straight`，`data-mid` 绕障。
   - 新增 `assets/check_arrows.py`：headless Chrome 逐页量箭头，报悬空 / 扎进块 / 打偏 / 穿块。
   - `references/svg.md`、`SKILL.md`、`README.md`、`AGENTS.md` 补用法，自查回路加这一步。
2. **去掉「收尾页」页型**（15 → 14）：最后一页就是最后一个有内容的点，不做小结 / 谢谢页。
3. **点击页面不翻页**：录屏误触会跳页，点击只用来收起页面列表；`references/customize.md` 写了怎么改回去。
4. **新增「代码解读页」页型 `.cx`**（14 → 15）：左边代码按段落色块高亮（蓝 / 橙 / 绿 / 紫），
   右边同色注释卡，色块从上到下的顺序与卡片顺序一一对应。`SKILL.md` 把它定为硬规则：
   凡是讲代码的页都用这种排法。样式取自本人一份实际 deck。
5. **定位从「录屏讲解」改为「直接分享」**：图页 `.sub` 必填（这张图看哪里），每个内容页末尾加
   `.talk` 讲稿块（把口头要讲的 2–4 句写在页上），模板 CSS 内置；`SKILL.md` 定为硬规则。
6. 安装说明改指向本仓库；示例图 `assets/page-types.png` 按 15 种页型重新渲染。

7. **视觉换成暖纸风，并改名 `tech-talk-deck`**（2026-10）：
   - 模板默认配色换成盲测选出的暖纸底 `#F3EFE6` + 120px 浅网格 + 墨字 + 赭橙强调 `#C2410C`，kicker 改等宽强调色；
     全部组件（含导航面板、箭头 marker）改为引用 `:root` 变量。上游浅灰风保留为备选主题 `data-theme="keynote"`。
   - 新增图示五色语义变量 `--c-io/linear/core/ffn/norm/cond` 和自绘 SVG 配色类（`b-core`、`hot`、`ar`、`t-mute`……），
     `references/svg.md` 的配色表和示例代码改成用类、不写死色值。
   - 字号整体大一档：讲稿 26px、图内文字 ≥ 22px；代码 18px，代码解读页上限改为 18 行。
   - 「数字卡」页型 `.stats` 换成「长度条」`.bars`（数字画成长度）；内置 `.src` 出处小字和 `.eq` 公式排版。
   - 「分步动画」改成「分步高亮」：图一开始就完整画出，`J`/`K` 只移动高亮（`PH[0]` 为全图无高亮），不再让元素逐个冒出。
   - 封面改为「大字 + 右侧一张代表图」，底部图条保留为可选；过渡页加一句「这一段要解决什么」。
   - 示例页内容换成一条连贯的例子（图像怎么变成 token），示范「先目的后做法」的标题写法；
     附三张猫图示例素材 `assets/media/`，`assets/page-types.png` 重新渲染。
   - `SKILL.md` 新增「每页怎么写（硬规则）」十条：标题先目的后做法（目的 → 限制 → 做法 → 效果）、结论先行、
     图先全出再逐项高亮、不写自我批判和免责声明、数字画成图、当页定义、多用真实素材、颜色语义一致、
     每页只留独有信息、读者追问即改页。理由和正反例放新增的 `references/style.md`。
   - frontmatter `name`、description、README、AGENTS.md、`agents/openai.yaml` 随改名更新。

改动 2–5、7 是本人使用偏好，不代表上游立场，上游不一定会接受。

## 许可证处理

上游 MIT 允许修改和再分发，条件是保留版权与许可声明。本目录保留上游 `LICENSE` 原文；
本仓库根目录的 MIT 只覆盖本地新增和修改的部分。
