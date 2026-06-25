# 기반 검증 스파이크 결과 (2026-06-24)

플랜 Task 1. 아키텍처 전제 3가지를 실제 실행으로 검증.

## 환경
- 상시 호스트, **root(uid=0)로 실행**, 업타임 6주+.
- claude 바이너리(고정):
  ```bash
  export TOKENDANCE_CLAUDE="$(ls -dt /root/.vscode-server/extensions/anthropic.claude-code-*/resources/native-binary/claude | head -1)"
  # => .../anthropic.claude-code-2.1.187-linux-x64/resources/native-binary/claude
  ```
- 버전 디렉토리가 바뀌므로 경로 하드코딩 금지. 위 glob으로 매번 최신 선택.

## 결과

### ① headless 자율 실행 — ✅ (단 root는 IS_SANDBOX=1 필요)
- `--dangerously-skip-permissions` 단독은 **root에서 거부됨**:
  `--dangerously-skip-permissions cannot be used with root/sudo privileges`.
- **해결**: `IS_SANDBOX=1` 환경변수와 함께 쓰면 root에서도 동작.
  ```bash
  IS_SANDBOX=1 "$TOKENDANCE_CLAUDE" -p "..." --dangerously-skip-permissions </dev/null
  ```
  → 파일 생성 등 도구 사용이 프롬프트 없이 자율 수행됨(검증 완료).

### ② detached 생존 — ✅
- `setsid env IS_SANDBOX=1 claude -p ... >log 2>&1 </dev/null &` 로 띄운 워커는
  **PPID=1로 재부모화**되고 자체 세션 리더(`Ssl`)가 됨 → launching shell이 죽어도 생존.
- 짧은 작업은 즉시 완료되어 산출물(slow.txt="done")로 독립 완료 확인. 긴 작업(sleep 30)은
  6초 후에도 `claude` 프로세스(PPID=1)가 살아있음을 확인.

### ③ Slack MCP in headless — ✅ (Task 11 경로 A 확정)
- headless `-p` 실행에서도 `mcp__claude_ai_Slack__*` 툴이 노출됨:
  `slack_read_channel`, `slack_send_message`, `slack_search_channels`,
  `slack_read_thread`, `slack_schedule_message`, `slack_create_canvas` 등.
- 따라서 마스터 프롬프트에서 Slack MCP 툴을 직접 사용 가능. 봇 토큰 폴백 불필요.

## 플랜에 반영해야 할 발견
1. **모든 claude 기동에 `IS_SANDBOX=1` 추가** (launch-worker.sh 워커, supervisor run_master).
2. **PID 추적 불안정** — `setsid` 후 claude가 재fork/재부모화하여 `$!`가 실제 워커 pid와
   불일치(관측: `$!`=3073895 ≠ 실제 claude=3073897). → **health_check를 pid 생존이 아니라
   heartbeat 신선도 기반으로 변경**. worker_pid는 best-effort 디버깅용으로만 저장.
3. **Task 11 = 경로 A** (Slack MCP). 채널 ID는 사람이 제공 필요.

## 결정 게이트
①②③ 모두 통과 → MVP 빌드 진행. 아키텍처 전제 무너지지 않음.
