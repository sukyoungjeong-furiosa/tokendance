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
  - 본격 코딩 일감 → `tasks.py new` 로 만들고 `task.md` 에 명세·완료기준을 적는다(디스패치는 cycle.py 가).
- **리뷰**: `task.md` 완료기준 대비 워커 결과(브랜치/diff, 있으면 `checks.md`)를 보고 `review.md` 에 평을 쓴 뒤 —
  합격이면 `status.py set <id> --state done`(원하면 PR), 미흡하면 `steer.md` 에 보완점을 적고 `status.py set <id> --state queued --bump-attempts`.
- **위임 기준**: 레포 코드 변경·여러 단계·장시간·위험은 워커에게. 빠르고 안전한 건 직접.
