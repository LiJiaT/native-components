---
name: claude-code-hook-pitfalls
description: 写 Claude Code hook 的四个实测坑——stdin 被吃静默失败、grep -c 零匹配退出码污染、SessionEnd 超时仅 1.5s 只做轻活、worker 自指入队要预过滤
metadata: 
  node_type: memory
  type: project
  originSessionId: c1bf0a34-ab30-4ee1-9935-7fb3a4581c44
  modified: 2026-10-08T14:29:11.368Z
---

# Claude Code hook 四个实测坑（写任何 hook 前对照检查）

1. **stdin 被吃静默失败**（最危险）：hook 脚本里 `input=$(cat)` 消费 stdin 后再传给 python，若漏传则 python json.load 拿到空输入 → 抛异常 → 静默 exit 0，队列永远不写入且无任何报错。修法：显式喂回 `echo "$input" | python -c ...`
2. **grep -c 零匹配退出码 1**：`count=$(grep -c pattern file || echo 0)` 零匹配时 grep 输出 '0' 且退出码 1，`|| echo 0` 又追加一个 0，计数变 '0\n0' 污染下游。修法：`grep -c ... || true` 或先判断输出
3. **SessionEnd 默认超时仅 1.5 秒**（官方契约，stdin 含 session_id/transcript_path/reason）：hook 里绝不做重活。正确模式：hook 只追加一行到队列文件然后 exit 0，重活由 nohup 拉起后台 worker（mkdir 原子锁防重复拉起）
4. **worker 自指入队**：worker 内层 `claude -p` 会话结束也触发 SessionEnd 把自己入队，烧光每日预算。修法：入队前做廉价 tool_use 计数预过滤（内层蒸馏会话 tool_use 很少，直接拦掉）

- 参考：SessionStart 注入提示用 hookSpecificOutput.additionalContext；产出物 `~/.claude/hooks/distill-enqueue.sh` 与 `distill-notify.sh` 可作参考实现

<!-- 来源: session 64335c1a, cand-1765c4, 理由: 坑全是静默发生、排查成本高（尤其 stdin 静默失败），DESIGN/STATUS 只记架构未记坑细节 -->
