---
name: apple-reminders
description: 操作本机 Apple 提醒事项（Reminders）：创建、改期、完成、删除、查询提醒，解析自然语言截止时间并落成提醒。当用户说"提醒我"、"建个提醒"、"加到提醒事项"、"帮我把 X 事项设个提醒"、会议/录音纪要要为待办建提醒、或提到 remindctl / Apple Reminders / 提醒事项 App 时使用。
---

# Apple Reminders 操作（remindctl + AppleScript 回退）

以下打法全部本机实测（2026-09 系列会话验证，TCC 机制与 AppleScript 回退 2026-09-16 实测有效）。

## 首选通道：remindctl

本机 `/opt/homebrew/bin/remindctl`（steipete/remindctl **0.3.7**，2026-10-09 经 `brew trust steipete/tap` + `brew upgrade` 升级，升级后 TCC 权限完好、`search` 实测可用）。核心命令：

```bash
remindctl show                                  # 今日及逾期概览
remindctl list <清单名>                          # 某清单条目
remindctl search <关键词>                        # 搜标题/备注（0.3.7 实测可用）
remindctl add --title "事项标题" --due "YYYY-MM-DD HH:mm" [--notes "..."] [--priority n]
remindctl complete <id-or-title>                # 完成
remindctl edit <id-or-title> --title/--due/--notes
remindctl delete <id-or-title>
remindctl export                                # 导出（JSON/CSV）
remindctl doctor                                # 权限/环境诊断
remindctl status                                # 权限状态
```

- `--due` 接受 `YYYY-MM-DD HH:mm`；只给日期时按上下文补默认时刻（用户没说时刻，会议类待办惯例 20:00）。
- 未指定清单时落在默认清单。
- 查"是否已有类似提醒"用 `search`（有界查询），不要用 osascript 全库 whose 扫描（见下方坑 2）。

## TCC 权限失败回退（实测关键）

`remindctl` 报 `Reminders access denied` 时的正确处理顺序：

1. **不要反复折腾 `remindctl authorize`**。TCC 按「负责调用的宿主 App」授权：用户在自己终端跑 authorize，授权的是那个终端 App，不是 AI 的宿主进程（VS Code 扩展 node 等）。系统设置→隐私→提醒事项里看到"终端"已开也没用，且该设置页没有手动添加按钮。
2. **直接改走 AppleScript 自动化通道**（与 EventKit 是不同权限类别）。执行时系统弹「"xxx"想要控制"提醒事项"」授权框，请用户点允许，一次授权长期有效：

```bash
osascript << 'EOF'
on mkDate(y, mo, d, h, mi)
    set dt to current date
    set day of dt to 1          -- 先设 1 号，再逐年逐月赋值，避免月尾溢出（如 8/31 设 2 月）
    set year of dt to y
    set month of dt to mo
    set day of dt to d
    set time of dt to h * 3600 + mi * 60
    return dt
end mkDate

tell application "Reminders"
    make new reminder with properties {name:"事项标题", due date:my mkDate(2026, 9, 16, 20, 0)}
end tell
return "OK"
EOF
```

- 同一条 osascript 内可循环 `make new reminder` 批量创建多条。
- 改期用 `set due date of theReminder to date "2026年9月18日 20:00:00"`（本地中文日期格式；要保留原时刻就把原时间拼进新日期，否则归零）。

## 坑与红线（全部实测踩过）

1. **批量创建返回值陷阱**：osascript 批量 make 循环的返回值只回传最后一个 ID，不能据此认为只建了一条。核对用 `get name of reminders of list "<清单名>" whose completed is false`（列表内过滤，快）。
2. **禁止全库扫描验证**：`reminders whose name contains ...` 这类全库 whose 查询提醒多时必超 2 分钟。创建命令返回 `OK` 即可采信（App 直接确认）；要用户复核就让他开 App 看。
3. **报错先怀疑沙箱**：remindctl/osascript 在沙箱内被拦截会误报成权限问题；权限类报错先确认运行环境是否沙箱，再走上面的回退链。
4. **失败如实报告**：创建与验证均失败时，明确报告失败事项和原因，不得宣称已创建。
5. **mkDate 先 day=1**：AppleScript 直接 `make date` 设年月日在月尾会溢出跳月，必须先 `set day of dt to 1` 再逐年逐月赋值。
6. 完成后向用户简要列出已创建的提醒及实际截止时间；等用户补日期的事项单独列出。

相关技能：`apple-notes`（备忘录读写）；纪要→提醒的完整工作流见 alfred 项目 `~/cc-personal/alfred/.claude/skills/{family-meeting-minutes,workday-voice-summary}/`。
