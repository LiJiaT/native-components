# 自进化环境 · 完整设计文档

> **恢复指南**：新 session 接手时按序阅读：
> 1. 本文件（设计全文）
> 2. `../README.md`（组件地图、安装与已知限制）
> 3. `../flow.md` / `../gates.md`（流程阶段与卡点）
> 4. `CONTEXT.md`（术语表）
> 5. `adr/0001–0004`（四项关键架构决策及理由）
>
> 状态：设计定稿；参考实现状态见 `../README.md`

---

## 1. 项目目标

**从 Claude Code 会话日志（transcript）中自动蒸馏可复用资产**（skill / rules / CLAUDE.md / hooks / memory），让环境随使用自我进化。

- **现在要做的**：个人级（`~/.claude`）进化流程，三期落成。
- **终态（只留接口，暂不实现）**：公司级统一开发平台——维护团队集中执行蒸馏、访问全员 session log、评审后通过组织资产库下发全员；员工全程无感知，个人设置叠加于组织层之上。

## 2. 决策记录（12 项，逐轮与用户敲定）

| # | 决策 | 备注 |
|---|---|---|
| Q1 | 长 session 用**增量蒸馏 + 对账**：游标记录进度，新证据可产出 supersedes 候选修订旧资产 | ADR-0001 |
| Q2 | **个人先行**，数据格式预留 user/scope/provenance 扩展点 | ADR-0002 |
| Q3 | 组织终态：员工侧全自动无感知 | |
| Q4 | 组织终态：统一组织层下发全员，个人设置叠加 | |
| Q5 | 组织层入库必经**维护团队评审 approve** | 调和"全自动"与"防污染" |
| Q6 | 同一经验识别：蒸馏时对照**一行摘要索引做语义判断**，合并并使 recurrence+1 | 不用哈希（对改写脆弱） |
| Q7 | 过时资产**直接删除**，git 历史即档案 | 不维护 .archive/ 目录 |
| Q8 | 个人期先 **staging + 批量确认**，2–4 周准确率数据达标后切全自动 | 准确率数据是公司期定阈值的依据 |
| Q9 | 安装 SIS 插件观察 1–2 周（skill 车道外包候选），阈值保持 ≥40 | 与自建 skill 并行对比 |
| Q10 | 组织资产库用 **git**（非 P4），原生支持 plugin marketplace | ADR-0003 |
| Q11 | **个人资产库也是 git 仓库**，蒸馏写入即 commit（同构练兵） | 个人/公司写入逻辑零差异 |
| Q12 | 公司期为**集中式蒸馏**：维护团队统一执行、有全员 log 权限、员工零感知 | ADR-0004 |

## 3. 总架构（六层）

```
1 采集层   SessionEnd hook 读 stdin 的 transcript_path，fire-and-forget 入队
           ⚠️ 不用 PostToolUse 逐条压缩（claude-mem Issue #618：单会话烧 140K token 的教训）
2 蒸馏层   后台受限 worker 异步处理 JSONL，L0→L1→L2→L3 漏斗（见 §4）
3 分诊层   每条候选走五车道分诊表（见 §5）
4 质量门   入库条件：①跨 session 复现 ②经验证成功 ③命名了失败模式
           产物先进 staging，确认后晋升（个人期 Q8：先批量确认）
5 资产库   git 化 markdown，每条写入带 provenance 注释（出处+理由）
           ⚠️ arXiv 2608.11095：无理由注释的指令文件只增不减(+226%)
6 召回+卫生 常驻预算极小（CLAUDE.md 静态+skill description）；
           curator 定期：语义去重、30/45 天 stale/删除（git 留痕）、修补优先于新建
安全基线   产物落盘前脱敏（secret 过滤）；不引入托管记忆服务；
           蒸馏子会话无 Bash + deny 规则 + 预算封顶 + transcript 不可信边界包裹
```

## 4. 三级视图提取（大日志处理法）

单 session 可达 10MB+，禁止全量读入。漏斗式处理：

| 级 | 成本 | 内容 | 产出 |
|---|---|---|---|
| **L0 筛选** | 0 token（纯脚本） | 扫全部 jsonl，统计：session_id、时间、项目、工具调用数、文件编辑数、纠错关键词数（"不对"/"不是"/"actually"/"wrong"） | 按阈值排序的候选 session 清单 |
| **L1 骨架** | ~3–5K token/session | jq 取 type=user 非 meta 文本 + assistant 的 text 块（跳过 thinking/tool_use/tool_result） | "会话剧本"，人工/agent 圈出 2–5 个高价值段落 |
| **L2 工具轨迹** | ~1–2K token/段 | 按 uuid 窗口切出该段 tool_use 序列：工具名 + input 前 100 字符 + 成败 + 结果前 200 字符 | 可复用流程的精确步骤、坑点 |
| **L3 取证** | 按需 | 按 tool_use_id 精确抽完整 input+output 原文 | 写 skill/rules 所需的精确命令参数 |

