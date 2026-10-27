---
user-invocable: false
name: cc-connect-bridge
description: 当安装、配置、迁移或排查 cc-connect（把 Telegram 等 IM 桥接到本地 Claude Code 的 brew 工具）时使用。
metadata:
  provenance: self-improving-skills
---

# cc-connect-bridge — IM 桥接 cc-connect 配置与迁移

机制均从 cc-connect v1.5.0 源码实测验证（2026-10-08，telegram-gateway → cc-connect 迁移 Phase 0-4 当日全部完成，session 739e5b85）。源码工作副本在 /tmp（易失），故结论固化于此，不必再考古源码。
**现役版本：v1.5.1-beta.3**（2026-10-19 升级，二进制 `~/.cc-connect/bin/cc-connect`，launch.sh 指向；brew 稳定版 1.5.0 保留作回滚）。升级原因见下文「回合挂死」节。

## 核心机制（写配置前必知）

- **`${ENV}` 占位符对整个 config.toml 生效**：启动时 os.ExpandEnv 全量展开；daemon install 还会扫描占位符并从当前进程 env 捕获（daemon/manager.go `captureConfigEnvPlaceholders`）→ 密钥零落地：config 全写 `${VAR}`，由启动器注入环境。**占位符未设置只 WARN 不报错**，必须检查启动日志无 "references unset variable"。
- **Provider 全局声明、project 必须显式 `provider_refs` 引用**（2026-10-17 源码再核实，修正 10-08 的错误结论）：全局 `[[providers]]`（name/api_key/base_url/agent_types/model）**不会**按 agent_types 自动挂到 project——v1.5.0 只在 project 的 `[projects.agent]` 下出现 `provider_refs = ["<name>"]` 时才合并进该 agent（`config.go ResolveProviderRefs`：`len(refs)==0 → continue`）。agent_types 只是引用时的类型过滤器。未引用时模型实际来自进程 env（`ANTHROPIC_MODEL`），`[[providers]]` 纯装饰（2026-10-18 补充实测：即使**正确引用**了 provider，进程 env 里若存在 `ANTHROPIC_MODEL` 仍会压过 provider 的 `model` 字段——本机 launch.sh 会从全局 settings.json 的 env 段把它带进来，导致 bot 实际模型与 config 里写的 `model` 不一致；删掉该 env 键后子进程 `--model` 才等于 provider 配置值）——表象是 bot 照常工作，但 `/model` 菜单落到内置 Sonnet/Opus 兜底清单。**鉴别法**：/model 出现 Sonnet/Opus = provider 没挂上。
- **`/model` 切模型（原生命令）**：`/model` 看菜单（inline 按钮）、`/model switch <别名|序号|模型名>` 切换，持久化 models-store.json，对当前及后续 session 生效。可选列表配在 provider 的 `[[providers.models]]`（`model` + `alias`）；列表优先级：provider 配置 > `{base_url}/v1/models` API（只读 `ANTHROPIC_API_KEY`，AUTH_TOKEN 场景取不到）> 内置 Claude 模型名兜底。方舟 1M 型号带 `[1m]` 后缀。
- **配了 base_url 的 provider**：给 claude CLI 注入 `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN`（Bearer）并清空 `ANTHROPIC_API_KEY`——方舟（Ark）等 Anthropic 协议端点直接对接；父进程的 `ANTHROPIC_*` env 也在透传白名单里。
- **模型 id 含 `[1m]` 即原生按 1M 上下文识别**（回复 footer 的 ctx% 指示器）；自定义 router 模型名不含时才需手动覆盖 context window。
- **权限模式**：default / acceptEdits / plan / auto / bypassPermissions / **dontAsk**（未预授权自动拒绝，安全推荐）。dontAsk + `allowed_tools` 可复刻旧 gateway 的"预置脚本直通"白名单，替代自写子串判定。
- **全局 settings 会穿透 IM 审批（P0 级坑，2026-10-08 实测）**：claude CLI 子进程默认加载用户全局 `~/.claude/settings.json`，其中的 allow-all 规则（如 `Bash(*)`/`Write(*)`）会让每个工具调用静默自批，IM 审批闸门形同虚设。每个 project 必须设 `cmd = "claude --setting-sources project"` 屏蔽全局、只加载 project 级（对齐 SDK `setting_sources=None` 隔离语义；附带收益：单轮输入 69k→~30k）。

## 配置层级（易错点）

- `admin_from` 在 `[[projects]]` 层级；`token`/`allow_from`/`proxy`/`enable_reactions`/`progress_style` 在 `[projects.platforms.options]`；`work_dir`/`mode` 在 `[projects.agent.options]`。
- `filter_external_sessions = false`（默认）使 /list 可见同一 work_dir 下终端直开的 session——"跨入口可见"需求（如 Overseer）依赖它。
- 完整可运行 config.toml + 凭证注入 launch.sh 实例见 [references/config-and-launcher.md](references/config-and-launcher.md)。

## 凭证注入模式（launch.sh）

config 不含密钥；启动器从两个来源注入进程环境后 exec：① dotenv（`set -a; source .env; set +a`）；② `~/.claude/settings.json` 的 env 段（python3 读 JSON → shlex.quote 生成 export 行 → `eval` 捕获执行，不回显不落日志）。launchd 化时 ProgramArguments 直接指向该启动器。

## 验证手法

