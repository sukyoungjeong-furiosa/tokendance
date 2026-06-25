# tokendance — 마스터 에이전트 하네스 설계

날짜: 2026-06-24
상태: 설계 승인 대기

## 1. 한 줄 요약

상시 켜진 호스트 위에서 주기적으로 깨어나, 흩어진 코딩 일감들을 격리된 워커 프로세스에 시키고, 그 결과물을 직접 리뷰하며, 진행 상황과 판단 필요 지점을 사람에게 보고하고, 사람의 중간 피드백을 워커에 다시 주입하는 자율 매니저("비서/행동대장/테크리더") 에이전트.

## 2. 목표 / 비목표

### 목표
- **자율 구동**: 사람 입력이 없어도 "완전 종료" 전까지 계속 굴러간다.
- **주기 + 이벤트**: 30분마다 깨어나 상태를 점검하고, 완료/막힘에 반응한다.
- **격리**: 일감 간, 마스터↔워커 간 컨텍스트를 공유하지 않는다. 역할 분리로 효율을 얻는다.
- **마스터의 직접 리뷰**: 마스터가 워커 결과물을 검수하고 합격/반려를 판단한다.
- **진행 중 관찰 + 조향**: 끝나기 전에도 워커가 뭘 하는지 보고, 중간 의견을 주입할 수 있다.
- **진행+의심 보고**: "다 했어요"가 아니라 "지금 이렇게 되고 있고, 이 부분 애매해서 일단 이렇게 했는데 맞나요?"를 보고한다.
- **지식 라이브러리화**: 작업에서 얻은 노하우/레포 지식을 점진 탐색 가능한 형태로 축적한다. (optional)

### 비목표 (현 단계)
- 마스터의 main 브랜치 직접 push. (워커는 PR/브랜치로만)
- 완전한 멀티 레포 추상화 — 1차는 단순하게, 정교화는 dogfood 백로그.
- 정교한 지식 라이브러리 — 1차는 뼈대만, 본격 구현은 dogfood 백로그.

## 3. 핵심 설계 결정과 근거

### 3.1 왜 "상시 호스트 데몬"인가 (모델 2)
하네스의 in-session 에이전트(서브에이전트, 워크플로우)는 **띄운 세션의 수명에 묶여** 세션이 끝나면 같이 죽는다. 클라우드 cron은 발화마다 임시 컨테이너가 떴다 파기되므로, 그 안에서 띄운 워커도 발화가 끝나면 사라진다. 따라서 "마스터가 시켜놓고 자러 가도 워커가 계속 사는" fire-and-forget을 하네스 기본 기능만으로는 만들 수 없다.

**해결**: 워커를 하네스의 서브에이전트가 아니라, 코드(`claude` 네이티브 바이너리)를 직접 실행해 만든 **독립 OS 프로세스**로 띄운다. `setsid`/`nohup`으로 부모에서 떼어내면, 띄운 마스터 프로세스가 죽어도 워커는 호스트 위에서 계속 산다. 이로써 하네스 세션 수명 한계를 완전히 우회한다.

이 모델은 상시 켜진 호스트를 전제로 한다. 대상 호스트는 업타임 6주+의 상시 서버이며, 네이티브 `claude` 바이너리·API 키·`setsid`/`nohup`이 모두 확인됨 (부록 A).

### 3.2 통신은 전부 파일 (단일 진실원)
에이전트 핸들/세션 ID는 세션·프로세스 경계를 넘지 못한다. 따라서 마스터↔워커, 깨어남↔깨어남, 사람↔시스템의 모든 소통은 **tokendance 레포 안의 파일**을 통한다. 연속성은 "살아있는 프로세스"가 아니라 "상태 파일"에 산다. 모든 상태가 git에 남아 추적/롤백 가능하다.

### 3.3 peek/steer는 "협조적 워커 + 파일 프로토콜"로
하네스는 돌고 있는 에이전트에 메시지를 직접 주입하지 못한다(`SendMessage`는 끝났거나 멈춘 에이전트 재개만 가능). 대신 워커를 우리가 직접 설계하므로, 워커가 체크포인트마다 **progress 파일을 쓰고(=peek 대상) steer 파일을 읽도록(=steer 주입)** 만들어 동등한 효과를 낸다.

