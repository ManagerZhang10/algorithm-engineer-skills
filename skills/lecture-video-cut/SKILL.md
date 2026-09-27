---
name: lecture-video-cut
description: 剪 ScreenKite 录的讲解视频：去静音气口、按文字锚点删卡壳重说段、叠圆形摄像头、烧逐字高亮字幕、高亮鼠标光标，出 draft 草片或与源同分辨率的 final 正式片。用户说「剪一下这个录屏」「把气口去掉」「加字幕」「摄像头放右下角」「高亮我的鼠标」「用 ffmpeg 流水线出片」，或给出 .skbundle 项目包要出片时用。不用于 ScreenKite 自带剪辑功能。
---

# lecture-video-cut

能力全在 `scripts/lecture_cut.py`（Python ≥ 3.9 标准库 + ffmpeg，通常软链成 `~/.local/bin/lecture-cut`），
本文件只讲何时用、怎么传参、失败怎么报。

## 什么时候用

- 用户用 ScreenKite 录了讲解视频（`<名字>.skbundle`，`media/` 下有屏幕 / 摄像头 / 麦克风三轨，
  `metadata/pointer-track.jsonl` 是鼠标轨迹），要出成片。
- 要做的事是这几类的组合：删静音气口、删卡壳后重说的那一遍、叠右下角圆形摄像头、烧逐字高亮中文字幕、高亮鼠标。
- 已有 whisper-1 词级转写 json（`sourceWords[]`，每项 `{start,end,text}`，秒）。没有就按
  [references/asr-term-fixes.md](references/asr-term-fixes.md) 里的参数调 `whisper-1`，凭据只从环境变量
  `OPENAI_API_KEY` / `OPENAI_BASE_URL` 读。

不要用它做：ScreenKite 自带的剪辑，以及跨大段的语义重复删除（讲者先讲现象后面再总结一次，通常是有意的）。

## 依赖

- ffmpeg ≥ 6，编译带 `libass`（烧 ASS 字幕）；macOS 上有 `h264_videotoolbox` 最好，没有就 `--encoder libx264`。
- 字幕字体默认 `PingFang SC`，没有就 `--font "Hiragino Sans GB"` 或任何本机中文字体名。
- 不需要 ffprobe，脚本用 `ffmpeg -i` 探测。

## 怎么走

1. **只读 skbundle**，不写、不移动、不改名里面任何文件。
2. `analyze` 出清单：
   ```bash
   lecture-cut analyze --bundle <x.skbundle> --words <whisper.json> --out <workdir> [--cuts cuts.json] [--term-fixes terms.json]
   ```
   产出 `<workdir>/review.md`（按句列全文、`mm:ss`、保留 / 删除标记，静音只汇总）和 `edl.json`（保留区间）。
   **先把 review.md 给用户过目再渲**，一次删太多用户会不放心。
3. 手工删除写 `cuts.json`，全部用文字锚点：
   ```json
   [{"from": "起始短语", "to_before": "结束短语（不含）", "reason": "卡壳后重讲"},
    {"from": "起始短语", "to": "结束短语（含）", "to_occurrence": "last", "reason": "..."}]
   ```
   可选 `from_occurrence` / `to_occurrence`：`first`（默认）| `last` | 第几次（整数）；`skip_if_missing: true` 允许起始短语不存在时跳过。
   匹配规则：去标点空格、不分大小写的子串匹配。**写锚点前先在转写里 grep 确认存在且唯一**；
   转写里合并过的英文词（如 `V OK`）是一个整体，锚点落在里面会整词处理。
4. 规格用 `--profile`：**草片 / 审清单用 `draft`（默认，720p30 低码率，快）；正式片用 `final`**
   （分辨率、帧率直接取屏幕源，不缩放不加黑边，码率按像素率换算约 16M，UI 元素按输出宽等比放大）。
   `--size WxH` / `--fps N` 可覆盖。先渲 20~30 秒试片看字幕和摄像头位置，再渲全片：
   ```bash
   lecture-cut render --workdir <workdir> --out preview.mp4 --preview 30 [--preview-start 600]   # draft
   lecture-cut render --workdir <workdir> --out <成片.mp4> --profile final
   ```
   默认 4 路并行；25 分钟源在 M 系列 Mac 上 draft 约 2 分钟、final（3024x1900@60）约 8 分钟。
   字幕每行 22 字、`\k` 卡拉 OK（说到变黄 #FFD54A）；鼠标光标默认叠加（自绘带白边箭头 / I 型光标放大 1.6 倍，
   背后半透明黄色光圈，点击时闪一下），`--no-cursor` 关闭，`--cursor-scale` / `--halo-size` / `--halo-alpha` 调。
5. 每次 render 会在成片旁写 `<out>.srt` 和 `<out>-字幕.md`（成片时间码按句一行，剪切接缝处插一行
   `--- 剪切点 ---`）。**把 `-字幕.md` 给用户扫一遍**：接缝前后两句连起来读不通，就是剪坏了。
6. 验收：`ffmpeg -i` 看时长分辨率帧率；抽 3 帧看字幕 / 摄像头 / 光标 / 屏幕没被裁；挑 2 个时间点把字幕和
   `edl.json` 反查的原文对一下。

## 失败怎么报

- `锚点找不到`：脚本会打印最接近的一段文本和时间，把它贴给用户让用户改锚点措辞，不要自己猜着删。
- `锚点出现 N 次，按 first 取第一次`：是提示不是错误，但要核对那一次是不是用户要的；不是就加 `occurrence`。
- `三轨时长不一致` 警告：报告里写出各轨时长，脚本已按最短对齐到开头。
- `没有 metadata/pointer-track.jsonl` 警告：成片没光标，报告里说明；不要用 `--no-cursor` 掩盖。
- `chunk 渲染失败`：把 ffmpeg 报错原文贴出来；常见是字体名不存在、ffmpeg 没带 libass、素材路径变了。
- `帧数不符`：拼接可能有音画漂移，报告里写明哪个 chunk、差几帧，不要静默交付。
- 渲染耗时、成片时长、review.md 路径、试片和成片路径，都写进最终报告。
