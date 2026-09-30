# manager-zhang-skills

个人 Agent Skill 仓库，沉淀反复用得上的写作、思考与协作技能。每个技能是一个自包含目录，
放 `SKILL.md`（指令与元数据）加可选的 `references/`（按需加载的长参考）。

同一份 `SKILL.md` 同时供 Claude Code 和 Codex 使用；`agents/openai.yaml` 只是 Codex 侧的
展示与调用配置，不影响技能内容本身。

## 技能索引

### 写作

| # | 技能 | 做什么 | 什么时候触发 | 参考文件 |
| --- | --- | --- | --- | --- |
| 1 | [weekly-review-authoring](skills/weekly-review-authoring/SKILL.md) | 先建证据清单再写周报，把周报写成职业证据而不是活动流水账 | 写周报、整理本周进展、Review 周报草稿 | [写作标准](skills/weekly-review-authoring/references/weekly-review-standard.md) |
| 2 | [architecture-plan-authoring](skills/architecture-plan-authoring/SKILL.md) | 按讲述时长冻结正文预算，先串文字主线再用图压缩表达 | 架构规划、技术规划、方案汇报、路线提案 | [交付物模式](skills/architecture-plan-authoring/references/deliverable-modes.md)、[审查量表](skills/architecture-plan-authoring/references/review-rubric.md) |
| 3 | [internship-reporting](skills/internship-reporting/SKILL.md) | 按五层框架将已有材料组织为实习 / 转正汇报 | 实习总结、转正汇报、晋升材料、45 分钟汇报模板 | [五层框架](skills/internship-reporting/references/five-level-reporting.md)、[45 分钟模板](skills/internship-reporting/references/45-minute-internship-report-template.md) |

### 讲解幻灯片

| # | 技能 | 做什么 | 什么时候触发 | 参考文件 |
| --- | --- | --- | --- | --- |
| 4 | [kelip-slide](skills/kelip-slide/SKILL.md) | 用单文件 HTML 做 keynote 风讲解 deck：15 种页型模板、自绘 SVG 箭头自动连线与穿块检查、代码解读页（左代码色块 + 右同色注释卡）、渲染自查 | 做 / 改 HTML deck、slides、讲解 PPT、录屏分享页 | [自绘 SVG](skills/kelip-slide/references/svg.md)、[素材处理](skills/kelip-slide/references/media.md)、[改造](skills/kelip-slide/references/customize.md)、[来源](skills/kelip-slide/UPSTREAM.md) |
| 5 | [deck-portrait](skills/deck-portrait/SKILL.md) | 横屏 HTML deck 自动重排成竖屏 3:4 PNG：页面上的文字块改竖排，图整张保留原结构，图里字太小时追加带小地图的局部放大页，逐页量字号出自查报告 | 横屏 deck 手机上字太小、要导成小红书竖图 | 脚本在 `scripts/`（零依赖，Node ≥ 22 + Chrome） |
| 6 | [paper-arch-figure](skills/paper-arch-figure/SKILL.md) | 论文风神经网络架构图：任意结构（block 堆叠、编码器-解码器、多阶段流水线、小图），统一五色语义风格，默认论文式三段放大、主干自下而上，有金样板可对照；先从源码取证记行号，再用 Python spec 生成可编辑 draw.io，导出 SVG / PNG 并按显示宽度自查字号 | 画模型架构图、把 block 内部画出来、重画论文结构图 | [取证](skills/paper-arch-figure/references/fact-sourcing.md)、[版式 API](skills/paper-arch-figure/references/layouts.md)、[样式](skills/paper-arch-figure/references/style.md)、[经典图画法](skills/paper-arch-figure/references/classic-figures.md)；脚本在 `scripts/`（Python 标准库 + draw.io 桌面版） |
| 7 | [lecture-video-cut](skills/lecture-video-cut/SKILL.md) | ScreenKite 录屏的 ffmpeg 剪辑流水线：麦克风静音去气口、文字锚点删卡壳重说段、逐字高亮 ASS 字幕、右下圆形摄像头、鼠标光标高亮与点击闪光；draft 草片 / final 与源同分辨率两档，每次出片附带字幕审阅 md 标出剪切接缝 | 剪 ScreenKite 录的讲解视频、去气口、加字幕、叠摄像头、高亮鼠标 | [转写术语修正](skills/lecture-video-cut/references/asr-term-fixes.md)；脚本在 `scripts/`（Python 标准库 + ffmpeg/libass） |

