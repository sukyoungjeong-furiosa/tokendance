# tokendance 인스턴스 설정 (예시)

이 파일을 `config.local.md` 로 복사해서 값을 채우세요.
`config.local.md` 는 git 에 올라가지 않습니다(인스턴스/보안 값).

```
# Slack self-DM 또는 채널 ID.
#  - self-DM 으로 쓰려면 본인 Slack user id (예: U0XXXXXXX) 를 넣으세요.
#  - 전용 채널이면 채널 id (예: C0XXXXXXX).
#  - 비워두면 마스터가 Slack pull/push 를 건너뜁니다(파일 리포트만).
SLACK_CHANNEL=

# 동시 실행 워커 상한. worktree 격리(prepare-worktree.sh)가 stub 인 동안에는
# 같은 레포에서 동시 작업이 충돌하므로 반드시 1. 격리 구현 후에만 올린다.
MAX_WORKERS=1
```

## 그 외 환경 (셸 환경변수로 주입)
- `TOKENDANCE_CLAUDE` — claude 네이티브 바이너리 경로. 예:
  `export TOKENDANCE_CLAUDE="$(ls -dt /root/.vscode-server/extensions/anthropic.claude-code-*/resources/native-binary/claude | head -1)"`
- Slack 인증은 Claude Code 자격증명(`~/.claude/.credentials.json`)을 그대로 사용하므로 레포에 토큰을 두지 않습니다.
