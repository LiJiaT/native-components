# cc-connect 配置与启动器实例（v1.5.0 实测，2026-10-08）

## config.toml（~/.cc-connect/config.toml，密钥零落地）

```toml
language = "zh"

# 方舟 provider（Anthropic 协议端点，全局声明后按 agent_types 自动匹配 project）
[[providers]]
name = "ark"
api_key = "${ANTHROPIC_AUTH_TOKEN}"
base_url = "${ANTHROPIC_BASE_URL}"
agent_types = ["claudecode"]
model = "GLM-5.3-Flash[1m]"   # 含 [1m] 即按 1M 上下文识别

[[projects]]
name = "spike"
admin_from = "${OWNER_TELEGRAM_USER_ID}"   # 注意：在 [[projects]] 层级
filter_external_sessions = false           # /list 可见外部终端 session

[projects.agent]
type = "claudecode"

[projects.agent.options]
work_dir = "/Users/lidaonian/cc-personal/alfred"
mode = "default"   # 验证审批形态；复刻预置脚本直通用 dontAsk + allowed_tools
cmd = "claude --setting-sources project"   # 必须：屏蔽全局 settings 的 allow-all，否则 IM 审批被穿透

# webhook 无人值守自测端点（迁移自检用，观察期后可关）
[webhook]
enabled = true
port = 9111
path = "/hook"
token = "${WEBHOOK_TOKEN}"   # 本地回环端点；token 从启动器 env 注入

[[projects.platforms]]
type = "telegram"

[projects.platforms.options]
token = "${CC_TEST_BOT_TOKEN}"
allow_from = "${OWNER_TELEGRAM_USER_ID}"
proxy = "http://127.0.0.1:7897"   # .env 无 PROXY_URL，非密钥直接写死
enable_reactions = true            # 收到消息即 ⚡
progress_style = "compact"
```

生产 project 模板同构：work_dir 换成各身份工作区（travel-planner / fitness-coach / alfred / overseer），token 换 `${TELEGRAM_TOKEN_*}`；灰度期逐个取消注释，加一个同时在旧 gateway 摘一个（token 互斥铁律）。

## launch.sh（~/.cc-connect/launch.sh，chmod 700）

```bash
#!/bin/bash
# 密钥只在两个源文件：gateway .env 与 settings.json env 段；本脚本不含密钥
set -euo pipefail

set -a
source "$HOME/.claude/telegram-gateway/.env"
set +a

# settings.json env 段逐项 export（shlex.quote，经 eval 捕获，不回显）
eval "$(python3 - <<'PYEOF'
import json, pathlib, shlex
env = json.loads((pathlib.Path.home() / ".claude" / "settings.json").read_text()).get("env", {})
for k, v in env.items():
    print(f"export {k}={shlex.quote(str(v))}")
PYEOF
)"

mkdir -p "$HOME/.cc-connect/logs"
export CC_LOG_FILE="$HOME/.cc-connect/logs/cc-connect.log"
exec /opt/homebrew/opt/cc-connect/bin/cc-connect --force --config "$HOME/.cc-connect/config.toml"
# ^ --force：清 stale 实例锁，launchd KeepAlive 重启不卡死
```

## dummy token 干跑验证

```bash
CC_TEST_BOT_TOKEN="123456:dummy-for-config-validation" ~/.cc-connect/launch.sh > /tmp/cc-dryrun.log 2>&1 &
sleep 12; kill $!
# ~/.cc-connect/logs/cc-connect.log 出现 getMe unauthorized
# = 配置解析 / ${ENV} 展开 / TG 代理链路全通（真实 token 到位后换掉即可）
```

## 逐身份切换命令序列（Phase 3 实战，每身份一轮）

```bash
# 1. 旧 gateway 摘 bot（bootout+bootstrap 必须，kickstart 不重读 plist env）
plutil -replace EnvironmentVariables.GATEWAY_BOTS -string "<剩余bots>" \
  ~/Library/LaunchAgents/com.lidaonian.telegram-gateway.plist
launchctl bootout gui/$(id -u)/com.lidaonian.telegram-gateway; sleep 2
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.lidaonian.telegram-gateway.plist
sleep 26   # 等"已上线"日志确认剩余 bot 就绪

# 2. config.toml 启用该 project（token 已从旧侧释放）→ 重启 cc-connect
pkill -f "cc-connect --config"; sleep 3
~/.cc-connect/launch.sh > /dev/null 2>&1 & disown
sleep 14; grep -E "connected|platform ready" ~/.cc-connect/logs/cc-connect.log | tail -4

# 3. webhook 无人值守自测（prompt 必须"不用工具只回复"，防审批挂起）
curl -s -X POST http://127.0.0.1:9111/hook \
  -H "Authorization: Bearer $WEBHOOK_TOKEN" -H "Content-Type: application/json" \
  -d '{"project":"<name>","session_key":"telegram:<chat_id>:<user_id>","prompt":"迁移自测，请只回复「XX 自检 OK」，不要使用任何工具。","event":"migration-selftest"}'
sleep 35; grep -E "turn complete|webhook: prompt executed" ~/.cc-connect/logs/cc-connect.log | tail -2
# 通过判据：turn complete（tools=0，5-8s/轮）+ prompt executed
```

摘最后一个 bot 后：`launchctl bootout` 旧服务整体停机，**不再 bootstrap**（零 bot + KeepAlive = 崩溃循环）；plist/仓库/.env 保留作回滚。

## launchd plist（~/Library/LaunchAgents/com.lidaonian.cc-connect.plist）

```xml
<dict>
    <key>Label</key><string>com.lidaonian.cc-connect</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>/Users/lidaonian/.cc-connect/launch.sh</string>
    </array>
    <key>WorkingDirectory</key><string>/Users/lidaonian/.cc-connect</string>
    <key>EnvironmentVariables</key>
    <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
    <key>KeepAlive</key><true/>
    <key>RunAtLoad</key><true/>
    <key>ThrottleInterval</key><integer>10</integer>
    <key>StandardErrorPath</key><string>/Users/lidaonian/.cc-connect/logs/launchd.err</string>
    <key>StandardOutPath</key><string>/Users/lidaonian/.cc-connect/logs/launchd.log</string>
</dict>
```

bootstrap 前先 `pkill -f "cc-connect --config"` 杀手工实例（`--force` 也兜底）。韧性验证：`kill -9 <pid>` 后 ~22s 内 KeepAlive 拉起新实例、全部 bot 重连；崩溃测试前先等 `turn complete`，否则打断在跑的自测回合（webhook 不重放）。
