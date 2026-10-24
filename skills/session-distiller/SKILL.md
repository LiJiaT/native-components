---
name: session-distiller
description: 从 Claude Code 历史 session 日志（transcript JSONL）中蒸馏可复用资产：skill、.claude/rules 规则、CLAUDE.md 条目、hook/permission 提案、memory 条目，经分诊和用户确认后写入。当用户说"蒸馏 session"、"整理一下之前的会话"、"把这个 session 的经验沉淀下来"、"看看最近哪些 session 值得学"、"把这次的坑记下来"、"更新 CLAUDE.md/rules/skills"且内容来自历史会话、或提到 session id/蒸馏/自进化时使用。不要在用户只是问问题或要求普通代码工作时触发。
---

# Session Distiller（会话蒸馏）

从历史 session 日志中提取可复用经验，分诊到五条车道，经用户确认后写入正式资产库。

完整设计与数据格式见 `~/.claude/self-evolve/DESIGN.md`（分诊表 §5、数据格式 §6、阈值 §4；由安装器从组件库 `flows/self-evolution/design/` 复制）。本 skill 是该设计的执行入口。

## 硬性规则

1. **禁止全量读入 transcript**。单 session 可达 10MB+，必须用漏斗：L0 → L1 → L2 → L3（脚本在 `scripts/`）。
2. **写入前必须盘点**：先查现有 skills / CLAUDE.md / rules / MEMORY.md / staging 索引，已有同类就改不新建。
3. **写入前必须确认**：输出候选表格，用户批准才写。唯一例外见分诊表的 hooks 车道（永远需确认，全自动期也不例外）。
4. **每条产物带 provenance**：`<!-- 来源: session <id>, <日期>, 理由: <一句话> -->`。
5. **写入即 git commit（资产库必须 git 化）**：规范要求资产库 git 化。若目标资产库不是 git 仓库，晋升 **blocked**，先由人决定初始化仓库或指定已有资产 repo；不得跳过 commit 与回滚路径，也不得把"非 git"当默认放行。
6. **产物落盘前脱敏**：候选中出现 token/密码/内网地址等敏感值时用 `<REDACTED>` 替换。

## 工作流

### Step 1 · 定位目标 session

用户可能给：session id（支持前缀）、"最近的 N 个"、某项目的、或没说（默认走 L0 扫描找高分的）。

```bash
scripts/scan.sh                 # L0：全部 session 按入选分数排序
scripts/scan.sh --project -Users-<user> --top 5 --days 14
```

入选阈值：工具调用 ≥40 或 文件编辑 ≥3 或 纠错信号 ≥2（脚本内常量，可调）。

### Step 2 · L1 骨架（对入选 session）

```bash
scripts/extract.sh <session-id> --level 1
```

输出带 `[序号]` 的"会话剧本"（用户原话 + 助手结论）。据此圈出 **2–5 个高价值段落**，判定信号：用户纠错（"不对，其实…"）、被推翻的误解、反复重试后才成功的操作、新流程首次走通、API/配置坑、里程碑。序号范围即 L2 的 `--from/--to` 输入。

**token 纪律**：L1 输出通常 3–5K token，够了就停，不要把输出整个贴给用户——摘要点即可。段落多或 session 多时可派子 agent 做 Step 2–3，主会话只收结论。

**L1 输出超大被持久化时的索引式阅读法**：长会话的 L1 输出常超 100KB，被 harness 持久化到 `~/.claude/projects/<proj>/<sid>/tool-results/*.txt`。此时不要分段盲读：
1. 从 Bash 工具结果里拿到持久化文件路径
2. `grep -n '^\[' 文件` 生成条目索引（行号+序号+角色+首行摘要），据此识别会话结构与值得深入的段——2400+ 条的巨型会话一次索引即可看清全局脉络
3. 对目标段用 `sed -n 'N,Mp'` 或按行号 grep 定向读，而非全文件读入
4. 注意：最终助手 JSON 输出在 extract 输出里会被按字符截断，看不到候选全貌时靠 L2 工具轨迹交叉印证

<!-- 来源: session <session-id>, cand-<id>, 理由: 对每次长会话蒸馏都复用的读法，实测有效 -->