## 4. 아키텍처

```
host (상시 호스트)
│
└─ supervisor.py  (nohup으로 띄운 유일한 상주 프로세스)
      │  30분마다:
      ├─ 헬스체크: 고아/죽은 워커 프로세스 감지, status 정합성 점검
      └─ 마스터 1회 기동 (동기 실행, 가볍게 끝남)
           master = claude -p --append-system-prompt prompts/master.md
                           --dangerously-skip-permissions
           │
           ├─ 1. inbox.md 처리 → state/tasks/<id>/ 로 정리, inbox 비움
           ├─ 2. 모든 status.json 스캔 → 분기 처리 (§6.2)
           ├─ 3. review 대기 일감 직접 리뷰 → done / 반려
           ├─ 4. 헤매는 워커에 steer.md 기록
           ├─ 5. queued 일감을 상한(4) 내에서 `launch-worker.sh <task-id>` 호출로 디스패치 (안 기다림)
           ├─ 6. 지식 수확물 library/ 반영
           ├─ 7. reports/ 작성 + Slack 요약 푸시
           └─ 종료
                │
                └─ launch-worker.sh: worktree 셋업 → setsid claude -p
                                          --append-system-prompt prompts/worker.md
                                          --dangerously-skip-permissions  &
                                          (마스터는 shell을 자유롭게 치지 않고 이 스크립트만 호출)
                      독립 OS 프로세스, 자기 수명대로 코딩:
                      ├─ 타겟 레포 worktree 셋업 (prepare-worktree.sh)
                      ├─ library/index.md 에서 필요한 지식만 픽업
                      ├─ 체크포인트마다: progress.md 쓰기 + steer.md 읽기 + heartbeat 갱신
                      └─ 종료 시: 결과물 + status=review (또는 blocked/failed)
```

## 5. 디렉토리 레이아웃

tokendance 레포가 컨트롤 플레인(본부)이다. 실제 코드는 워커가 각 타겟 레포를 체크아웃해서 작업한다.

```
tokendance/
  CLAUDE.md                       # 마스터/워커가 공유하는 운영 규칙
  prompts/
    master.md                     # 마스터 시스템 프롬프트(정체성/절차)
    worker.md                     # 워커 시스템 프롬프트(정체성/체크포인트 프로토콜)
  scripts/
    supervisor.py                 # 상주 타이머 + 마스터 기동 + 헬스체크
    launch-worker.sh              # worktree 셋업 + setsid claude 워커 기동 (마스터의 유일한 워커 기동 통로)
    status.py                     # status.json 의 유일한 변경 통로 (flock + atomic write, §6.3)
    prepare-worktree.sh           # 공통 artifact 셋업 (1차는 stub, dogfood로 정교화)
    start.sh / stop.sh            # supervisor 기동/정지
  state/
    inbox/
      pending/<ts>-<slug>.md      # 사람/Slack/remote 입력 한 건 = 파일 한 개 (큐)
      processed/<ts>-<slug>.md    # 마스터가 처리 후 이동 (감사 추적)
    tasks/<task-id>/
      task.md                     # 일감 스펙, 출처, 완료 기준
      status.json                 # 상태 머신 (§6.1). status.py 로만 변경
      progress.md                 # 워커의 현재 진행 서술 (peek 대상, 워커 소유)
      steer.md                    # 마스터/사람의 중간 지시 (append-only 누적 로그, §8)
      steer.cursor                # 워커가 마지막으로 소비한 steer 지점 (워커 소유)
      log.md                      # 진행/결정 로그 (지식 C, 워커 소유 append)
      review.md                   # 마스터의 리뷰 노트 (마스터 소유)
    reports/YYYY-MM-DD.md         # 일자별 리포트
    workers/<task-id>.log         # 워커 프로세스 stdout/stderr
  library/
    index.md                      # 목차/지도 (점진 탐색 진입점)
    playbooks/                    # 재사용 노하우 (지식 A)
    repos/<repo>.md               # 레포별 지식 베이스 (지식 B)
  docs/superpowers/specs/         # 이 설계 문서 등
```

## 6. 상태 모델

