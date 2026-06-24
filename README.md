# tokendance

상시 호스트 위에서 코딩 일감을 자율 관리하는 **마스터 에이전트 하네스**.
30분마다 깨어나 일감을 격리된 워커 프로세스에 시키고, 결과물을 직접 리뷰하고,
진행/판단 필요 지점을 Slack DM으로 보고하며, 당신의 피드백을 워커에 다시 주입한다.

- 설계: [docs/superpowers/specs/2026-06-24-tokendance-master-agent-design.md](docs/superpowers/specs/2026-06-24-tokendance-master-agent-design.md)
- 구현 플랜: [docs/superpowers/plans/2026-06-24-tokendance-master-agent-mvp.md](docs/superpowers/plans/2026-06-24-tokendance-master-agent-mvp.md)
- 기반 검증: [docs/superpowers/spikes/2026-06-24-foundation-findings.md](docs/superpowers/spikes/2026-06-24-foundation-findings.md)

## 아키텍처 (한 단락)

`scripts/supervisor.py`(nohup 상주 루프)가 30분마다: ① heartbeat 신선도로 죽은 워커를
needs_human 으로 정리하고 ② headless `claude` 마스터를 1회 기동한다. 마스터는 Slack DM과
inbox 큐를 읽어 **질문엔 직접 답하고, 사소한 일은 직접 처리하고, 본격 코딩 일감은**
`scripts/launch-worker.sh` 로 워커(독립 OS 프로세스, `setsid` 로 detach)를 띄운다 — 기다리지
않고 잠든다. 워커는 깨끗한 컨텍스트로 작업하며 progress/heartbeat/steer 파일로만 소통한다.
다음 깨어남에 마스터가 결과물을 직접 리뷰하고(합격→done, 반려→재투입) 리포트를 DM에 푸시한다.
모든 상태는 레포 안 파일이 단일 진실원이며 git 으로 추적된다.

## 사용법

```bash
# 1) 인스턴스 설정: 템플릿 복사 후 Slack 채널 등 채우기 (config.local.md 는 git 추적 안 됨)
cp config.example.md config.local.md   # 그리고 SLACK_CHANNEL 값을 채운다 (비우면 Slack 생략)

# 2) claude 바이너리 경로 주입 (버전 디렉토리는 바뀔 수 있으니 glob 로 최신 선택)
export TOKENDANCE_CLAUDE="$(ls -dt /root/.vscode-server/extensions/anthropic.claude-code-*/resources/native-binary/claude | head -1)"

scripts/start.sh     # supervisor 데몬 기동 (30분 주기)
scripts/stop.sh      # 정지
python3 scripts/supervisor.py --once   # 수동으로 한 사이클 즉시 실행
```

### 일감/피드백 주는 법
- **Slack self-DM** (권장): 본인과의 DM(`Messages to yourself`)에 한 줄 던지면 마스터가
  읽어 처리하고 리포트를 거기로 올린다. 마스터 메시지는 맨 앞에 `🤖 tokendance` 마커가 붙는다.
- **파일**: `python3 scripts/inbox.py add "할 일 한 줄" --slug mytask` (또는
  `state/inbox/pending/` 에 `.md` 파일을 직접 떨궈도 됨).
- **터미널**: 위 명령을 직접 실행.

### 상태 보는 법
```bash
python3 scripts/tasks.py list                 # 모든 일감 + 상태
python3 scripts/status.py get <task-id>       # 한 일감의 status.json
cat state/tasks/<task-id>/progress.md         # 워커의 현재 진행 (peek)
cat state/reports/<날짜>.md                    # 일자 리포트
```

### 진행 중 워커에 의견 주입 (steer)
`state/tasks/<task-id>/steer.md` 에 timestamped 블록을 append 하면 워커가 다음 체크포인트에서 반영.

## 상태 디렉토리

```
state/inbox/{pending,processed}/   사람/Slack 입력 큐
state/tasks/<id>/                  task.md, status.json, progress.md, steer.md, log.md, review.md
state/reports/<날짜>.md             일자 리포트
state/slack.cursor                 Slack 중복 방지 포인터 (gitignored)
library/{index.md,playbooks/,repos/}   지식 라이브러리 (점진 탐색)
prompts/{master.md,worker.md}      마스터/워커 시스템 프롬프트
scripts/{supervisor,status,tasks,inbox}.py, launch-worker.sh, prepare-worktree.sh, start/stop.sh
```

## 불변 규칙
- status.json 변경은 `scripts/status.py` 로만 (flock + atomic).
- 워커 기동은 `scripts/launch-worker.sh` 로만.
- 타겟 레포 변경은 브랜치/PR만. main 직접 push 금지.
- 자동화 도구는 Python 표준 라이브러리만 (외부 패키지/jq 불사용).
- root 실행 시 claude 기동에 `IS_SANDBOX=1` 필요.

## 테스트
```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```
