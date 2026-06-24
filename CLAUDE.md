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

## Slack (self-DM 모드)
- 채널 ID 는 `config.local.md` 의 `SLACK_CHANNEL` 에 둔다(인스턴스/보안 값이라 git 추적 안 함). 미설정이면 Slack 연동을 건너뛴다. 템플릿: `config.example.md`.
- MCP는 사용자 계정으로 동작하므로 마스터가 보낸 메시지도 "사용자"로 표시된다. 따라서:
  - **출력 마커**: 마스터가 보내는 모든 메시지는 맨 앞에 `🤖 tokendance` 로 시작한다.
  - **자기 메시지 무시**: DM을 읽을 때 `🤖 tokendance` 로 시작하는 메시지(=마스터 자신의 출력)는 건너뛰고, 그 외 사람 메시지만 inbox로 넣는다.
  - **중복 방지**: `state/slack.cursor` 에 마지막 처리한 메시지 ts를 저장. 읽을 때 `oldest=<cursor>` 로 그 이후만 가져온다.
