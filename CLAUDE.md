# tokendance

상시 호스트 위에서 코딩 일감을 자율 관리하는 마스터 에이전트 하네스.
설계: docs/superpowers/specs/2026-06-24-tokendance-master-agent-design.md

## 불변 규칙 (마스터·워커 공통)
- status.json 변경은 `scripts/status.py` 로만.
- 워커 기동은 `scripts/launch-worker.sh` 로만.
- 상태: queued | running | needs_human | blocked | review | done | failed. failed 는 failure_reason 필수.
- 파일 소유: progress/log/steer.cursor=워커, review/reports=마스터, steer.md=append-only, status.json=status.py.
- 타겟 레포 변경은 브랜치/PR만. main 직접 push 금지.
- 모든 자동화 도구는 Python 표준 라이브러리만 사용(외부 패키지/jq 금지).

## 환경
- claude 바이너리: 환경변수 `TOKENDANCE_CLAUDE`.
- root 실행이라 claude 기동 시 `IS_SANDBOX=1` + `--dangerously-skip-permissions` 필요.
- supervisor 기동/정지: `scripts/start.sh` / `scripts/stop.sh`.

## Slack (봇 토큰 모드)
- `config.local.md` 에 `SLACK_BOT_TOKEN`(xoxb) 과 `SLACK_CHANNEL`(상대 user id)을 둔다(git 추적 안 함; 템플릿 `config.example.md`). 둘 중 하나라도 없으면 Slack 연동을 건너뛴다.
- **수신**: supervisor 가 60초마다 `scripts/slack.py poll` 로 봇↔사용자 DM 의 새 사람 메시지를 inbox 로 옮기고(LLM 불필요), 새 메시지가 있으면 마스터를 즉시 깨운다. cursor=`state/slack.cursor`(ts 초과분만, exclusive).
- **발신**: `scripts/slack.py post "<텍스트>"`. 봇이 "tokendance" 정체성으로 보내므로 별도 마커 불필요. 폴링은 사람(user) 메시지만 집어 봇 자기 출력은 자동 무시.