### 6.1 status.json 스키마
```json
{
  "id": "2026-06-24-fix-login",
  "title": "로그인 버그 수정",
  "repo": "git@.../foo.git",
  "state": "queued | running | needs_human | blocked | review | done | failed",
  "version": 7,
  "worker_pid": 12345,
  "worker_session_id": "abc123",
  "branch": "tokendance/fix-login",
  "heartbeat": "2026-06-24T10:05:00Z",
  "created": "2026-06-24T09:00:00Z",
  "updated": "2026-06-24T10:05:00Z",
  "attempts": 1,
  "failure_reason": null
}
```
- `state` 의미:
  - `queued` — 디스패치 대기
  - `running` — 워커 프로세스가 작업 중
  - `needs_human` — **사람의 판단/결정 대기** (기술적으론 안 막힘). 리포트 🟡.
  - `blocked` — **기술적 막힘** (빌드 실패, 권한, 외부 의존성 등). 리포트 🔴.
  - `review` — 워커가 결과물을 마치고 마스터 검수 대기
  - `done` — 검수 합격, 종료
  - `failed` — 종료된 실패. `failure_reason` **필수**(비어 있으면 안 됨).
- `version` — 단조 증가 정수. 모든 변경 시 +1. stale write 감지 및 낙관적 동시성 제어(§6.3)에 사용.
- `heartbeat` — 워커가 체크포인트마다 갱신. 마스터는 신선도로 생사를 판단한다.
- `worker_pid` — 마스터/supervisor가 실제 프로세스 생존을 교차 확인.
- `worker_session_id` — 반려된 일감을 `--resume`해 컨텍스트를 이어 재투입.

### 6.2 마스터의 status 분기
- `running` & heartbeat 신선 & pid 살아있음 → **냅둠**. progress.md 훑어 헤매면 steer.md에 교정 추가.
- `running` & (heartbeat 멈춤 또는 pid 죽음) → **죽은 워커**. log/progress 보고 재투입(`--resume`) 또는 `needs_human`으로 에스컬레이션.
- `review` → **마스터 직접 리뷰**(§7). done 또는 반려.
- `needs_human` → 리포트 🟡에 "판단 필요" 항목으로 올림. 사람 응답이 steer로 들어오면 워커 재개.
- `blocked` → 막힌 이유 + 마스터 제안을 리포트 🔴에 올림.
- `queued` & 동시 실행 < 4 → **워커 디스패치** (`launch-worker.sh <task-id>` 호출).
- `done` / `failed` → 아카이브/리포트.

### 6.3 동시성과 파일 소유권
워커·마스터·사람·Slack 어댑터가 동시에 파일을 만질 수 있으므로, 상태 무결성을 다음으로 보장한다:

- **status.json 은 `scripts/status.py`로만 변경한다** (직접 편집·jq 금지). 헬퍼가:
  - `flock`으로 task 단위 락(`status.json.lock`)을 잡고 read-modify-write를 직렬화 → *lost update* 방지.
  - 임시 파일에 쓴 뒤 `os.replace`(원자적 rename)로 교체 → torn read 방지.
  - 변경마다 `version`+1, `updated` 갱신. 호출자가 기대 version을 넘기면 불일치 시 거부(낙관적 잠금) — 선택적.
  - 인터페이스 예: `status.py set <task-id> state running --pid 123`, `status.py heartbeat <task-id>`, `status.py get <task-id>`.
- **파일별 단일 소유자 원칙** (경합 최소화):
  - `progress.md`, `log.md`, `steer.cursor` → **워커**가 쓴다. (마스터·사람은 읽기만)
  - `review.md`, `reports/` → **마스터**가 쓴다.
  - `steer.md` → 마스터·사람이 **append만** 한다 (덮어쓰기 금지, §8). 워커는 읽기만.
  - `status.json` → 워커·마스터 둘 다 쓰지만 **반드시 status.py 경유**.
  - `inbox/pending/` → 사람·Slack·remote가 파일을 **추가**, 마스터가 `processed/`로 **이동**.

## 7. 리뷰 루프

