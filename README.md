# Algorithm Engineer Skills · 算法工程师的 Agent Skills

[中文](#中文) · [English](#english)

<a id="中文"></a>

给算法工程师用的 Agent Skill 合集，同一份 `SKILL.md` 在 Claude Code 和 Codex 里都能用。

现有的公开 skill 大多集中在写论文、读论文和全自动科研。这里补的是研发中间那段天天要做的活：
多个模型怎么比才公平、一大批图怎么送进 VLM、论文怎么快速读出带页码的结论、实验结论怎么讲给别人听。
每个 skill 都来自作者日常工作里反复做过的事，踩过的坑写成了规则。

每个技能是 `skills/` 下一个自包含目录：`SKILL.md`（指令与元数据），加可选的 `references/`
（按需加载的长参考）和 `scripts/`（可直接运行的脚本）。`agents/openai.yaml` 只是 Codex 侧的展示配置。

## 技能索引

### 评测与实验

| 技能 | 做什么 | 什么时候用 |
| --- | --- | --- |
| [fair-eval-protocol](skills/fair-eval-protocol/SKILL.md) | 横向对比前先把「怎么比」定死：输入按字节冻结并哈希、统一尺寸和解码参数、只在所有臂都成功的交集上算分、失败按类型单列、先读原始输出再起量。附 `freeze_manifest.py` 和 `intersect.py` | 比较模型、checkpoint、API 供应商、prompt 版本；LLM / VLM / Agent / 文生图 / 图像编辑都适用 |
| [batch-vlm-requests](skills/batch-vlm-requests/SKILL.md) | 一批图片送多模态 API：内联 base64 还是 URL、走 batch 还是实时、先估成本再用真实 usage 校准、冻结实际提交的请求字节、按 ID 收结果并区分空输出 / 截断 / 拒答。附构建、估算、并发发送、汇总四个脚本 | 批量打标、蒸馏、LLM-as-judge、多 teacher 对比 |
| [edit-drift-eval](skills/edit-drift-eval/SKILL.md) | 图像编辑模型多轮漂移评测：同一张图、同一串 prompt 连改 K 步，量框外背景漂移，出 N 栏并排对比视频 | 多轮编辑会不会越改越偏、几家编辑模型并排对比 |
| [pelican-bicycle-eval](skills/pelican-bicycle-eval/SKILL.md) | 「鹈鹕骑自行车」SVG 测评做成可重复的：多次运行看稳定性，记 token 和折算消耗；也能用官方直连当基线，检查 API 中转有没有偷塞 input token、关掉思考 | 横评几家模型的 SVG 能力；怀疑中转通道降级 |

### 读论文与讲解

| 技能 | 做什么 | 什么时候用 |
| --- | --- | --- |
| [paper-quick-read](skills/paper-quick-read/SKILL.md) | 5–10 分钟读一篇论文：脚本抽出带页码的全文和图表页截图，agent 按提纲版或速读版写导读，每句结论标页码 `[p.N]`，贡献分「论文宣称 / 实验支持 / 无法单独归因」三层，交付前回原页抽查 | 丢一个 arXiv 链接或 PDF，要一份能核对的导读 |
| [paper-arch-figure](skills/paper-arch-figure/SKILL.md) | 论文风神经网络架构图：先从源码取证记行号，再用 Python spec 生成可编辑 draw.io，导出 SVG / PNG | 画模型架构图、把 block 内部画出来 |
| [tech-talk-deck](skills/tech-talk-deck/SKILL.md) | 单文件 HTML 技术分享 deck：暖纸底 + 赭橙配色，15 种页型，每页先讲目的再讲做法、图先全出再逐项高亮，自绘 SVG 箭头自动连线与穿块检查，渲染自查 | 组会分享、实验汇报、论文讲解、录屏 |
| [deck-portrait](skills/deck-portrait/SKILL.md) | 把横屏 deck 自动重排成竖屏 3:4 PNG，图里字太小时追加局部放大页 | 横屏 deck 手机上看不清 |
| [xhs-43-deck](skills/xhs-43-deck/SKILL.md) | 小红书 4:3 图文配图 deck，公式离线排版，按手机宽度量字号 | 把一段技术讲解做成手机上读的图文 |
| [lecture-video-cut](skills/lecture-video-cut/SKILL.md) | 录屏讲解的 ffmpeg 剪辑流水线：去气口、删卡壳段、逐字高亮字幕、圆形摄像头、鼠标高亮 | 剪技术分享录屏 |

### 写作与汇报

| 技能 | 做什么 | 什么时候用 |
| --- | --- | --- |
| [weekly-review-authoring](skills/weekly-review-authoring/SKILL.md) | 先建证据清单再写周报，把周报写成职业证据而不是活动流水账 | 写周报、整理本周进展 |
| [architecture-plan-authoring](skills/architecture-plan-authoring/SKILL.md) | 按讲述时长冻结正文预算，先串文字主线再用图压缩表达 | 架构规划、技术方案汇报 |
| [working-report](skills/working-report/SKILL.md) | 按五层框架把已有材料串成一个故事，组织为工作汇报 | 阶段述职、实习总结、转正、晋升材料 |
| [xiaohongshu-content-extraction](skills/xiaohongshu-content-extraction/SKILL.md) | 把公开小红书笔记、长图或截图转成带来源边界的 Markdown | 提取笔记原文、OCR |

### 思考

| 技能 | 做什么 | 什么时候用 |
| --- | --- | --- |
| [question-clarifying](skills/question-clarifying/SKILL.md) | 苏格拉底式问诊，把模糊困惑收敛成一个准确的问题 | 说不清自己想问什么 |
| [unfamiliar-topic-learning](skills/unfamiliar-topic-learning/SKILL.md) | 双层解释、反向拆解、横纵分析或事实核查 | 听不懂某个概念、想系统研究一个领域 |
| [problem-solving-lenses](skills/problem-solving-lenses/SKILL.md) | 专家会诊、第一性原理、跨领域借解 | 方案越修越复杂、本行业解法都试过 |
| [decision-stress-testing](skills/decision-stress-testing/SKILL.md) | 两个选项都论证到最强；推演失效时改用最小实验 | 两条路都有道理、拿不定主意 |
| [self-understanding-interview](skills/self-understanding-interview/SKILL.md) | 深度访谈：找底层天赋，给三个五年版本和原型行动 | 考虑职业方向转变 |

## 技能之间的分工

**评测类：**`fair-eval-protocol` 管「怎么比才公平」，是所有对比实验的前置；`batch-vlm-requests`
管「请求怎么发、结果怎么收」；`edit-drift-eval` 和 `pelican-bicycle-eval` 是两个具体的评测，
跑之前同样按 `fair-eval-protocol` 定口径。

**读论文：**`paper-quick-read` 是快读，目标是一份能逐句核对页码的导读。要一站一站精读、
对着代码走一遍信息流，推荐第三方的 [skJack/kelip-paper-reading](https://github.com/skJack/kelip-paper-reading)。

**出 deck：**

| 技能 | 画幅 | 用途 |
| --- | --- | --- |
| `tech-talk-deck` | 16:9 | 技术分享 deck 本身，内容、页型、自绘图都在这里定 |
| `deck-portrait` | 横屏 → 竖屏 3:4 | 只接做好的 deck，不改内容，只重排导出 |
| `xhs-43-deck` | 4:3 | 为小红书图文从头做，不接 tech-talk-deck 的 deck |

模型结构图用 `paper-arch-figure` 画好，作为素材放进 `tech-talk-deck` 的一图页。

**写作：**周报面向自己和主管，验收标准是「这条能不能不考古就写进简历」；架构规划面向听众，
验收标准是「讲述者能不能脱稿复述主线」；工作汇报面向述职、转正和晋升，验收标准是「听众能说出主线、个人贡献和下一步」。

**思考：**按问题卡在哪一步选——说不清要问什么用 `question-clarifying`，不懂用 `unfamiliar-topic-learning`，
想不出方案用 `problem-solving-lenses`，两个方案选不出来用 `decision-stress-testing`，
卡的其实是方向用 `self-understanding-interview`。

## 安装

技能目录直接软链或复制到 Agent 的技能目录即可，不需要构建。

```bash
git clone https://github.com/ManagerZhang10/algorithm-engineer-skills.git
cd algorithm-engineer-skills

# Claude Code（用户级）：全装
for s in skills/*/; do ln -s "$PWD/$s" ~/.claude/skills/; done

# Codex
for s in skills/*/; do ln -s "$PWD/$s" ~/.codex/skills/; done

# 只装一个
ln -s "$PWD/skills/fair-eval-protocol" ~/.claude/skills/
```

项目级安装把链接放进 `<repo>/.claude/skills/`。带脚本的技能依赖写在各自 `SKILL.md` 里，
多数只需要 Python 标准库；`paper-quick-read` 需要 `pymupdf`。

## 配套工具与作者的其他作品

- [chrome-paper-reader](https://github.com/ManagerZhang10/chrome-paper-reader)：本地优先的 Chrome 读论文插件，`paper-quick-read` 的浏览器版。
- [explainer-studio](https://github.com/ManagerZhang10/explainer-studio)：中文技术讲解短视频工具箱。
- [image-gen-edit-papers](https://github.com/ManagerZhang10/image-gen-edit-papers)：195 篇图像生成与编辑论文的中文深读笔记。
- [video-gen-edit-papers](https://github.com/ManagerZhang10/video-gen-edit-papers)：50 篇视频生成与编辑论文的中文解读。
- [vlm-introduction](https://github.com/ManagerZhang10/vlm-introduction)：多模态大模型原理讲解视频与讲义。
- [LLM_bagu](https://github.com/ManagerZhang10/LLM_bagu)：手撕 LLM / RL 面试基本功题库。
- [agentic-rl-from-scratch](https://github.com/ManagerZhang10/agentic-rl-from-scratch)：不用 GPU、不用 LLM，纯 Python 从零写 agentic RL。

## 来源与边界

- 作者本人编写：`fair-eval-protocol`、`batch-vlm-requests`、`paper-quick-read`、`pelican-bicycle-eval`、
  `edit-drift-eval`、`paper-arch-figure`、`deck-portrait`、`xhs-43-deck`、`lecture-video-cut`、
  三个写作技能和 `xiaohongshu-content-extraction`。公开前做过脱敏：去掉了真实姓名、本机路径、
  内部项目代号、存储桶和内网地址，方法论部分未删减。
- `tech-talk-deck` 基于 [skJack/kelip-slide](https://github.com/skJack/kelip-slide)（MIT）改造，原名 kelip-slide。
  上游 `LICENSE` 原样保留在该目录，逐条改动见其 `UPSTREAM.md`。
- `pelican-bicycle-eval` 原为独立仓库，已连同提交历史并入本仓库。题面「Generate an SVG of a pelican
  riding a bicycle」是 Simon Willison 2024 年起推广的公开非正式基准。
- 五个思考技能改编自一篇公开发表的公众号文章里的 12 个提示词，**不是作者原创方法**；
  各目录下的 `UPSTREAM.md` 写明了出处和许可证状态（原文未声明授权条款，状态不确定）。
- 所有密钥只从环境变量或使用者自己的配置文件读取，仓库里不含任何凭据。
- 这些技能按作者的工作场景打磨，不是通用最佳实践；直接套用前先看它假设了什么。

---

<a id="english"></a>

## English

Agent skills for ML / algorithm engineers. Each `SKILL.md` works in both Claude Code and Codex.

Most public skill collections focus on paper writing, paper reading and autonomous research. This one
covers the daily middle of R&D work: fair model comparisons, sending large image batches to VLM APIs,
quick paper reads with verifiable page citations, and presenting experiment results. Every skill comes
from tasks the author repeats at work, with the pitfalls written down as rules. Skill bodies are in Chinese.

### Skills

| Skill | What it does |
| --- | --- |
| [fair-eval-protocol](skills/fair-eval-protocol/SKILL.md) | Freeze the eval protocol before comparing models / checkpoints / providers / prompts: hashed input manifest, unified sizes and decoding params, score only on the intersection every arm completed, failures reported by type. Ships `freeze_manifest.py` and `intersect.py`. |
| [batch-vlm-requests](skills/batch-vlm-requests/SKILL.md) | Batch image requests to multimodal APIs: inline base64 vs URL, batch vs realtime, cost estimate calibrated on real usage, frozen request bytes, results joined by ID with empty / truncated / refused outputs separated. |
| [edit-drift-eval](skills/edit-drift-eval/SKILL.md) | Multi-turn drift eval for image-edit models, with side-by-side comparison videos. |
| [pelican-bicycle-eval](skills/pelican-bicycle-eval/SKILL.md) | Repeatable "pelican riding a bicycle" SVG eval with stability and token accounting; also detects API relays that inject tokens or suppress reasoning. |
| [paper-quick-read](skills/paper-quick-read/SKILL.md) | 5–10 minute paper read: extract page-numbered text and figure pages, then write a guide where every claim carries `[p.N]`, with contributions split into claimed / supported by experiments / not separately attributable. |
| [paper-arch-figure](skills/paper-arch-figure/SKILL.md) | Paper-style neural network architecture figures as editable draw.io, sourced from code. |
| [tech-talk-deck](skills/tech-talk-deck/SKILL.md) | Single-file HTML tech-talk decks: 15 page types, goal-before-mechanism titles, picture-first highlighting, auto-routed SVG arrows, render self-check. Derived from skJack/kelip-slide (MIT). |
| [deck-portrait](skills/deck-portrait/SKILL.md) | Re-layout a 16:9 deck into 3:4 portrait PNGs for phones. |
| [xhs-43-deck](skills/xhs-43-deck/SKILL.md) | 4:3 image-post decks for Xiaohongshu, sized for phone reading. |
| [lecture-video-cut](skills/lecture-video-cut/SKILL.md) | ffmpeg pipeline for screen-recorded talks: silence removal, word-highlighted subtitles, webcam overlay. |
| Writing: [weekly-review-authoring](skills/weekly-review-authoring/SKILL.md), [architecture-plan-authoring](skills/architecture-plan-authoring/SKILL.md), [working-report](skills/working-report/SKILL.md), [xiaohongshu-content-extraction](skills/xiaohongshu-content-extraction/SKILL.md) | Evidence-first weekly reviews, talk-length-budgeted architecture plans, work / promotion reports, Xiaohongshu post extraction. |
| Thinking: [question-clarifying](skills/question-clarifying/SKILL.md), [unfamiliar-topic-learning](skills/unfamiliar-topic-learning/SKILL.md), [problem-solving-lenses](skills/problem-solving-lenses/SKILL.md), [decision-stress-testing](skills/decision-stress-testing/SKILL.md), [self-understanding-interview](skills/self-understanding-interview/SKILL.md) | From a vague question to a decision: clarify, learn, reframe, stress-test, reflect. |

### Install

```bash
git clone https://github.com/ManagerZhang10/algorithm-engineer-skills.git
cd algorithm-engineer-skills
for s in skills/*/; do ln -s "$PWD/$s" ~/.claude/skills/; done   # Claude Code
for s in skills/*/; do ln -s "$PWD/$s" ~/.codex/skills/; done    # Codex
```

### Attribution

`tech-talk-deck` is derived from [skJack/kelip-slide](https://github.com/skJack/kelip-slide) (MIT); the
upstream license is kept in its directory. The five thinking skills are adapted from prompts in a public
article (license status unclear, see each `UPSTREAM.md`). For deep, station-by-station paper reading we
recommend [skJack/kelip-paper-reading](https://github.com/skJack/kelip-paper-reading).

## License

[MIT](LICENSE) — covers content written in this repo. Skills adapted from third-party material are
described in their `UPSTREAM.md`; MIT here does not relicense upstream work.
