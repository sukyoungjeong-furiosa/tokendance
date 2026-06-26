# tokendance 인스턴스 설정 (예시)

이 파일을 `config.local.md` 로 복사해서 값을 채우세요.
`config.local.md` 는 git 에 올라가지 않습니다(인스턴스/보안 값).

```
# Slack self-DM 또는 채널 ID.
#  - self-DM 으로 쓰려면 본인 Slack user id (예: U0XXXXXXX) 를 넣으세요.
#  - 전용 채널이면 채널 id (예: C0XXXXXXX).
#  - 비워두면 마스터가 Slack pull/push 를 건너뜁니다(파일 리포트만).
SLACK_CHANNEL=

# 동시 실행 워커 상한. 워커는 prepare-worktree.sh 가 만든 격리 git worktree 에서
# 동작하므로 같은 레포라도 소스 충돌 없이 1 이상으로 올릴 수 있다.
# (공유 빌드 캐시는 symlink 이므로 빌드 동시성은 레포 특성에 맞게 판단.)
MAX_WORKERS=1

# supervisor 깨어남 주기(초). 미설정이면 1800(30분).
# 값을 바꾸면 stop.sh/start.sh 로 재시작해야 적용됨(데몬이 시작 시 1회 로드).
POLL_INTERVAL=21600

# 마스터 세션을 이만큼 이어간(--resume) 뒤 새 세션으로 리셋(맥락은 롤링노트가 인계).
# prompts/master/* 가 바뀌면 cycles 와 무관하게 즉시 리셋(편집 자동 반영).
MASTER_SESSION_MAX_CYCLES=20

# 사서(librarian) 패스를 도는 KST 시각(새벽). 미설정이면 3(새벽 3시).
# 그 시각 + idle(처리할 일감 없음)일 때 하루 1회 지식 라이브러리를 자가 큐레이션한다.
LIBRARIAN_HOUR_KST=3

# 마스터 아침 루틴(완료 worktree GC + 일일 다이제스트)을 도는 KST 시각. 미설정이면 7(아침 7시).
# 그 시각에 하루 1회 실행한다(idle 무관 — 들고있는/확인필요 작업을 Slack 으로 보고하므로).
MASTER_MORNING_HOUR_KST=7
```

## 그 외 환경 (셸 환경변수로 주입)
- `TOKENDANCE_CLAUDE` — claude 네이티브 바이너리 경로. 예:
  `export TOKENDANCE_CLAUDE="$(ls -dt /root/.vscode-server/extensions/anthropic.claude-code-*/resources/native-binary/claude | head -1)"`
- Slack 인증은 Claude Code 자격증명(`~/.claude/.credentials.json`)을 그대로 사용하므로 레포에 토큰을 두지 않습니다.