1. 워커가 `state=review`로 마치고 결과물(브랜치/diff/산출물 경로)을 남긴다.
2. 마스터가 `task.md`의 완료 기준 대비 결과물을 검수하고 `review.md`에 평을 남긴다.
3. 합격 → `state=done`, 리포트 ✅. 필요 시 PR 생성.
4. 반려 → `steer.md`에 교정 지시 + `state=queued`(또는 `--resume`로 같은 워커 컨텍스트 재투입). `attempts++`.

## 8. peek / steer 프로토콜

`steer.md`는 **append-only 누적 로그**다. 각 지시는 timestamped 블록으로 추가된다 (덮어쓰기 금지 → 마스터·사람이 동시에 써도 손실 없음):
```
## 2026-06-24T10:05:00Z (master)
로그인 토큰 만료를 24h로 가정하지 말고 설정값을 읽어와.
```

### 워커 체크포인트(각 의미 있는 단계 경계)에서:
1. `progress.md`에 기록: **현재 단계 / 지금 하는 일 / 부딪힌 애매함 / 일단 한 가정 / 자체 점검("이 방향 맞나")**.
2. `steer.md`에서 `steer.cursor`가 가리키는 지점 **이후의 새 지시만** 읽어 반영하고, 반영 사실을 `log.md`에 남긴 뒤 `steer.cursor`를 마지막 소비 지점(파일 바이트 offset 또는 마지막 블록 timestamp)으로 갱신한다.
3. `status.py heartbeat <task-id>`로 heartbeat 갱신.
4. 사람 판단이 꼭 필요하면 `status.py set <id> state needs_human`으로 전환하고 멈춤(또는 다음 체크포인트까지 진행 가능한 부분만 진행).
5. 계속 진행.

### 마스터/사람의 주입:
- 마스터는 헤매는 워커의 `steer.md`에 timestamped 블록을 **append**.
- 사람은 inbox(§9) 또는 직접 `steer.md`에 append → 다음 체크포인트에 반영.

## 9. 입력 채널 → inbox 수렴

터미널 직접 편집 / Slack / remote-control 에이전트 — 모두 입력 한 건을 `state/inbox/pending/<ts>-<slug>.md` 파일 한 개로 떨군다 (단일 파일 동시 편집으로 인한 손실 방지를 위한 큐 방식). 사람은 `echo "..." > state/inbox/pending/now.md` 한 줄로도 투입 가능. 마스터는 깨어날 때 `pending/`의 파일들을 처리해 해당 일감의 task/steer로 라우팅한 뒤 `processed/`로 이동한다(감사 추적 보존). 마스터는 입력 출처를 몰라도 된다. Slack 어댑터는 깨어남마다 지정 채널/DM을 읽어 새 지시를 `pending/` 파일로 떨군다.

## 10. 리포트 (진행+의심 중심)

`reports/YYYY-MM-DD.md`에 누적, Slack에 요약 푸시:
- 🟢 **순항** (`running`): (일감, 한 줄 현황)
- 🟡 **판단 필요** (`needs_human`): "X가 애매해서 일단 Y로 진행 중 — 맞나요?" → 답이 steer로 흘러감
- 🔴 **막힘** (`blocked`): 기술적 이유 + 마스터 제안
- ✅ **리뷰 완료** (`done`): 검수 결과물 + 한 줄 평
- ⚫ **실패** (`failed`): `failure_reason` 요약

## 11. Slack 연동 (1차 범위 포함)

사용자 계정의 Slack MCP를 통해:
- **입력 어댑터**: 지정 채널/DM의 새 메시지를 깨어남마다 읽어 inbox로 정리.
- **출력**: 리포트(§10) 요약을 채널에 푸시. 🟡/🔴 항목은 사람 응답을 유도.
- 사람의 Slack 답글 → 다음 깨어남에 inbox로 수집 → 해당 일감 steer로 라우팅.

## 12. 동시성 / 안전

- 동시 워커 상한 **4**. queued는 슬롯이 빌 때까지 대기.
- supervisor 주기 **30분**.
- `--dangerously-skip-permissions`는 자율성에 필수지만 위험. 완화책:
  - 워커는 항상 worktree에서 격리 작업.
  - 타겟 레포 변경은 **브랜치/PR로만**. main 직접 push 금지.
  - 모든 상태가 git에 남아 추적/롤백 가능.
  - supervisor 헬스체크가 폭주/고아 프로세스를 감지.
