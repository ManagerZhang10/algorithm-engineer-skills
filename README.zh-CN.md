# pelican-proxy-check · 鹈鹕查中转

> [English](README.md) ｜ 技能指令见 [SKILL.md](SKILL.md)。

让若干条「模型 × 通道」画同一张**鹈鹕骑自行车**的 SVG 并排放，并从这同一发的响应里量出
每条通道的 **input token 注入**、**思考 token 抑制**和**响应元数据指纹**。

![看板截图](assets/board.png)

## 它解决什么问题

用 API 中转 / 网关 / 转售商时，你拿到的未必是宣称的东西。常见的手脚有四种：换成更便宜的
模型、偷偷量化、往每个请求里塞隐藏 system prompt、把推理思考关掉。前两种可以靠行为指纹类
工具识别；**后两种会被它们误判**——那类工具自己的文档就承认，只换 system prompt 造成的
分布漂移跟换模型是一个量级，分不清是哪种。

本工具走另一条路：**不猜，只读服务端自己报回来的数字**。

| 看什么 | 说明什么 |
| --- | --- |
| 同款模型跨通道的 `prompt_tokens` 差 | 多出来的就是被塞进去的隐藏上下文，是个确定的 token 数 |
| 同一思考档位下的 `reasoning_tokens` | 推理有没有被抑制 |
| `usage` 里的非标准字段 | 中转层的实现指纹 |
| 响应 id 前缀 | 响应有没有被改写或伪造 |

这几项都**直接落在看板上**，就印在每张图下面，不是只躺在 `run.json` 里：中转往你的 prompt 里
塞了 97 个 token 的隐藏上下文，格子里就是 `入 129 (+97)`；通道回传了思考 token 且值为 0，
显示 `思考 0`（高亮）；通道压根不回传这个字段，显示 `思考 — 未报` —— 这**两件事不是一回事**，
看板上分得开；中转自己的计费字段漏进 `usage`，显示 `usage 非标 9 项`，悬停能看到字段名。

**关键前提：同一个模型至少配两条通道 —— 可信的官方直连当基线，加上待验的中转。**
没有基线，所有数字都只是绝对值。这也是本工具和同类工具最大的不同：那些工具得靠社区维护的
参考指纹，而你手里往往真有直连账号可比。

基线用 `PB_<名>_BASELINE=true` 显式标出来。不标时的回退规则：同一个模型的泳道里，
CHANNEL 名含「直连」或 `direct` 的那条。

> **入 token 的差值只在同一个 model 的泳道之间算。** 跨 model 绝对不算：各家分词器不同，
> 跨 model 比入 token 量的是分词器，不是中转。同 model 只有一条泳道、或找不到基线时，
> 看板直接不显示差值 —— 不瞎猜。

## 图是干什么的

「生成一张鹈鹕骑自行车的 SVG」是 Simon Willison 2024 年起的一个公开非正式基准：这个场景在
训练数据里几乎不存在，模型只能真的去算几何，不能靠背。

图本身是**感官参照**——同一道题各家画成什么样，一眼可比，也方便截图给人看。但它温度非零、
方差很大，**单看一张图判不了任何事**。真正下结论要看上面那张表里的数字。

## 上手

只用 Python 标准库，不装依赖。但第一次跑**得留出 15–25 分钟**：时间基本都花在凑齐要对比的
那几条泳道的 key 和 base_url 上。跑批本身一轮一到两分钟（2026-09-13 实测四条泳道 57 秒、
113 秒各一次），大头是 reasoning 模型在思考。

```bash
mkdir -p ~/.config/pelican-proxy-check
cp lanes.env.example ~/.config/pelican-proxy-check/lanes.env
chmod 600 ~/.config/pelican-proxy-check/lanes.env   # 里面是密钥
$EDITOR ~/.config/pelican-proxy-check/lanes.env

python3 pelican_proxy_check.py --open
```

最后一条命令并发跑完所有泳道，写出**一个自包含的 HTML**（SVG 以 data URI 内联进去，
单独把这个文件拷走或发出去，图不会裂），并在浏览器里打开。

key 已经在 shell 环境里的，配置文件里用 `${VAR}` 引用就行，不必落明文：

```bash
PB_OPENAI_DIRECT_API_KEY=${OPENAI_API_KEY}
```

`${VAR}` 读的是**运行脚本那个 shell 的环境变量**，不是这个配置文件里的其他行 —— 跑之前先
`export`（或 `set -a; source your.env; set +a`），没 export 脚本会直接停下来告诉你缺哪个变量。

挂个定时器就是持续监控；脚本自带锁，上一轮没跑完不会叠上来。

```bash
python3 pelican_proxy_check.py render --open   # 只用已有快照重出看板，不花 API 钱
```

### 参数

| 参数 | 默认 | 作用 |
| --- | --- | --- |
| `render` | — | 只用已有快照重出看板，不调 API |
| `--config PATH` | `~/.config/pelican-proxy-check/lanes.env` | 泳道配置路径（权限必须 600） |
| `--out DIR` | `~/.local/share/pelican-proxy-check` | 快照和 `index.html` 放哪 |
| `--keep N` | `3` | 保留并展示最近几轮 |
| `--lang zh\|en` | `zh` | 看板语言 |
| `--anonymize` | 关 | 通道名抹成「中转 A / 中转 B」 |
| `--open` | 关 | 跑完顺手打开看板 |
| `--help` | — | 打印用法 |

想同时盯两套配置，就是两组 `--config` / `--out`：

```bash
python3 pelican_proxy_check.py --config ~/lanes-work.env --out ~/boards/work --keep 10
```

写错的参数一律报错退出并提示正确写法，不会被静默忽略 —— `--anonymize` 拼错一个字母就把
服务商真名照原样发出去，这种事不能有。

## 要外发截图时

```bash
python3 pelican_proxy_check.py render --anonymize        # 英文看板加 --lang en
```

通道名会被抹成「中转 A / 中转 B」，官方直连保留。上面那张截图就是这么出的 ——
**结论可以分享，被测服务商的名字不必**。

## 边界

只判**通道完整性**（请求在路上被改了什么），不判**模型身份**（端点背后到底是哪个模型）。
后者是行为指纹类工具的活，两者互补。

单轮异常可能只是抖动。判「恒定注入」还是「间歇注入」至少要三轮以上，而这恰好是最有价值的
区分：恒定的可以当常量扣掉；忽大忽小说明后面挂着多个池子、路由随机，**同一个 prompt 的行为
不可复现**。