- 入选阈值（参考 SIS 0.18.0 教训：阈值 12 时 92% 运行都在写 skill，库一天涨 10 个）：**工具调用 ≥40 或 文件编辑 ≥3 或 纠错信号 ≥2**
- L2/L3 可派子 agent 执行，主会话只看结论（符合用户 CLAUDE.md 既定策略）
- transcript 结构事实（已实测）：tool_use/tool_result 完整保留（单条实测最大 21KB 无截断），另有 toolUseResult 元数据、thinking 块、cwd/时间戳/版本号

## 5. 五车道分诊表

| 候选性质 | 个人期去处 | 公司期落地映射 |
|---|---|---|
| 多步流程，跨项目通用 | `~/.claude/skills/` 新 skill 或已有 skill 加章节 | plugin marketplace（skill 形式） |
| 多步流程，项目专属 | 该项目 `.claude/skills/` | 项目仓库 `.claude/`（走 PR） |
| 只对某类文件/路径生效的约束 | `.claude/rules/<topic>.md` + `paths:` frontmatter | 打包进 marketplace skill（plugin 不能带 rules） |
| 每会话都要的指令 | `CLAUDE.md`（≤200 行硬约束） | managed CLAUDE.md / `claudeMd` key |
| 必须确定执行/禁止的行为 | hook / settings permissions 提案（**永远需显式确认，全自动期也不例外**） | managed settings / hooks |
| 环境/账号/工具事实 | 项目 memory（ADD-only） | 不下发，留个人 |
| 一次性细节 | 丢弃，表格注明原因 | — |

判定阈值（官方 features-overview）：同一约定搞错两次 → CLAUDE.md 候选；同一流程粘贴第三次 → skill 候选。

## 6. 数据格式规范（公司期兼容的关键）

### 6.1 候选文件（staging 中一条经验一个文件）

```markdown
---
id: cand-<8位hash>
created: 2026-09-23
source_sessions: ["<session-id>"]
user: <user>
scope: user | project
lane: skill | rules | claude-md | hooks | memory
status: staged | promoted | superseded | deleted
supersedes: null
recurrence: 1
---
# 标题
正文（流程步骤 / 规则内容 / 事实）
<!-- 理由: 为什么值得入库；来源: session <id>, <日期> -->
```

### 6.2 蒸馏游标（每个 session 一份）

`~/.claude/self-evolve/distill-state/<session-id>.json`：
```json
{
  "last_offset": 0,
  "last_uuid": "",
  "distill_count": 3,
  "candidates": ["cand-a1f3", "cand-b22e"]
}
```

### 6.3 写入 CLAUDE.md/rules 的 provenance 注释

```markdown
<!-- 来源: session <session-id>, <日期>, 理由: 第二次犯同错 -->
```

### 6.4 staging 索引（Q6 语义匹配的载体）

`~/.claude/self-evolve/staging/INDEX.md`：每行一条 `cand-id | lane | 一行摘要`，蒸馏流程必须先查索引再决定 新增/合并(recurrence+1)/supersedes。

## 7. 实施计划（个人期三期）

### 一期：手动 session-distiller（本次开工）

```
~/.claude/skills/session-distiller/
├── SKILL.md            # 主流程：L0→圈段→L2→L3→盘点→分诊→确认→写入
├── scripts/scan.sh     # L0 统计扫描
└── scripts/extract.sh  # L1/L2/L3 提取（--level/--from/--to/--tool-id）
~/.claude/self-evolve/
├── staging/            # 候选暂存 + INDEX.md
└── distill-state/      # 游标
```

工作流：定位 session → L0 → L1 全扫圈段 → L2 轨迹 → 必要 L3 → **盘点已有资产**（ls skills、读 CLAUDE.md/MEMORY.md/rules，已有就改不新建）→ 查 staging INDEX 语义去重 → 分诊表 → 输出「候选→分类→去处→理由」表格 → **用户确认** → 写入（带 provenance）→ git commit。

配套：个人资产库 `git init`（白名单 .gitignore：只跟踪 CLAUDE.md、skills/、rules/、agents/、hooks/、self-evolve/；**排除 settings*.json、.credentials.json 等敏感文件**）；安装 SIS 插件（marketplace: UniM0cha/self-improving-skills，确认 SIS_DISTILL_THRESHOLD≥40）。