- **좁은 인터페이스 원칙**: 마스터는 *판단*만 하고, 부수효과는 정해진 스크립트로만 위임한다.
  - 워커 프로세스 기동/관리 → `launch-worker.sh` 만. (마스터가 직접 `setsid`/`kill` 등 자유 shell 금지)
  - status.json 변경 → `status.py` 만.
  - 이로써 자율 권한 하에서도 마스터의 행동 표면이 좁아져 사고 반경이 준다.

## 13. MVP 범위 vs Dogfood 백로그

### MVP (손으로 구축)
- state/ 디렉토리 구조 + status.json 상태 머신(7개 상태)
- **status.py** (flock + atomic write, status.json 변경 유일 통로 — §6.3)
- **inbox 큐** (pending/ → processed/) + 마스터 라우팅 로직
- supervisor.py (30분 타이머, 마스터 기동, 헬스체크)
- launch-worker.sh (worktree 셋업 + setsid 워커 기동, pid/로그 캡처)
- prompts/master.md, prompts/worker.md (peek/steer append-only 프로토콜 + steer.cursor 포함)
- 리뷰 루프, 진행+의심 리포트
- Slack 입력 어댑터 + 출력 푸시
- prepare-worktree.sh: 동작하는 최소 stub
- library/: 뼈대(index.md + 빈 디렉토리)만

### Dogfood 백로그 (tokendance가 스스로 수행할 첫 일감들 — inbox에 시드)
1. `prepare-worktree.sh` 정교화 — 실제 타겟 레포의 공통 artifact 의존성 처리(심볼릭링크/복사 전략).
2. 지식 라이브러리 본격화 — playbook/레포지식 수확·갱신 자동화, index 점진 탐색 다듬기.
3. remote-control 에이전트 입력 경로 정식화.
4. 멀티 레포 핸들링 추상화.
5. 리뷰 품질 강화 — 자동 테스트 실행/검증을 리뷰 루프에 결합.
6. 워커 재개(`--resume`) 기반 반려 재투입 신뢰성 강화.
7. supervisor 자기 회복(크래시 후 재기동) 및 관측성.

## 14. 미해결 / 플랜 1단계 검증 항목

- **headless 스모크 테스트**: `claude -p ... --dangerously-skip-permissions`로 자율 1회 실행이 인증/도구 포함 정상 동작하는지 실제 확인.
- **detached 생존 확인**: `setsid claude -p &`로 띄운 워커가 부모 종료 후에도 사는지 확인.
- **워커 worktree + 자율 권한**의 실제 안전성 점검.
- Slack MCP가 headless(비대화형) 실행 컨텍스트에서도 접근 가능한지 확인 (대화형 인증 의존 가능성).

## 부록 A — 검증된 호스트 사실 (2026-06-24)
- 상시 호스트, 업타임 6주+ (상시형).
- 네이티브 `claude` 바이너리 존재: `~/.vscode-server/extensions/anthropic.claude-code-2.1.187-linux-x64/resources/native-binary/claude` (node 불필요). 지원 플래그: `-p/--print`, `--append-system-prompt`, `--agents`, `--dangerously-skip-permissions`, `--resume`/`--continue`, `--output-format stream-json`, `--bg`, `--model`, `--effort`.
- `nohup`, `setsid` 존재. `ANTHROPIC_API_KEY` 세팅됨 + `~/.claude/.credentials.json` 존재.
- 부재: PATH상의 `claude`/`node`, `crontab`, `systemctl` → 주기성은 nohup supervisor 루프가 담당.

## 부록 B — 검증된 하네스 사실
- 서브에이전트/워크플로우는 띄운 세션 수명에 묶임. 세션 종료 시 함께 종료.
- `SendMessage`는 끝났거나 멈춘 에이전트의 재개만 가능 (돌고 있는 에이전트 직접 주입 불가).
- 에이전트 ID/핸들은 세션 경계를 넘지 못함.
- 클라우드 cron 발화는 매번 새 임시 세션; 발화 간 통신은 파일로만.
- 따라서 fire-and-forget·장수 워커는 OS 프로세스(코드로 띄운 `claude`)로 구현해야 함.
