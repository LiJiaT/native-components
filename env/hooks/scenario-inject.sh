#!/bin/bash
# scenario-inject.sh — UserPromptSubmit hook 包装器
#
# 职责：解析 python3 路径（hook 环境 PATH 不可靠，见 memory bg-shell-pitfalls），
#       实际逻辑在 scenario-inject.py。
# 铁律：任何异常都必须静默 exit 0，绝不阻断用户 prompt。
# 机制说明：~/.claude/scenarios/README.md

PY=/opt/homebrew/bin/python3
[ -x "$PY" ] || PY=/usr/bin/python3
[ -x "$PY" ] || exit 0

exec "$PY" "$(dirname "$0")/scenario-inject.py"
