# 自进化流程（Self-Evolution Flow）

从 Claude Code 会话日志中蒸馏可复用资产，经人工确认后写入 skills / rules / CLAUDE.md / hooks / memory。目标是让 AI 环境随使用持续改进，同时保留来源与人工卡点。

## 组件地图

| 组件 | 位置 | 作用 |
|---|---|---|
| 蒸馏技能 | [`skills/session-distiller`](../../skills/session-distiller/SKILL.md) | 手动蒸馏：L0 筛选 → L1 骨架 → L2 轨迹 → L3 取证 → 分诊 → 确认 → 写入 |
| 入队 / 提醒 hook | [`hooks/self-evolve`](../../hooks/self-evolve/README.md) | `SessionEnd` 入队，`SessionStart` 提醒待确认候选 |
| 完整设计 | [`design/DESIGN.md`](design/DESIGN.md) | 六层架构、三级漏斗、五车道分诊、数据格式、三期计划 |
| 术语表 | [`design/CONTEXT.md`](design/CONTEXT.md) | session / transcript / 候选 / 晋升 / 游标等术语 |
| 架构决策 | [`design/adr/`](design/adr/) | 增量蒸馏、个人先行、组织资产库、集中式蒸馏 |
| 流程与卡点 | [`flow.md`](flow.md) / [`gates.md`](gates.md) | 阶段输入输出、确定性检查与人工审批点 |

## 安装

```bash
cp -r skills/session-distiller ~/.claude/skills/
mkdir -p ~/.claude/hooks/self-evolve
cp hooks/self-evolve/*.sh ~/.claude/hooks/self-evolve/
mkdir -p ~/.claude/self-evolve/{queue,staging,distill-state}
```

把 [`hooks/self-evolve/settings.example.json`](../../hooks/self-evolve/settings.example.json) 的 `hooks` 配置合并进 `~/.claude/settings.json`。Windows 使用 `hooks/self-evolve/win/*.cmd`，按本机 Python / Git 路径调整。

## 运行时不入库

以下目录是运行状态，不随组件库分发，也不应提交到公共仓库：

```text
~/.claude/self-evolve/
├── queue/           # jobs.jsonl、每日计数、worker.log
├── staging/         # 候选文件与 INDEX.md
└── distill-state/   # 每个 session 的蒸馏游标
```

候选文件里可能出现原始 session 片段；入库前必须按 `gates.md` 脱敏并提炼，禁止把原始记录写入长期记忆。

## 参考实现状态

- 一期（手动蒸馏）与二期（SessionEnd 入队 + 后台 worker + SessionStart 提醒）已在参考环境跑通。
- 三期 curator、晋升自动化、Q8 准确率验收尚未实现。
- **已知限制**：参考实现的 `worker.sh` 尚未接入 `distill-state` 游标，长 session 可能被重复全量蒸馏；当前靠 staging INDEX 的语义去重兜底。后续修复方向是蒸馏前查游标、只蒸增量尾部、蒸完写回。
- worker 依赖本机 `claude` CLI 与可用模型；模型不可用时任务保留在队列，不影响正常会话。

## 使用入口

- 手动整理某次会话：对 AI 说“蒸馏 session `<id>`”或“整理一下之前的会话”。
- 查看待确认候选：看 `~/.claude/self-evolve/staging/INDEX.md` 中标为 `staged` 的行。
- 晋升：按 `skills/session-distiller` 的 Step 8–10 输出候选表，人工批准后写入并提交（若资产库是 git 仓库）。
