# 给 AI Agent 的说明

这个目录是 **tech-talk-deck**：一套做技术讲解幻灯片的模板和规范（基于 skJack/kelip-slide 改造，原名 kelip-slide）。
单文件 HTML，1920×1080，暖纸底 + 赭橙强调，一页一个主体块，Chrome 打开键盘翻页。

要做、改、检查幻灯片（deck / slides / keynote / 讲解 PPT / 分享页面）时：

1. **先读 `SKILL.md`**，按它的版式系统、写页硬规则和流程做，不要自己另起一套 CSS。
2. 从 `assets/deck-template.html` 复制模板，里面 15 种页型各有一个填好的示例页。
3. **写页硬规则**（`SKILL.md`「每页怎么写」）第一版就照做：标题先目的后做法、结论先行、图先全出再逐项高亮、
   页上不写自我批判和免责声明、数字画成图不做数字卡、符号当页定义。理由见 `references/style.md`。
4. **图页 `.sub` 必填，每个内容页末尾必有 `.talk` 讲稿块**——deck 是发出去看的，没人讲解。
5. **讲代码的页一律用「代码解读页」**（`.cx`：左代码色块、右同色注释卡、上下顺序对齐）。
6. **改完必须截图自己看一遍再交付，但只截改过的页**：`assets/render_pages.sh <页码...>`。
   整本 `render_preview.py` 只在新 deck 首次搭完或用户要求全量时前台跑一次。
   有自绘 SVG 的再跑 `assets/check_arrows.py deck.html`，✗ 全部改掉。
7. 自绘机制图看 `references/svg.md`（配色用类，不写死色值），素材处理看 `references/media.md`，
   换主题 / 配色 / 画幅看 `references/customize.md`。

`SKILL.md` 里标了「建议」的内容规则是默认值，项目自己的风格约定优先。
