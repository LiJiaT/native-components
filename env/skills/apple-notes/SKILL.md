---
name: apple-notes
description: 操作本机 Apple 备忘录（Notes）：读取、搜索、创建、保存笔记正文。当用户说"存到备忘录"、"记到 Notes"、"看看我备忘录里"、"找一下上周的笔记"、会议/录音纪要要保存为备忘录、或提到 Apple Notes / 备忘录 App 时使用。
---

# Apple Notes 操作（osascript 实测模式）

以下打法全部本机实测（2026-09 系列会话验证）。

## 读取：列出与取正文

Notes 的 body 是 HTML，直接读会满屏标签。标准管道：

```bash
# 列最近 N 天修改过的笔记标题
osascript -e 'tell application "Notes" to get name of every note whose modification date > (current date) - 30 * days'

# 取某条正文并去掉 HTML 标签与空行
osascript -e 'tell application "Notes" to get body of note "<标题>"' \
  | sed 's/<[^>]*>//g' | sed '/^[[:space:]]*$/d'
```

更稳的读取用 `plaintext` 属性（免 sed），并可按创建窗口取最新一条（限定清单/关键词 + 排除当天，见下方坑 3）：

```bash
osascript << 'EOF'
tell application "Notes"
    set midnight to current date
    set time of midnight to 0
    set cutoff to (current date) - 10 * days
    set matches to (every note whose name contains "纪要" and creation date < midnight and creation date > cutoff)
    if (count of matches) is 0 then return "NONE"
    set best to item 1 of matches
    repeat with n in matches
        if creation date of n > creation date of best then set best to contents of n
    end repeat
    return "TITLE: " & (name of best) & linefeed & "CREATED: " & ((creation date of best) as string) & linefeed & "----" & linefeed & (plaintext of best)
end tell
EOF
```

## 写入：HTML body 才有格式

`make new note with properties {name:标题, body:正文}` 的 body 必须是 HTML（`<div>`/`<b>`/`<br>` 等）并指定字号，否则存出无格式纯文本。实测格式基准：**标题 21px、章节标题 15px、正文 11px**：

```bash
osascript << 'EOF'
set noteTitle to "笔记标题"
set noteBody to "<div><b><span style='font-size: 21px'>笔记标题</span></b></div><div><br></div><div><span style='font-size: 11px'>正文第一段</span></div><div><span style='font-size: 15px'><b>章节标题</b></span></div><div><span style='font-size: 11px'>章节内容</span></div>"
tell application "Notes"
    make new note with properties {name:noteTitle, body:noteBody}
end tell
return "OK"
EOF
```

- 复杂内容先在临时文件里拼好 HTML 再读进来，避免 heredoc 内引号转义灾难。
- 避免内容里的弯引号/特殊字符进 AppleScript 字符串字面量。

## 坑与红线（全部实测踩过）

1. **同日重跑自引用**：按 creation date 检索"上一期"纪要/报告时，同日重跑会把当天早先版本当"上一期"。过滤条件必须加 `creation date < (今天 00:00)`（即 `time of midnight to 0` 后取 `< midnight`）硬性排除当天。
2. **返回值陷阱**：AppleScript 循环 make 的返回值不可靠（批量场景只回传最后一个），写入类操作以 `return "OK"` 作为成功依据即可，勿从循环返回值推断创建数量。
3. **验证别做过头**：保存返回 `OK` 即可采信；不要为验证做全库 whose 扫描（笔记多时超时）。
4. **报错先怀疑沙箱**：osascript 在沙箱内被拦截会误报权限问题；先确认运行环境再走授权排查。
5. Notes 与 Reminders 的 TCC 授权相互独立；Reminders 侧的宿主授权机制见 `apple-reminders` 技能。

相关技能：`apple-reminders`（提醒事项，纪要待办配套）；完整"纪要→Notes+Reminders"工作流见 alfred 项目 `~/cc-personal/alfred/.claude/skills/{family-meeting-minutes,workday-voice-summary}/`。
