#!/usr/bin/env python3
"""사서(librarian): 주기적 지식 라이브러리 큐레이션 패스.

마스터 일감관리와 분리된 별도 역할. supervisor 가 하루 1회(KST 새벽 + idle) 트리거한다.

진실원은 ledger(`library/.harvest-ledger.json`)이고 harvest 가 거기서 `.md` 를 재렌더한다.
사서는 **렌더된 `.md` 를 직접 고치지 않고 ledger entries 를 편집**한 뒤 재렌더한다.
harvest 와 같은 flock(`library/.harvest-ledger.lock`)으로 직렬화한다(harvest_knowledge.ledger_lock).

이 모듈은 두 층으로 나뉜다:
  1. 순수 로직 — should_run 게이트, last-run 상태, ledger 변형(merge/polish/reclassify/
     candidate/promote), Slack 보고 형식. 부작용 없이 단위 테스트한다.
  2. CLI — 위 변형들을 flock 안에서 load→mutate→save→재렌더로 묶어 사서 에이전트가 호출한다.
     모든 편집이 락 직렬화 + 즉시 재렌더되므로 .md 를 직접 만질 일이 없다.

사서 에이전트(LLM)는 supervisor 가 run_librarian 으로 띄우며, prompts/librarian/* 지시대로
이 CLI 만 써서 ledger 를 큐레이션하고 slack.py 로 보고한다.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harvest_knowledge as HK
import prompt as PROMPT

KST = timezone(timedelta(hours=9))


# ── 트리거 게이트 (KST 시각 + idle + 하루 1회) ───────────────────────────────

def kst_date(now_utc):
    return now_utc.astimezone(KST).strftime("%Y-%m-%d")


def kst_hour(now_utc):
    return now_utc.astimezone(KST).hour


def should_run(now_utc, idle, last_run_date, target_hour):
    """사서를 지금 돌려야 하는가(순수 함수).

    - idle(처리할 새 일감 없음)일 때만.
    - KST 시각이 target_hour 일 때만(새벽 윈도).
    - 오늘(KST 날짜) 아직 안 돌았을 때만(하루 1회 중복 방지).
    """
    if not idle:
        return False
    if kst_hour(now_utc) != target_hour:
        return False
    return kst_date(now_utc) != (last_run_date or "")


# ── last-run 상태 (state/librarian.last) ─────────────────────────────────────

def _last_path(root):
    return os.path.join(root, "state", "librarian.last")


def read_last_run(root):
    try:
        with open(_last_path(root)) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def write_last_run(root, date_str):
    p = _last_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(date_str)


def mark_run(root, now_utc):
    """오늘(KST) 돌았다고 기록 — 실행 결정 시점에 호출해 하루 중복을 막는다."""
    write_last_run(root, kst_date(now_utc))


# ── ledger 엔트리 파생필드/키 재계산 ─────────────────────────────────────────

def _recompute(entry):
    """엔트리의 title/scope/repo 로부터 slug/dest/anchor 를 다시 계산하고 키를 반환한다."""
    slug = HK.slugify(entry["title"])
    entry["slug"] = slug
    scope = entry["scope"]
    repo = entry.get("repo") or ""
    if scope == "repo":
        entry["dest"] = os.path.join("repos", f"{HK.slugify(repo)}.md")
        entry["anchor"] = HK.anchor(entry["title"])
    else:
        entry["dest"] = os.path.join("playbooks", f"{slug}.md")
        entry["anchor"] = None
    return _key_for(entry)


def _key_for(entry):
    """엔트리의 정규 ledger 키. candidate tier 는 1급과 충돌하지 않게 'candidate:' 접두."""
    base = HK._entry_key(entry["scope"], entry.get("repo") or "", entry["slug"])
    if HK.is_candidate(entry):
        return "candidate:" + base
    return base


def _union_tags(*tag_strs):
    """콤마구분 태그들을 순서보존 + 중복제거로 합친다."""
    seen, out = set(), []
    for s in tag_strs:
        for t in (s or "").split(","):
            t = t.strip()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    return ", ".join(out)


def _union_sources(*src_lists):
    seen, out = set(), []
    for lst in src_lists:
        for s in (lst or []):
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out


# ── 1단계 변형: merge / polish / reclassify ──────────────────────────────────

def merge_entries(entries, keys, into_title=None, body=None):
    """여러 엔트리를 하나로 병합한다. sources/tags union, 첫 비어있지 않은 summary 유지.

    body 가 주어지면 그것으로(사서가 재작성한 통합 본문), 아니면 본문들을 이어 붙인다.
    결과 scope/repo 는 첫 엔트리 것을 따른다. tier 는 하나라도 primary 면 primary.
    오래된 키들을 제거하고 (재계산한) 새 키로 삽입한 뒤 새 키를 반환한다.
    """
    parts = [entries[k] for k in keys]
    first = parts[0]
    merged = {
        "title": into_title or first["title"],
        "scope": first["scope"],
        "repo": first.get("repo"),
        "summary": next((p.get("summary") for p in parts if p.get("summary")), ""),
        "tags": _union_tags(*[p.get("tags", "") for p in parts]),
        "body": body if body is not None else "\n\n".join(
            p.get("body", "") for p in parts if p.get("body")),
        "tier": (HK.TIER_PRIMARY if any(not HK.is_candidate(p) for p in parts)
                 else HK.TIER_CANDIDATE),
        "sources": _union_sources(*[p.get("sources", []) for p in parts]),
    }
    for k in keys:
        del entries[k]
    new_key = _recompute(merged)
    entries[new_key] = merged
    return new_key


def polish_entry(entries, key, title=None, summary=None, tags=None, body=None):
    """본문/summary/tags/title 을 다듬는다. title 이 바뀌면 키를 재계산해 옮긴다(키 반환)."""
    e = entries[key]
    if title is not None:
        e["title"] = title
    if summary is not None:
        e["summary"] = summary
    if tags is not None:
        e["tags"] = tags
    if body is not None:
        e["body"] = body
    del entries[key]
    new_key = _recompute(e)
    entries[new_key] = e
    return new_key


def reclassify_entry(entries, key, scope=None, repo=None):
    """scope/repo 를 바꿔 재분류한다 → 키/dest/anchor 재계산 후 옮긴다(새 키 반환)."""
    e = entries[key]
    if scope is not None:
        e["scope"] = scope
    if repo is not None:
        e["repo"] = repo
    if e["scope"] == "playbook":
        e["repo"] = None
    del entries[key]
    new_key = _recompute(e)
    entries[new_key] = e
    return new_key


# ── 2단계 변형: candidate tiering ────────────────────────────────────────────

def add_candidate(entries, title, body, scope="playbook", repo=None,
                  summary="", tags="", sources=None):
    """불확실한 신규 지식을 candidate tier 로 격리 추가한다(사람 승인 전, 1급 아님)."""
    e = {
        "title": title,
        "scope": scope,
        "repo": (repo or None) if scope == "repo" else None,
        "summary": summary,
        "tags": tags,
        "body": body,
        "tier": HK.TIER_CANDIDATE,
        "sources": list(sources or []),
    }
    new_key = _recompute(e)
    entries[new_key] = e
    return new_key


def promote_candidate(entries, key):
    """candidate → primary 승격(사람 승인 시). 1급 키 충돌 시 sources 만 합치고 후보 흡수.

    승격 후 1급 키를 반환한다. 후보가 아니면 ValueError.
    """
    e = entries.get(key)
    if e is None:
        raise KeyError(key)
    if not HK.is_candidate(e):
        raise ValueError(f"not a candidate: {key}")
    del entries[key]
    e["tier"] = HK.TIER_PRIMARY
    new_key = _recompute(e)
    if new_key in entries:
        existing = entries[new_key]
        existing["sources"] = _union_sources(existing.get("sources", []),
                                              e.get("sources", []))
    else:
        entries[new_key] = e
    return new_key


# ── Slack 보고 형식 ──────────────────────────────────────────────────────────

def format_report(merged, polished, candidates):
    return f"정리: 병합 {merged} · 다듬음 {polished} · 후보 {candidates}(검토 요청)"


# ── 사서 에이전트 기동 (supervisor 가 호출) ──────────────────────────────────

def run_librarian(root, claude_bin):
    """headless claude 로 사서 큐레이션 패스를 1회 수행시킨다(마스터와 분리된 역할).

    매번 fresh 세션 — 큐레이션은 그날치 무상태 패스다(마스터처럼 맥락 이어갈 필요 없음).
    """
    user_prompt = ("너는 tokendance 사서다. 시스템 프롬프트의 지침대로 지식 라이브러리 "
                   "큐레이션 패스를 정확히 한 번 수행한 뒤 종료하라.")
    sysprompt = PROMPT.build(root, "librarian")
    args = [claude_bin, "-p", user_prompt, "--dangerously-skip-permissions",
            "--append-system-prompt", sysprompt, "--output-format", "json"]
    env = {**os.environ, "IS_SANDBOX": "1"}   # root 자율 권한
    return subprocess.run(args, cwd=root, env=env, capture_output=True, text=True)


# ── CLI (flock 안에서 ledger 편집 + 재렌더) ──────────────────────────────────

def _read_body(args):
    """--body TEXT 우선, 없으면 --body-file PATH('-'=stdin), 둘 다 없으면 None."""
    if getattr(args, "body", None) is not None:
        return args.body
    bf = getattr(args, "body_file", None)
    if bf:
        if bf == "-":
            return sys.stdin.read()
        with open(bf) as f:
            return f.read()
    return None


def _commit(root, entries):
    """변경된 entries 를 ledger 에 저장하고 library 를 재렌더한다(락 보유 중 호출)."""
    HK.save_ledger(root, {"version": 1, "entries": entries})
    HK._render_library(root, HK.load_ledger(root))


def _cmd_list(root, args):
    """ledger 엔트리 요약을 JSON 으로 출력(에이전트가 큐레이션 계획에 사용). 읽기 전용."""
    entries = HK.load_ledger(root).get("entries", {})
    out = []
    for k, e in sorted(entries.items()):
        out.append({
            "key": k, "title": e.get("title"), "scope": e.get("scope"),
            "repo": e.get("repo"), "tier": HK.entry_tier(e),
            "summary": e.get("summary", ""), "tags": e.get("tags", ""),
            "body_len": len(e.get("body", "")), "sources": e.get("sources", []),
        })
    print(json.dumps(out, ensure_ascii=False, indent=2))


def main(argv=None):
    ap = argparse.ArgumentParser(description="사서: ledger 큐레이션(flock + 재렌더).")
    ap.add_argument("--root", default=HK._default_root())
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list")

    m = sub.add_parser("merge")
    m.add_argument("keys", nargs="+")
    m.add_argument("--into", dest="into")
    m.add_argument("--body")
    m.add_argument("--body-file")

    p = sub.add_parser("polish")
    p.add_argument("key")
    p.add_argument("--title")
    p.add_argument("--summary")
    p.add_argument("--tags")
    p.add_argument("--body")
    p.add_argument("--body-file")

    r = sub.add_parser("reclassify")
    r.add_argument("key")
    r.add_argument("--scope", choices=["playbook", "repo"])
    r.add_argument("--repo")

    c = sub.add_parser("add-candidate")
    c.add_argument("--title", required=True)
    c.add_argument("--body")
    c.add_argument("--body-file")
    c.add_argument("--scope", choices=["playbook", "repo"], default="playbook")
    c.add_argument("--repo")
    c.add_argument("--summary", default="")
    c.add_argument("--tags", default="")
    c.add_argument("--source", action="append", dest="sources")

    pr = sub.add_parser("promote")
    pr.add_argument("key")

    sub.add_parser("render")

    rep = sub.add_parser("report")
    rep.add_argument("--merged", type=int, default=0)
    rep.add_argument("--polished", type=int, default=0)
    rep.add_argument("--candidates", type=int, default=0)
    rep.add_argument("--post", action="store_true", help="Slack 으로도 전송")

    args = ap.parse_args(argv)
    root = args.root

    if args.cmd == "list":
        return _cmd_list(root, args)

    if args.cmd == "report":
        text = format_report(args.merged, args.polished, args.candidates)
        print(text)
        if args.post:
            import slack as SL
            SL.post(root, text)
        return

    # 이하 변형 명령: 모두 flock 안에서 load→mutate→save→재렌더.
    with HK.ledger_lock(root):
        ledger = HK.load_ledger(root)
        entries = ledger.setdefault("entries", {})
        if args.cmd == "merge":
            nk = merge_entries(entries, args.keys, into_title=args.into,
                               body=_read_body(args))
            _commit(root, entries)
            print(nk)
        elif args.cmd == "polish":
            nk = polish_entry(entries, args.key, title=args.title,
                              summary=args.summary, tags=args.tags, body=_read_body(args))
            _commit(root, entries)
            print(nk)
        elif args.cmd == "reclassify":
            nk = reclassify_entry(entries, args.key, scope=args.scope, repo=args.repo)
            _commit(root, entries)
            print(nk)
        elif args.cmd == "add-candidate":
            nk = add_candidate(entries, args.title, _read_body(args) or "",
                               scope=args.scope, repo=args.repo, summary=args.summary,
                               tags=args.tags, sources=args.sources)
            _commit(root, entries)
            print(nk)
        elif args.cmd == "promote":
            nk = promote_candidate(entries, args.key)
            _commit(root, entries)
            print(nk)
        elif args.cmd == "render":
            _commit(root, entries)
            print("rendered")


if __name__ == "__main__":
    main()