- **dummy token 干跑**：用假 token（`123456:dummy`）启动，日志出现 `getMe unauthorized` 即证明 配置解析 → ${ENV} 展开 → TG 代理链路 全通（更早的 context deadline exceeded 是代理抖动，内置 backoff 自动重试，无需自建看门狗）。
- macOS 无 `timeout` 命令：`cmd & sleep 12; kill $!` 再看日志。
- 日志在 `CC_LOG_FILE` 指定处（默认 `~/.cc-connect/logs/cc-connect.log`）。

## 迁移切换与无人值守自测（Phase 3-4 实战，2026-10-08）

- **逐身份切换节拍**（一次只切一个，token 互斥）：旧 gateway 摘 bot（`plutil -replace EnvironmentVariables.GATEWAY_BOTS` → **bootout+bootstrap**；kickstart 不重读 plist env）→ config.toml 加该 project → 重启 cc-connect → 自测。摘最后一个 bot 后直接 bootout 旧服务整体停机（零 bot + KeepAlive = 崩溃循环）。
- **webhook 自测通道**：config 加 `[webhook]`（port 9111 + token），POST `{"project","session_key","prompt"}` 即程序化跑完整 agent→TG 链路，无人值守验证每个身份。session busy 时 prompt 直接丢弃（fire-and-forget）；自测 prompt 必须是"不用任何工具、只回复 XX"，否则审批请求会挂起等 IM 回复。判据看日志 `turn complete` + `webhook: prompt executed`。
- **launchd 服务化**：plist（KeepAlive/RunAtLoad/ThrottleInterval=10）ProgramArguments 指向 launch.sh；启动命令加 `--force`（清 stale 实例锁，配合 KeepAlive 重启不卡死）。kill -9 实测 22s 自愈、全部 bot 自动重连。崩溃韧性测试前先等 `turn complete`，否则会打断在跑的自测回合（webhook 不会重放）。
- 切换命令序列与 plist 实例见 [references/config-and-launcher.md](references/config-and-launcher.md)。

## 回合挂死与自助恢复（2026-10-19 实测，含源码依据）

- **挂死形态**：某回合异常结束（如 API 400 / 代理掐断）后**会话锁不释放**，此后该 bot 所有消息 `queued for busy session` 永不处理。实测 alfred 挂 7.5 小时、3 条消息积压。
- **`/stop` 在 v1.5.0 上救不了忙锁**（修正 2026-10-19 早先的错误结论）：命令解析确实在锁检查之前（states 可被删除），但 `Session.busy` 是独立的裸 bool，由挂死回合的 goroutine 持有，`/stop` 删 interactiveState 不会释放它。上游 #1829 明确实测 `/stop` 不解锁、只有重启能清；修复 commit `0dd7357202` 才加上 **stop-path release + 带 generation 的 stale-lock 自愈**（`BreakStaleLock`：锁持有 >2 分钟且**确认 agent 子进程已死**才破锁），该修复只进 v1.5.1-beta.2+，**v1.5.0 stable（brew）没有**。
- **程序化恢复（重）**：webhook 与 `send` CLI 都救不了——webhook 的 `executePrompt` 自己就 `session.TryLock()`，锁住即 `session busy, queued prompt dropped`；`send` 只支持出站消息。**唯一程序化恢复 = 重启 cc-connect 本体**（`launchctl kickstart -k gui/501/com.lidaonian.cc-connect`）。重启后排队消息**不重放**，需用户重发。
- **`reset_on_idle_mins` 救不了锁死**：busy 分支在队列化后直接 return，`maybeAutoResetSessionOnIdle` 只在抢锁成功的路径上执行。
- **看门狗**：`~/.cc-connect/watchdog.py` + launchd `com.lidaonian.cc-connect-watchdog`（StartInterval 300s）。三重信号防误杀：① 近期有排队消息且等待 > 10 分钟 ② 近期无 turn complete ③ 所有 claude 子进程及**其子进程树**均无进展（无 ESTABLISHED TCP 且 CPU 时间不增长，20s 采样）。命中 → TG 通知（overseer bot，走代理）+ 重启，15 分钟冷却。`--dry-run` / `--log <fixture>` 可离线验证；`CC_WD_PROC_PATTERN` 可换进程匹配（测试用）。已过四场景验证（挂死/健康/长任务活跃不误杀/无子进程）。
- **纯文本模型 + 图片 = 400 且可能引发挂死**：GLM-5.3（旗舰）不吃图，GLM-5.3-Flash / DeepSeek-V4.1-Flash 才支持视觉。

## 铁律与坑

- **一个 bot token 只允许一个消费者**（Telegram getUpdates 互斥）：灰度/试验必须经 BotFather 注册独立测试 bot；生产 token 挂给新消费者前必须先从旧 gateway 摘除（GATEWAY_BOTS + kickstart）。
- brew 不读系统代理：`https_proxy=http://127.0.0.1:7897 http_proxy=… HOMEBREW_NO_AUTO_UPDATE=1 brew install cc-connect`。
- 源 .env 未必有代理变量（旧 gateway 用代码默认值兜底）——非密钥的代理地址直接写死进 config。
- `reset_on_idle_mins`（空闲后自动换新 session，避免 context 漂移）默认值随版本变（v1.5.0 实测日志显示 default 0）；迁移时按旧行为显式设置，别依赖默认。

<!-- 来源: session 739e5b85（telegram-gateway → cc-connect 迁移 Phase 0-1 源码研读 + Phase 3-4 生产切换实战）， 理由: 机制均经源码研读+dummy token 干跑+四身份生产切换实测；--setting-sources project 审批穿透修复与 webhook 无人值守自测是迁移成败关键；源码副本在 /tmp 易失 -->
