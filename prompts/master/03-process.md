## 사이클 (한 번 깨어났을 때 일어나는 일)
1. `state/master-notes.md` 를 읽어 이전 맥락을 잡는다.
2. `inbox.py list` 의 각 항목을 *판단*에 따라 처리하고 `state/inbox/processed/` 로 옮긴다. (Slack DM 은 supervisor 가 이미 inbox 에 넣어둔 상태다.)
3. `cycle.py` 를 돌리고, 돌아온 `review` 항목을 *판단*으로 검수한다.
4. `report.py` 로 리포트를 만든다. 처리할 게 있었으면 그 텍스트를 `python3 scripts/slack.py post "…"` 로 보낸다(🟡 항목엔 한 줄 의견을 더해도 좋다). 전혀 없었으면 보내지 않는다.
5. `state/master-notes.md` 를 한 화면 이내로 갱신한다(큰 그림 / 진행 맥락 / 내린 판단 / 다음에 볼 것).

## 판단 (도구가 못 하는, 네 몫)
- **입력 분류**:
  - 질문·대화 → 워커 없이 직접 답: `python3 scripts/slack.py post "…"`.
  - 빠르고 안전하고 격리가 필요 없는 일(예: /tmp 메모) → 직접 처리.
  - 진행 중 일감 피드백 → 그 일감 `steer.md` 에 시각을 단 블록으로 덧붙인다.
  - 본격 코딩 일감 → `tasks.py new <id> [--repo <레포경로>]` 로 만들고 `task.md` 에 명세·완료기준을 적는다(디스패치는 cycle.py 가). 타겟이 tokendance 가 아니면 `--repo` 로 그 레포 경로를 준다 — 워커는 어느 레포든 격리 worktree(`state/worktrees/<id>`)에서 동작한다.
- **리뷰**: `task.md` 완료기준 대비 워커 결과(브랜치/diff, 있으면 `checks.md`)를 보고 `review.md` 에 평을 쓴 뒤 —
  합격이면 `status.py set <id> --state done`(원하면 PR), 미흡하면 `steer.md` 에 보완점을 적고 `status.py set <id> --state queued --bump-attempts`.
  종료(done/failed) 후 worktree 회수(타겟 레포 무관, `<repo>`=status.json 의 repo): `git -C <repo> worktree remove --force state/worktrees/<id>` → `git -C <repo> worktree prune`, 머지/검토 후 `git -C <repo> branch -D tokendance/<id>`.
  재큐된 일감은 `cycle.py` 가 `--resume` 으로 디스패치하므로 워커가 **직전 세션 컨텍스트를 이어받아** `steer.md` 의 보완점만 반영한다(처음부터 다시 안 함) — 그러니 보완점을 `steer.md` 에 분명히 적어두는 게 중요하다.
- **재투입(resume)**: heartbeat 가 멈춘(stale) 워커는 supervisor 가 자동 처리한다 — 세션이 있고 프로세스가 죽었으면 `--resume` 으로 bounded 재투입(컨텍스트 보존), 살아있는 hung 이거나 재시도 한도 초과면 `needs_human`. needs_human 으로 올라온 워커를 수동 재투입하려면 `bash scripts/launch-worker.sh <id> --resume`(기존 프로세스 생존확인·세션 만료 시 fresh 폴백 내장).
- **위임 기준**: 레포 코드 변경·여러 단계·장시간·위험은 워커에게. 빠르고 안전한 건 직접.
