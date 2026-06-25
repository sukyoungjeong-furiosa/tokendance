## 도구
- `python3 scripts/config.py get <KEY>` — 설정/경로 조회 (SLACK_CHANNEL, MAX_WORKERS 등).
- `python3 scripts/cycle.py` — 기계 단계를 대신 해준다: queued 일감을 MAX_WORKERS 까지 디스패치하고 지식 harvest 를 돌린 뒤, 네가 판단할 일거리를 JSON 으로 돌려준다 (`review` / `needs_human` / `blocked` / `inbox_pending` / counts).
- `python3 scripts/inbox.py list|add` — 사람 입력 큐.
- `python3 scripts/tasks.py new|list` — 일감 생성/조회.
- `python3 scripts/status.py set <id> --state …` — 일감 상태의 유일한 변경 통로.
- `python3 scripts/report.py` — 현재 상태로 리포트를 만들어 state/reports 에 기록하고 텍스트를 돌려준다.
- `bash scripts/launch-worker.sh <id>` — 워커를 격리 worktree 에서 띄운다(보통 cycle.py 가 호출).
- Slack 이 켜져 있으면 MCP: `slack_read_channel` / `slack_send_message`.
