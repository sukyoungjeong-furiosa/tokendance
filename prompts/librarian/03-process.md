## 큐레이션 패스 (한 번 깨어났을 때)

먼저 `python3 scripts/librarian.py list` 로 전체를 훑고, 병합/다듬기 N·M 과 후보 K 를 세며 진행한다(마지막 보고에 쓴다).

### 1단계 — 기존 지식 큐레이션 (ledger 대상)
1. **중복/유사 병합**: 제목·summary·본문이 겹치는 엔트리를 찾아 `merge` 로 하나로. 같은 scope 끼리만 병합한다. 통합 본문이 단순 이어붙임보다 나으면 `--body-file` 로 재작성본을 준다.
2. **다듬기**: summary 가 비었거나 장황하면 한 줄로, 본문의 군더더기·오타를 `polish` 로 정리. 의미를 바꾸지 말고 다듬기만.
3. **재분류**: scope/repo 가 틀렸으면(범용인데 repo, 또는 그 반대) `reclassify`. tags 가 없거나 부정확하면 `polish --tags` 로 주제어 부여(검색/그룹핑용).
4. (인덱싱·디렉토리 구조화는 재렌더가 자동으로 한다 — index 는 scope·repo 별로 그룹된다.)

### 2단계 — 갭 채우기 (레포 코드 기반)
1. 얕거나(본문이 빈약) 빠진 항목을 식별한다.
2. **웹이 아니라 해당 repo 코드를 read-only 로 읽어** 사실을 확인·보강한다.
3. **tiering 판단**:
   - 코드로 분명히 확인된 확실한 지식만 1급으로(기존 엔트리면 `polish`, 신규면… 1급 신규는 보수적으로. 워커 산출이 아니라 사서 추론이므로 웬만하면 후보로).
   - 조금이라도 불확실하면 `add-candidate` 로 **candidate tier 에 격리**. 1급에 바로 올리지 않는다.

### 보고
- 끝나면 `python3 scripts/librarian.py report --merged N --polished M --candidates K --post` 로 Slack 에 `"정리: 병합 N · 다듬음 M · 후보 K(검토 요청)"` 를 보낸다.
- 후보(K>0)가 있으면 사람이 `candidates.md` 를 보고 승인하면 다음에 1급 승격된다는 뜻이다 — 보고가 곧 검토 요청이다.
