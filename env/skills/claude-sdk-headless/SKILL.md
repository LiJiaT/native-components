---
user-invocable: false
name: claude-sdk-headless
description: 用 Python claude-agent-sdk 无头调用 Claude Code（经方舟网关，凭证取自 ~/.claude/settings.json 的 env）构建 agent/bot/自动化服务、或排查 SDK query 流问题（空回复、unrecognized_model 告警、消息类型、session resume、can_use_tool 闸门）时使用。
metadata:
  provenance: self-improving-skills

---
# claude-sdk-headless — claude-agent-sdk 无头调用（方舟网关）

以下要点在 2026-09 telegram-gateway 三 bot 迁移中实测验证（session 5ce5690a）。完整可运行示例：`~/.claude/telegram-gateway/gateway.py`（多 bot dispatcher：每 chat FIFO 队列、流式节流回传、can_use_tool 审批闸门）与同目录 `test_debug.py`（消息结构 dump）。

## 环境装配（单一真身）

- 凭证从 `~/.claude/settings.json` 的 `env` 读取：`ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN`，连同 `HTTPS_PROXY`/`HTTP_PROXY`/`NO_PROXY` 一起塞进 `ClaudeAgentOptions(env={...})`。**模型名取顶层 `model` 键**（`/model` 的写入处，2026-10-18 起为单一真身；env `ANTHROPIC_MODEL` 已移除——它存在时会压过 `model` 键、让 /model 无法持久化）。不要另存 token 副本，不要进命令行参数。
- `setting_sources=None` 可去掉项目级 settings 噪音，但**抑制不了用户级 hooks**：SessionStart 等钩子照常在 SDK 子进程里触发（流里会来 HookEventMessage）。每次 query 基础输入约 1.7 万 token（用户 CLAUDE.md + hooks 注入），做成本预估时算进去。

## 模型传入方式（踩坑）

- **模型名以 env `ANTHROPIC_MODEL` 形式传给 SDK，不要用 `options.model`**：显式传 `options.model="GLM-5.3-Flash[1m]"` 出现过空回复（请求本身成功、有 cost 有 session_id）；改为 env 继承后正常返回。模型名的**取值来源**是 settings.json 顶层 `model` 键（见上）。
- `[claude-code:unrecognized_model]` 告警是装饰性的：CLI 不认识非别名模型名，但请求照发、网关照收（`ResultMessage.model_usage`/`total_cost_usd` 可证）。看到它先别修，看 ResultMessage 再判断。

## query 流的消息类型

- 会出现的类型：`SystemMessage`(init)、`AssistantMessage`（content 是 TextBlock 等块）、`StreamEvent`、`ResultMessage`（终态）、`HookEventMessage`。
- `StreamEvent.event` 是**原生 Anthropic 流事件 dict**：仅当 `event["type"]=="content_block_delta"` 且 `event["delta"]["type"]=="text_delta"` 时取 `event["delta"]["text"]` 做增量。需要 StreamEvent 必须 `include_partial_messages=True`。
- 消费端必须**优雅忽略未知消息类型**（isinstance 分发 + 兜底 pass），新类型随 SDK 版本会出现。
- 终稿文本**优先取 `ResultMessage.result`**，比流式增量拼接可靠；流式只用于展示。
- 会话续接：保存 `ResultMessage.session_id`，下次 `options.resume=<id>`。

## can_use_tool 权限闸门

- 无值守 bot 场景的分层策略：只读工具（Read/Glob/Grep/Skill/WebSearch 等）直通；Bash 按预置脚本路径前缀放行；其余走远程审批（Telegram inline button + `asyncio.Future`，超时默认拒绝）。完整实现见 gateway.py。
- 陷阱：settings 文件里的 allow 规则会**遮蔽** can_use_tool（SDK 源码有 `_warn_if_can_use_tool_shadowed` 警告）——闸门不生效时先查 settings 的 allow 规则，别先怀疑自己的回调。

## 冒烟测试模板

新环境/新网关先跑最小验证（提示词"只回复两个字：正常"，断言回复 + 打印 session_id/cost_usd），别直接上业务。脚本见 `references/smoke_test.py`。

## 长驻 daemon 可靠性（2026-10-07 断线事故实测）

- **launchd KeepAlive 只保活进程不保活功能**：asyncio 事件循环可在外部扰动后整体冻结（实测：代理客户端自主重启掐线 → PTB 轮询冻结 → 进程假活 12 天，KeepAlive 永不触发）。长驻 Python 异步服务必须自带"不干活就自杀"的看门狗。
- 看门狗模式：定时（如 60s）做一次**全链路探测**（如 getMe，真实走 代理→远端→token 链路，零 LLM 消耗），任一探测对象距上次成功超阈值（如 300s）即 `os._exit(1)` 交 launchd 拉起；看门狗协程自身异常同样退出兜底。成功周期静默、每 N 周期打一条活体日志——健康检查就是 grep 心跳日志看时间戳是否停滞，别只看进程存在。
- **改 plist 的 EnvironmentVariables 后 `launchctl kickstart -k` 不重载 env**，必须 `bootout` + `bootstrap`。
- 多 bot/token 服务重启时新旧进程 token 交接有几秒重叠：启动要带重试 + 错峰，否则随机一两个起不来。

## 外发容错与预置脚本（2026-10-07 实测）

- **流式回传管道里，平台侧外发的瞬时失败绝不能上抛炸掉整场查询**：装饰性调用（如 Telegram `send_chat_action`）直接吞错；消息发送/编辑统一经重试包装（如 2 次线性退避），最终失败记日志放弃；只有 SDK 侧异常才上抛给顶层提示用户。实测一次代理抖动让 typing 指示器超时沿 `StreamSender.append→run_query` 一路上抛，把已流式过半的回复整场中止（gateway commit 5b7c428）。
- **别让模型每轮现场发明解析脚本**：bot 被问"有哪些 session 在跑"时反复手写临时 Python 扫 transcript，慢、易错、还答非所问。修法是类级的：预置一个与既有固定命令同口径的脚本（session_overview.py，与 /status 同源逻辑）、加进网关 Bash 白名单直通、CLAUDE.md 写明"先跑脚本、以脚本输出为准、按 Session ID 短码逐条列"；追问单个 session 细节才直接 Read/Grep transcript（cc-personal commit 75bec19）。用户口误术语（把 session 说成 "section"）也写进 CLAUDE.md。

## 跨 session 工具化（监视/注入）

- `~/.claude/projects/<munged-cwd>/<session-id>.jsonl` 即本机全部 session：mtime 判活跃；**transcript 前几行的 `cwd` 字段**可还原该 session 的工作目录（比从 munged 目录名反推可靠，dash 命名无法无歧义还原）；尾部 JSON 行取最近带 text/tool_use 的记录做动作摘要。
- 向空闲 session 注入指令：`options.resume=<id>` + `cwd=还原的工作目录` + 复用 can_use_tool 审批闸门；对 mtime 仍活跃（<2min）的 session 硬拒绝，防与终端里正在跑的实例撞车。

<!-- 来源: session 5ce5690a（telegram-gateway 三 bot 迁移）+ session 763ea9db（心跳看门狗/overseer）+ session eb9ff48c（外发容错/预置脚本）, 理由: SDK×方舟网关链路首版实测，模型传入方式/消息类型分发/权限闸门遮蔽/看门狗防假活/launchd env 重载/外发故障隔离/预置脚本替代现场发明解析均为类级可复用技术 -->
