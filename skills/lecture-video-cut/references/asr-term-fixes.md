# whisper 转写的术语修正

whisper-1 转中文技术讲解时的两类固定毛病，以及本技能怎么处理。

## 1. 英文被拆碎

`s` + `igma`、`Lo` + `RA` 这类。词级时间戳文件里的 `text` 是碎片，需要在生成
`whisper.json` 时合并成一个词（合并后的词时间 = 第一片 start 到最后一片 end）。
合并会让「V OK」这类相邻英文粘成一个词，锚点落在里面时脚本按整词处理，`review.md`
里能看出来。

## 2. 术语同音错写

按你的领域准备一份 `{"错写": "正写"}` 字典，`analyze --term-fixes terms.json` 传入。
脚本会跨词匹配（错写跨了几个 whisper 词也能替换），替换发生在锚点匹配之前，所以
cuts.json 里的锚点按**正写**来写。`term-fixes.example.json` 是一份图像生成 / 编辑
领域的示例，直接改着用。

## 3. 口头禅不靠词

whisper 会吞掉「呃 / 嗯」，所以气口靠麦克风轨的静音检测（`--silence-db`、
`--silence-min`），不要指望在转写里删这些词。

## 转写调用参数

用 OpenAI 兼容接口，凭据只从环境变量 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 读：

```bash
curl -s "$OPENAI_BASE_URL/audio/transcriptions" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -F file=@microphone.m4a -F model=whisper-1 -F language=zh \
  -F response_format=verbose_json -F "timestamp_granularities[]=word" \
  -F prompt="LoRA, DiT, VAE, ViT, sigma, flow matching, 隐变量"
```

`prompt` 里放术语表能明显减少错写。25 分钟音频约 1–2 分钟返回。
