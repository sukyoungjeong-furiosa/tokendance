#!/usr/bin/env bash
# MVP stub. 실제 worktree + 공통 artifact 셋업은 dogfood 백로그 항목 1에서 구현.
# 인자: $1 = task-id
set -euo pipefail
TASK_ID="${1:?task-id required}"
echo "[prepare-worktree] stub for task ${TASK_ID} (no-op; dogfood backlog #1에서 구현 예정)"
exit 0
