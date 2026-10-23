# 自进化环境（Self-Evolving Environment）

从 Claude Code 会话日志中自动蒸馏可复用资产（skill / rules / CLAUDE.md / hooks / memory），先服务于个人环境，终态是公司级统一开发平台。

## Language

### 核心流程

**Session（会话）**:
一次 Claude Code 对话，对应 `~/.claude/projects/<项目slug>/<session-id>.jsonl` 一个持续追加的日志文件。`--resume` 复用同一 session id。
_Avoid_: Section、station、对话窗口

**Transcript（会话日志）**:
session 的 JSONL 文件本体，含用户消息、助手消息、工具调用（tool_use）与返回（tool_result）。
_Avoid_: log、记录文件

**蒸馏（Distillation）**:
从 transcript 中识别可复用经验并转化为资产候选的过程。
_Avoid_: 针流、提取、总结

**候选（Candidate）**:
蒸馏产出的、尚未进入正式资产库的单条经验（一条规则、一个流程、一条事实）。
_Avoid_: 产物、条目

**暂存区（Staging）**:
候选的存放区，位于正式资产库之外，等待晋升。
_Avoid_: 缓冲区、临时区

**晋升（Promotion）**:
候选从暂存区进入正式资产库的动作。
_Avoid_: 入库、发布

**蒸馏游标（Cursor）**:
每个 session 记录"已蒸馏到哪儿"的状态（字节偏移 + 消息 uuid），使长 session 只蒸增量。
_Avoid_: 水印、断点

**Supersedes 链**:
新候选标注取代某个旧候选/资产的关系链，形成资产的演化历史。
_Avoid_: 覆盖、替换记录

### 资产侧

**资产（Asset）**:
正式入库的可复用配置：skill、`.claude/rules/` 规则、CLAUDE.md 条目、hook、memory 条目。
_Avoid_: 知识、配置项

**车道（Lane）**:
资产按性质分的五条独立处理路径：skill / rules / CLAUDE.md / hooks / memory。
_Avoid_: 类别、层级

**库卫生（Curation）**:
对资产库的周期性治理：去重合并、stale 标记、归档。
_Avoid_: 清理、维护

**Provenance（出处注释）**:
每条资产携带的来源信息：session id、日期、入选理由。用于审计与防"灾难性记忆"。
_Avoid_: 元数据、备注

### 组织侧（终态）

**组织层（Org Layer）**:
公司统一管理的资产集合，下发到所有员工的 Claude 配置；员工个人设置叠加其上。
_Avoid_: 全局配置、共享层

**组织资产库（Org Asset Repo）**:
组织层的唯一事实源：一个版本控制仓库（git 或 P4），所有蒸馏改动以 commit/PR 形式进入，维护团队评审 approve 后合入，员工从该仓库同步。
_Avoid_: 共享目录、配置中心

**下发（Distribution）**:
组织资产库中已批准的资产同步到每个员工本地 Claude 配置的动作。
_Avoid_: 发布、推送

**维护团队（Maintainer Team）**:
评审蒸馏改动、决定哪些晋升进组织资产库的团队。公司期由它集中执行蒸馏与上浮，有权访问全员 session log；员工全程无感知。
_Avoid_: 管理员、审批人
