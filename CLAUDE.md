# tokendance

상시 호스트 위에서 코딩 일감을 자율 관리하는 마스터 에이전트 하네스.
설계: docs/superpowers/specs/2026-06-24-tokendance-master-agent-design.md

tokendance 레포는 **컨트롤 플레인**일 뿐, 워커는 **임의의 타겟 레포**에서 작업한다(멀티레포). 일감의 타겟은 `tasks.py new <id> --repo <PATH>` 로 지정하며 status.json 의 `repo` 필드에 저장된다(생략 시 tokendance 자기 자신 = 도그푸딩). worktree 는 어느 레포든 `<tokendance ROOT>/state/worktrees/<id>`(브랜치 `tokendance/<id>`)에 만들어지고, 워커 cwd 가 된다. 워커는 tokendance 메타(progress/checkpoint/finish/log)를 `TOKENDANCE_ROOT` 절대경로로 기록하므로 worktree 가 비-tokendance 레포여도 동작한다. 회수: `git -C <repo> worktree remove/prune`, 브랜치 삭제 `git -C <repo> branch -D tokendance/<id>`.

## 워크트리 아티팩트 재사용 (레포별 opt-in)
타겟 레포가 무거운 아티팩트(libtorch 등)를 매 worktree 마다 다시 받지 않게, 메인 체크아웃의 것을 symlink/env 로 재사용한다. 둘 다 메인 레포 체크아웃에서 읽으므로 미추적 드롭만으로 동작하고, 파일이 없는 레포(tokendance 도그푸딩 등)는 무영향이다.
- `<repo>/.tokendance-worktree.manifest`: worktree 로 symlink 할 경로 목록(한 줄당). `prepare-worktree.sh` 가 메인레포→worktree 로 링크(읽기 재사용; 원본 불변). dvc 포인터처럼 추적 콘텐츠와 gitignore 추출본이 섞인 디렉토리는 부모 경로 한 줄이면 되고, "자식 1단계 병합"으로 추적 포인터는 보존하고 추출본만 링크된다. 없으면 기본값(node_modules/target/.venv…).
- `<repo>/.tokendance-worktree.env`: `launch-worker.sh` 가 worktree 생성 후 source 해 워커 프로세스 env 에 주입(`$WORKTREE` 참조 가능). 예) npu-tools 는 `LIBTORCH="$WORKTREE/artifacts/furiosa-libtorch/current"` → 워커가 수동 export 없이 libtorch 빌드/테스트 가능.

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
- supervisor 기동/정지: `scripts/start.sh` / `scripts/stop.sh`. start.sh 는 `scripts/supervise.sh` keepalive 래퍼를 `setsid` 로 띄우고(래퍼 pid=`supervisor.pid`, 프로세스그룹 리더), 래퍼가 supervisor.py 가 죽으면 자동 재기동한다(빠른 크래시 백오프, `state/supervisor.lock` flock 로 중복 방지). stop.sh 는 그룹째 종료한다.
- supervisor 관측성: `state/supervisor.ticks.jsonl`(tick 당 JSON; 5MB 초과 시 `.jsonl.1` 로 회전, 디스크 bounded), `state/supervisor.metrics.json`(요약 스냅샷; `python3 scripts/supervisor.py metrics`), `state/supervisor.respawn.log`(재기동 이벤트). 모두 `state/` 라 git 추적 안 함.

## Slack (봇 토큰 모드)
- `config.local.md` 에 `SLACK_BOT_TOKEN`(xoxb) 과 `SLACK_CHANNEL`(상대 user id)을 둔다(git 추적 안 함; 템플릿 `config.example.md`). 둘 중 하나라도 없으면 Slack 연동을 건너뛴다.
- **수신**: supervisor 가 60초마다 `scripts/slack.py poll` 로 봇↔사용자 DM 의 새 사람 메시지를 inbox 로 옮기고(LLM 불필요), 새 메시지가 있으면 마스터를 즉시 깨운다. cursor=`state/slack.cursor`(ts 초과분만, exclusive).
- **발신**: `scripts/slack.py post "<텍스트>"`. 봇이 "tokendance" 정체성으로 보내므로 별도 마커 불필요. 폴링은 사람(user) 메시지만 집어 봇 자기 출력은 자동 무시.
