#!/bin/bash
# SessionEnd hook：把 session 排入蒸馏队列。必须快（默认超时 1.5s）。
# 实际解析在 enqueue.py：不 eval 输入、逐行 JSON 解析、路径原样保留。
# 任何失败都静默 exit 0（旁路 hook 不阻塞会话），诊断写 queue/enqueue.log。
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$DIR/enqueue.py" 2>/dev/null || true
exit 0
