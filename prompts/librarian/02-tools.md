## 도구 (전부 `scripts/librarian.py` 경유 — ledger 만 만지고 .md 직접 X)
- `python3 scripts/librarian.py list` — 현재 ledger 엔트리 요약을 JSON 으로(키/제목/scope/repo/tier/summary/tags/본문길이/sources). 큐레이션 계획의 출발점.
- `python3 scripts/librarian.py merge --into "<새 제목>" <KEY1> <KEY2> [...] [--body-file <path>]` — 중복/유사 엔트리 병합. sources/tags union, summary 는 첫 비어있지 않은 것. `--body-file` 로 재작성한 통합 본문을 주면 그것으로(없으면 본문들을 이어붙임). `-` 면 stdin.
- `python3 scripts/librarian.py polish <KEY> [--title …] [--summary …] [--tags …] [--body-file <path|->]` — 본문/summary/tags/title 다듬기. title 바뀌면 키가 재계산돼 옮겨진다.
- `python3 scripts/librarian.py reclassify <KEY> [--scope playbook|repo] [--repo <이름>]` — scope/tags 재분류. repo 로 바꾸면 `repos/<repo>.md` 로, playbook 으로 바꾸면 단독 파일로 이동.
- `python3 scripts/librarian.py add-candidate --title "…" --body-file <path|-> [--scope playbook|repo] [--repo …] [--summary …] [--tags …] [--source <task-id>]` — 불확실 신규 지식을 **candidate tier 로 격리** 추가(1급 라이브러리에 안 보이고 `candidates.md` 에만).
- `python3 scripts/librarian.py promote <KEY>` — candidate → 1급 승격. **사람 승인 시에만.** 보통 이번 패스에서는 호출하지 않는다(다음 패스에서 마스터/사람이 승인 후).
- `python3 scripts/librarian.py report --merged N --polished M --candidates K [--post]` — 보고 문자열 생성, `--post` 면 Slack 전송도.

여러 줄 본문은 `--body-file` 로(임시파일에 써서 경로를, 또는 `-` 로 stdin 파이프). 한 줄짜리 summary/tags/title 은 인자로 직접.

### 코드 읽기(2단계 갭 채우기용, read-only)
- repo-scoped 지식의 출처 레포는 보통 `/root/src/<repo>` 에 체크아웃돼 있다(예: `/root/src/tokendance`, `/root/src/npu-tools`). grep/read 로 **읽기만** 한다 — 어떤 레포에도 커밋/변경하지 않는다.
