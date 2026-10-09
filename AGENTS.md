# algorithm-engineer-skills 仓库约定

> 适用范围：本仓库全部内容

## 一、这个仓库是什么

个人 Agent Skill 的沉淀仓库。**一个技能 = `skills/` 下一个自包含目录**，可以被单独软链
到 `~/.claude/skills/` 或 `~/.codex/skills/` 使用，不依赖本仓库其它文件。

这里只放技能本身。技能产出的周报、方案、文档一律不进本仓库。

## 二、目录形态

```text
skills/<skill-name>/
├── SKILL.md              ← 必须。YAML frontmatter 只有 name 和 description
├── references/           ← 可选。按需加载的长参考，SKILL.md 里显式链接
└── agents/openai.yaml    ← 可选。Codex 侧展示与调用配置
```

- 目录名、`SKILL.md` 的 `name` 字段必须一致，小写加连字符。
- `description` 要同时说清「做什么」和「什么时候用」，这是 Agent 选技能的唯一依据。
- `SKILL.md` 保留可执行结论。长流程、量表、模板放 `references/`，
  并在 `SKILL.md` 里写明什么条件下读取。

## 三、README 是唯一索引

新增或删除技能时同步改 `README.md` 的技能索引表和安装段落。
表里一行一个技能，技能名指向 `SKILL.md`，参考文件单独成列。
跨技能的分工说明写在 README 的「三个技能的分工」一节，不写进单个 `SKILL.md`。

## 四、公开仓库的脱敏纪律

本仓库是 **public**。提交前必须确认新增内容不含：

- 真实姓名、邮箱、手机号；
- 本机绝对路径（`/Users/...`）；
- 内部项目代号、内部系统名、未公开的组织架构信息；
- 任何凭据、token、内网地址。

组织专有的字段名、模板和配色可以保留，但必须在 `SKILL.md` 里写成
**可替换的默认值**，而不是写成唯一正确答案。

提交前自查：

```bash
grep -rniE "/Users/|@[a-z0-9-]+\.(com|cn)|token|secret|api[_-]?key" . --exclude-dir=.git
```

## 五、事实纪律

- 派生自他人的技能必须在同目录放 `UPSTREAM.md`，写清来源仓库、路径、取得日期、
  本地改了什么，以及上游许可证状态。**许可证状态不确定时如实写不确定，不要推断。**
- README 里对技能来源和脱敏范围的描述必须与实际改动一致。
- 不把未验证的判断写成事实。

## 六、对外动作停点

`git push`、改仓库可见性、建 Release、加协作者都是对外动作，**执行前必须问一次**。
建仓、写文件、改技能内容不用问。
