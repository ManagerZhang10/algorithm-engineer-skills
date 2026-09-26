# 上游来源

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

改动 2–5 是本人使用偏好，不代表上游立场，上游不一定会接受。

## 许可证处理

上游 MIT 允许修改和再分发，条件是保留版权与许可声明。本目录保留上游 `LICENSE` 原文；
本仓库根目录的 MIT 只覆盖本地新增和修改的部分。
