# 给 AI Agent 的说明

这个目录是一套**做讲解幻灯片的模板和规范**：单文件 HTML，1920×1080，一页一个主体块，
Chrome 打开键盘翻页。

要做、改、检查幻灯片（deck / slides / 讲解 PPT / 分享页面）时：

1. **先读 `SKILL.md`**，按它的版式系统和流程做，不要自己另起一套 CSS。
2. 从 `assets/deck-template.html` 复制模板，里面 15 种页型各有一个填好的示例页。
3. **排完必须跑 `assets/render_preview.py` 把每页渲染成图，自己看一遍再交付**——
   版式问题（图顶边、白卡空一半、表格挤成一团）只有看图才发现得了。
   有自绘 SVG 的再跑 `assets/check_arrows.py deck.html`，✗ 全部改掉。
4. **讲代码的页一律用「代码解读页」**（`.cx`：左代码色块、右同色注释卡、上下顺序对齐），规则在 `SKILL.md`。
5. 需要自绘机制图看 `references/svg.md`，处理素材看 `references/media.md`，
   改配色 / 画幅 / 加回页脚小字看 `references/customize.md`。

`SKILL.md` 里标了「建议」的内容规则是默认值，项目自己的风格约定优先。
