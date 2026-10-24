#!/bin/bash
# 后台蒸馏 worker 包装器：真实逻辑在 worker.py（跨平台锁、失败保留、游标、去重）。
# 环境变量：WORKER_DRY_RUN=1 / MAX_JOBS_PER_DAY / DISTILLER_MODEL / DISTILLER_CMD
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$DIR/worker.py" "$@"
