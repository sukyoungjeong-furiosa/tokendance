## 도구
- `python3 scripts/config.py get <KEY>` — 설정/경로 조회 (SLACK_CHANNEL, MAX_WORKERS 등).
- `python3 scripts/cycle.py` — 기계 단계를 대신 해준다: queued 일감을 MAX_WORKERS 까지 디스패치하고 지식 harvest 를 돌린 뒤, 네가 판단할 일거리를 JSON 으로 돌려준다 (`review` / `needs_human` / `blocked` / `inbox_pending` / counts).
- `python3 scripts/inbox.py list|add` — 사람 입력 큐.
- `python3 scripts/tasks.py new <id> [--repo <PATH>]` — 일감 생성/조회. `--repo` 로 **타겟 레포**를 지정하면 워커가 그 레포 worktree 에서 작업한다(생략=tokendance 도그푸딩). 비-tokendance 레포도 동일하게 지원.
- `python3 scripts/status.py set <id> --state …` — 일감 상태의 유일한 변경 통로.
- `python3 scripts/report.py` — 현재 상태로 리포트를 만들어 state/reports 에 기록하고 텍스트를 돌려준다.
- `bash scripts/launch-worker.sh <id> [--resume]` — 워커를 격리 worktree 에서 띄운다(보통 cycle.py 가 호출). `--resume` 은 기록된 세션을 이어받아 기동(없거나 만료면 fresh 폴백); 살아있는 워커가 있으면 중복 기동하지 않는다.
- `python3 scripts/slack.py post "<텍스트>"` — Slack 봇 DM 으로 전송(켜져 있을 때만; 아니면 무해). 수신은 supervisor 가 60초마다 자동으로 inbox 에 넣어주므로 너는 pull 하지 않는다.