### Step 3 · L2 工具轨迹（对每个圈出的段落）

```bash
scripts/extract.sh <session-id> --level 2 --from <序号> --to <序号>
```

看清：精确步骤顺序、哪个命令失败过、报错是什么、最终怎么修好的。**失败的尝试和修正过程往往是比成功更值钱的蒸馏素材**（失败模式要写进 skill 的"不要做"部分）。

### Step 4 · L3 取证（按需）

只有当确定要写 skill/rules、需要精确命令和参数时：

```bash
scripts/extract.sh <session-id> --level 3 --tool-id <toolu_xxx>
```

### Step 5 · 盘点已有资产（防重复闸一）

- `ls ~/.claude/skills/` 及相关项目的 `.claude/skills/`，读 description 相近者的 SKILL.md
- 读 `~/.claude/CLAUDE.md`、项目 `CLAUDE.md`、`~/.claude/rules/`、项目 `.claude/rules/`
- 读项目 memory（`~/.claude/projects/<slug>/memory/`）
- 若发现"已有 skill 覆盖但本次没用上"——**先报告这一点**，这是习惯纠正，比新资产更有价值

### Step 6 · 查 staging 索引（防重复闸二）

读 `~/.claude/self-evolve/staging/INDEX.md`（每行 `cand-id | lane | 一行摘要`）。对每条新候选做语义判断：

- 与现有候选**同一经验** → 不新建，将旧候选 `recurrence` +1，更新正文补充新细节
- 与现有资产/候选**部分重叠** → 产出 supersedes 候选（frontmatter `supersedes: <id>`），正文说明改动理由
- **全新** → 新候选

### Step 7 · 分诊（五车道）

按 DESIGN.md §5 分诊表归类。判定口诀（官方阈值）：**同一约定搞错两次 → CLAUDE.md 候选；同一流程第三次出现 → skill 候选**；只对特定路径生效 → rules + `paths:` frontmatter；要求确定性执行/禁止 → hook/permission 提案；环境事实 → memory；一次性细节 → 丢弃（表格里注明原因）。

### Step 8 · 输出候选表格，等确认

```markdown
| # | 候选 | 车道 | 去处 | 理由 | recurrence |
|---|------|------|------|------|-----------|
| 1 | 部署脚本需先 export TOKEN | skill | ~/.claude/skills/deploy-flow/ | 两个 session 各踩一次 | 2 |
| 2 | 一次性 debug 过程 | 丢弃 | — | 无复用价值 | — |
```

**到此停止，等用户批准。**

### Step 8.5 · 晋升检查（只检查，不自动批准）

对每条拟晋升候选生成 `promotion.json`（schema 见 `schemas/promotion.schema.json`），至少包含：跨 session 证据（≥2）、证据文件 hash、失败模式、owner、scope、目标仓库 commit/clean、`target_path`、`status: proposed`。运行：

```bash
python gates/gate.py promotion --file promotion.json
```

检查通过只代表字段/hash/git/范围齐全，不改变人工批准要求；未通过不得进入 Step 9。

### Step 9 · 写入（用户批准后）

1. 每条批准的候选按 DESIGN.md §6.1 格式写正式产物：
   - skill → `<name>/SKILL.md`（frontmatter name/description 遵守官方规范：description ≤1024 字符、写清何时触发、第三人称；正文 ≤500 行，长内容拆 `references/`）
   - rules → `.claude/rules/<topic>.md`，需要路径作用域时加 `paths:` frontmatter
   - CLAUDE.md 条目 → 检查目标文件 ≤200 行
   - memory → 项目 memory 目录，ADD-only
   - hook/permission 提案 → 只写候选文件到 staging，**不直接改 settings.json**
2. 更新 `staging/INDEX.md` 与候选状态（promoted）
3. 更新游标：`~/.claude/self-evolve/distill-state/<session-id>.json`（DESIGN.md §6.2）
4. 在目标资产库执行 `git add -A && git commit -m "distill: <一句话> (cand-xxx)"`；非 git 仓库时按硬性规则 5 停止并交人处理。

### Step 10 · 汇报

写入位置清单 + git commit hash + 一句"下次遇到 X 应触发 Y skill"的提醒。若 Step 5 发现了未使用的已有 skill，在这里点名。