### 内容提取

| # | 技能 | 做什么 | 什么时候触发 | 参考文件 |
| --- | --- | --- | --- | --- |
| 5 | [xiaohongshu-content-extraction](skills/xiaohongshu-content-extraction/SKILL.md) | 将公开小红书笔记、长图或截图转成带来源边界的可编辑 Markdown | 给出小红书链接、长图或截图，要求提取原文、OCR 或转写 | — |

### 工程诊断

| # | 技能 | 做什么 | 什么时候触发 | 参考文件 |
| --- | --- | --- | --- | --- |
| 6 | [pelican-proxy-check](https://github.com/ManagerZhang10/pelican-proxy-check) ↗ | 让多条「模型 x 通道」画同一张鹈鹕骑自行车 SVG 并出并排看板，同时量出 input token 注入与思考 token 抑制 | 怀疑 API 中转层降级、偷塞隐藏 system prompt 或关掉思考；横评几家模型的出图能力 | **住在独立仓库**，装法见该仓库 README |

### 思考

| # | 技能 | 做什么 | 什么时候触发 | 参考文件 |
| --- | --- | --- | --- | --- |
| 3 | [question-clarifying](skills/question-clarifying/SKILL.md) | 用苏格拉底式问诊把模糊困惑收敛成一个准确、值得回答的问题 | 说不清自己想问什么、问题描述发散、要求先别给建议 | [复制版模板](skills/question-clarifying/references/prompt-template.md) |
| 4 | [unfamiliar-topic-learning](skills/unfamiliar-topic-learning/SKILL.md) | 按需求选定双层解释、反向拆解、横纵分析或事实核查 | 听不懂某个概念、想拆解好范例、想系统研究一个领域、怀疑一份材料 | [四种方法模板](skills/unfamiliar-topic-learning/references/prompt-templates.md) |
| 5 | [problem-solving-lenses](skills/problem-solving-lenses/SKILL.md) | 先换视角再给方案：专家会诊、第一性原理、跨领域借解 | 方案越修越复杂、问题跨多个专业、本行业解法都试过无效 | [三种视角模板](skills/problem-solving-lenses/references/prompt-templates.md) |
| 6 | [decision-stress-testing](skills/decision-stress-testing/SKILL.md) | 把两个选项都论证到最强；推演失效时改用最小实验取现实数据 | 两条路都有道理、反复权衡拿不定主意、想验证一个想法值不值得做 | [两个方法模板](skills/decision-stress-testing/references/prompt-templates.md) |
| 7 | [self-understanding-interview](skills/self-understanding-interview/SKILL.md) | 深度访谈：往回看找底层天赋，往前看给三个五年版本和原型行动 | 想搞清自己擅长什么、怀疑自己没天赋、在考虑职业或人生方向转变 | [天赋挖掘](skills/self-understanding-interview/references/talent-discovery.md)、[人生设计](skills/self-understanding-interview/references/life-design.md) |

## 技能之间的分工

### 三个写作技能

都是写作技能，但解决的问题不同，不要混用：

- **周报**面向自己和主管。核心是结果、证据、影响和支援请求，
  验收标准是「离职后这条能不能不重新考古就写进简历」。
- **架构规划**面向听众。核心是一条能被口头复述的因果链，
  正文长度由有效讲述时长反推，验收标准是「讲述者能不能脱稿复述主线并回答质疑」。
- **实习汇报**面向实习总结、转正或晋升场景。核心是把项目从工作交付逐步组织为方法、全局判断、角色定位和可信的增量价值；验收标准是「听众能说出共同主线、个人贡献和下一步」。

### 讲解幻灯片与竖屏导出

- **kelip-slide** 负责做和改横屏 deck 本身，内容、页型、自绘图都在这里定。
- **deck-portrait** 只接已经做好的 deck，不改内容，只按竖屏重排并导出 PNG；竖屏里某页不好看，先在它的 `portrait.json` 里微调，仍不行再回 kelip-slide 改原页。
- **paper-arch-figure** 只负责模型架构图这一种图，产出可编辑的 draw.io 和 SVG / PNG；图做好后作为素材放进 kelip-slide 的一图页。kelip-slide 自带的自绘 SVG 适合流程和示意，block 级的模型结构用这个。

### 小红书图文转写与实习汇报

- **小红书图文转写**只负责忠实提取公开笔记的正文和图片文字，并标明来源与不确定处；它不改写观点，也不生成汇报。
- **实习汇报**只接受已有的可编辑材料，负责形成汇报故事、五层诊断和模板；原始小红书图文应先由“小红书图文转写”转为材料，再交给它。

### 五个思考技能

按“问题处在哪一步”分工，串起来是一条从困惑到行动的链，单个也能独立用：

| 处境 | 用哪个 |
| --- | --- |
| 还说不清要问什么 | `question-clarifying` |
| 知道要问什么，但不懂 | `unfamiliar-topic-learning` |
| 懂了，但方案想不出来或想不好 | `problem-solving-lenses` |
| 方案有两个，选不出来 | `decision-stress-testing` |
| 卡的其实不是这件事，是方向 | `self-understanding-interview` |

最容易混的是前两个和第四个：`question-clarifying` 是**还没有答案**时把问题问对，
`decision-stress-testing` 是**已有两个答案**时选一个，底层目的不同，不要互相替代。

## 共享的一条纪律

**不把未验证的判断写成事实。**

- 周报里体现为区分已验证事实、本人判断和待验证假设；
- 架构规划里体现为「零上下文读者测试」——隐藏聊天记录和作者解释，只让审阅者读当前正文；
- 五个思考技能里体现为事实、推断、观点分开写，证据不足时写「暂未核实」，
  以及所有关于用户本人的判断都必须对应他讲过的具体经历。

## 安装

技能目录直接软链或复制到 Agent 的技能目录即可，不需要构建步骤。

```bash
git clone https://github.com/ManagerZhang10/manager-zhang-skills.git
cd manager-zhang-skills

# Claude Code（用户级）：按需挑，或者全装
for s in skills/*/; do ln -s "$PWD/$s" ~/.claude/skills/; done

# Codex
for s in skills/*/; do ln -s "$PWD/$s" ~/.codex/skills/; done
```

只装某一个就单独链那一个目录，例如：

```bash
ln -s "$PWD/skills/decision-stress-testing" ~/.claude/skills/
```

项目级安装把链接放进 `<repo>/.claude/skills/` 即可。

带命令行脚本的技能可以顺手把入口链进 PATH，例如：

```bash
ln -s "$PWD/skills/paper-arch-figure/scripts/archfig.py" ~/.local/bin/archfig
```

## 来源与边界

- 两个写作技能（`weekly-review-authoring`、`architecture-plan-authoring`）由本人编写。
  公开前做过脱敏：去掉了真实姓名、本机绝对路径和内部项目代号。方法论部分未做删减。
- 五个思考技能改编自一篇公开发表的公众号文章里的 12 个提示词，**不是本人原创方法**。
  每个技能目录下的 `UPSTREAM.md` 写明了出处、取得日期、本地改了什么，
  以及上游许可证状态（原文未声明授权条款，状态为不确定）。使用前请先读该文件。
- `kelip-slide` 派生自 [skJack/kelip-slide](https://github.com/skJack/kelip-slide)（MIT，上游 `LICENSE` 原样保留在该目录）。
  本地加了箭头自动连线与穿块检查（已提回上游 PR #1）、去掉收尾页、点击不翻页，
  以及「代码解读页」页型；逐条改动见该目录 `UPSTREAM.md`。
- `pelican-proxy-check` 由本人编写，**已拆成独立仓库**
  [ManagerZhang10/pelican-proxy-check](https://github.com/ManagerZhang10/pelican-proxy-check)，
  这里不再保留副本（一份代码两个地方维护迟早不同步）。所用题面
  「Generate an SVG of a pelican riding a bicycle」是 Simon Willison 2024 年起的公开非正式基准，
  沿用原版措辞以保持与公开对比图可比。脚本只用 Python 标准库；泳道配置含密钥，
  放在仓库外的 `~/.config/` 下，仓库内只有样例。
- 周报的六模块字段名和架构规划的三色配色**保留为默认模板**，
  都可以整体替换成你所在组织的字段和品牌色；替换字段不影响其余写作标准。
- 这些技能是按本人的工作场景打磨的，不是通用最佳实践。直接套用前先看它假设了什么。

## License

[MIT](LICENSE) —— 覆盖本仓库本地编写的内容。改编自第三方材料的技能另见其目录下的
`UPSTREAM.md`，MIT 不代表已获得上游的再许可授权。