**验收**：拿 2–3 个真实历史 session 端到端实测，产出候选表格并经用户确认写入。

### 二期：自动化采集 + 后台蒸馏

- `~/.claude/hooks/distill-enqueue.sh`：SessionEnd hook，stdin 收 JSON（含 session_id、transcript_path），算 L0 统计，达标追加队列行到 `self-evolve/queue/`，exit 0 不阻塞
- 后台 worker（launchd/cron 或 nohup）：消费队列，起受限无头 `claude -p` 执行一期流程，产物写 staging
- SessionStart hook 提示"N 条待确认"，用户批量确认晋升
- 安全围栏：子会话无 Bash、凭据路径 deny、单 job 预算封顶（参考 SIS_DISTILL_MAX_USD + MAX_JOBS_PER_DAY）、transcript 随机边界包裹
- 蒸馏管线入口参数化（接受任意 transcript 路径/队列）——ADR-0004 集中式复用的前提

### 三期：库卫生 + 晋升自动化

- curator 定期跑：staging INDEX 语义去重合并；30 天未触发标 stale、45 天删除（use_count≥3 加倍宽限，删除=带理由的 git commit）；description 压缩；修补优先于新建
- 晋升自动化：同一经验 recurrence ≥3 → 自动从 staging 晋升（降为周报式批量告知）
- 效果评估：官方 evaluation-driven 法验证 skill 是否减少重复错误
- Q8 验收：2–4 周 staging 准确率数据达标 → 切全自动

## 8. 公司期架构备忘（暂不实现，接口已预留）

- **集中式蒸馏**（ADR-0004）：维护团队有全员 log 权限，中央复用同一管线（管线入口参数化是为此预留）
- **组织资产库 = git repo**（ADR-0003）：唯一事实源，commit/PR 进入，评审=代码评审，个人期 git 同构练兵
- **下发双通道**（官方核查结论）：①plugin marketplace（就是这个 repo 自己，承载 skills/agents/hooks；managed settings 强推 enabledPlugins + extraKnownMarketplaces + autoUpdate）②managed CLAUDE.md / managed-settings.json（承载全局指令/permissions，MDM/Ansible 或 server-managed settings 送达）
- ⚠️ 官方事实：plugin 不能携带 CLAUDE.md/rules；无 managed 级 rules 目录；规则类指令须打包成 skill

## 9. 关键参考

- 官方：[Steering Claude Code（CLAUDE.md/skills/hooks/rules 决策）](https://claude.com/blog/steering-claude-code-skills-hooks-rules-subagents-and-more)、[memory.md（四级记忆+rules）](https://code.claude.com/docs/en/memory.md)、[features-overview（触发阈值表）](https://code.claude.com/docs/en/features-overview.md)、[skills best-practices（官方进化循环）](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)、[Effective Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)、[admin-setup（组织下发）](https://code.claude.com/docs/en/admin-setup.md)
- 社区：[session-retro（分诊表原型）](https://gist.github.com/wonkwonlee/43c6b490ca8e61788daa4972517c4fd4)、[session-checkpoint（信号清单+三层memory）](https://gist.github.com/MiLk/9e09b90c2de7bbc7f6ace206fb35040d)、[UniM0cha/self-improving-skills（SIS，后台蒸馏蓝本）](https://github.com/UniM0cha/self-improving-skills)、[MemU](https://github.com/NevaMind-AI/MemU)、[claude-mem（渐进披露召回+#618教训）](https://github.com/thedotmack/claude-mem)
- 论文：[Voyager（验证门+skill library）](https://arxiv.org/abs/2305.16291)、[ExpeL（经验库add/edit/upvote）](https://arxiv.org/abs/2308.10144)、[灾难性记忆（理由注释）](https://arxiv.org/abs/2608.11095)
- 血泪教训：记忆反复重写退化（坏记忆比遗忘更糟）；PostToolUse 逐条压缩=成本灾难；CLAUDE.md 无注释只增不减；双记忆引擎不可叠加；记忆文件是攻击面需脱敏

## 10. 参考实现进度（个人环境示例）

- [x] 调研（官方+社区）与架构设计
- [x] 12 项决策敲定，CONTEXT.md + ADR-0001~0004 落盘
- [x] 一期：session-distiller skill + 三级提取脚本 + git 资产库 + 手动端到端实测
- [x] 二期：SessionEnd 入队 hook + 后台 worker + SessionStart 提醒，自动化闭环跑通
- [ ] 三期：curator + 晋升自动化 + Q8 验收切全自动
- [ ] 观察期决定：外部蒸馏插件的去留

参考实现的已知限制与未闭合项见 `../README.md`。
