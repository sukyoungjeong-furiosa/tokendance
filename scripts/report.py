#!/usr/bin/env python3
"""상태에서 리포트를 템플릿 생성(줄글 형식 규칙을 코드로).

  python3 scripts/report.py            # 리포트 텍스트를 stdout + state/reports/<KST date>.md 에 append
  python3 scripts/report.py --print    # 파일에 쓰지 않고 텍스트만 출력(Slack 용)

마스터는 이 텍스트를 그대로 쓰거나, 🟡 항목에 판단 한 줄을 덧붙여 Slack 에 보낸다.
"""
import argparse
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tasks as TK
import status as S

# 상태 → (이모지, 라벨). 표시 순서이기도 하다.
SECTIONS = [
    ("running", "🟢", "순항"),
    ("review", "🔎", "리뷰 대기"),
    ("needs_human", "🟡", "판단 필요"),
    ("blocked", "🔴", "막힘"),
    ("queued", "⏳", "대기"),
    ("done", "✅", "완료"),
    ("failed", "⚫", "실패"),
]


def _kst(now=None):
    now = now or datetime.now(timezone.utc)
    return (now + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M KST")


def _oneliner(root, d):
    """task 한 줄 요약: 제목 + (사유/진행 단서)."""
    title = d.get("title") or d["id"]
    note = d.get("failure_reason") or ""
    if not note and d.get("state") in ("running", "needs_human"):
        # progress.md 첫 비어있지 않은 줄(헤더 제외)을 단서로.
        p = os.path.join(S.task_dir(root, d["id"]), "progress.md")
        try:
            for line in open(p):
                s = line.strip().lstrip("#").strip()
                if s:
                    note = s
                    break
        except OSError:
            pass
    return f"{d['id']} — {title}" + (f" · {note[:80]}" if note else "")


def counts_line(root):
    """상태별 카운트 한 줄(예: '🟢2 🔎1 🟡0 ...'). ack/요약에 재사용."""
    by = {}
    for d in TK.list_tasks(root):
        by[d.get("state")] = by.get(d.get("state"), 0) + 1
    return " ".join(f"{emoji}{by.get(st, 0)}" for st, emoji, _ in SECTIONS)


# 수신 ack 에서 이름까지 나열할 상태(title 이 있는 task 들). 종료 상태는 숫자만.
_ACK_NAMED = [("running", "🟢", "진행"), ("review", "🔎", "리뷰대기"),
              ("needs_human", "🟡", "확인필요"), ("blocked", "🔴", "막힘"),
              ("queued", "⏳", "대기")]
_ACK_COUNTED = [("done", "✅"), ("failed", "⚫")]


def ack_text(root, max_each=3):
    """수신 즉시 보내는 상태 요약(LLM 없이). 방금 받은 건 inbox 미처리로, 진행 중 작업은 이름으로 나열.

    각 상태 max_each 개까지만 이름을 적고 나머지는 '+N'. 대량 상태는 숫자만 → 길이 bounded.
    """
    import inbox as IB
    lines = ["👀 받았어요!"]
    pend = IB.list_pending(root)
    if pend:
        echoes = []
        for n in pend[:max_each]:
            try:
                first = (IB.read_pending(root, n).strip().splitlines() or [""])[0]
            except OSError:
                first = "?"
            echoes.append(f"“{first[:24]}”")
        more = f" +{len(pend) - max_each}건 더" if len(pend) > max_each else ""
        lines.append(f"• 미처리 {len(pend)}건(곧 분류): {', '.join(echoes)}{more}")

    by = {}
    for d in TK.list_tasks(root):
        by.setdefault(d.get("state"), []).append(d)
    for st, emoji, label in _ACK_NAMED:
        items = by.get(st, [])
        if not items:
            continue
        names = [(d.get("title") or d["id"])[:28] for d in items[:max_each]]
        more = f" +{len(items) - max_each}" if len(items) > max_each else ""
        lines.append(f"• {emoji} {label} {len(items)}: {', '.join(names)}{more}")

    tail = " · ".join(f"{emoji}{len(by.get(st, []))}" for st, emoji in _ACK_COUNTED)
    lines.append(f"({tail}) — 확인하고 곧 처리해서 알려드릴게요 🙂")
    return "\n".join(lines)


def build_report(root, now=None):
    tasks = TK.list_tasks(root)
    by = {}
    for d in tasks:
        by.setdefault(d.get("state"), []).append(d)
    counts = " ".join(f"{emoji}{len(by.get(st, []))}" for st, emoji, _ in SECTIONS)
    lines = [f"🤖 tokendance — 사이클 요약 ({_kst(now)})", "", counts]
    for st, emoji, label in SECTIONS:
        items = by.get(st, [])
        if not items or st in ("queued",):       # queued 는 카운트만(상세 생략)
            continue
        lines.append("")
        lines.append(f"{emoji} {label}")
        for d in items:
            lines.append(f"  • {_oneliner(root, d)}")
    return "\n".join(lines) + "\n"


def _default_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=_default_root())
    ap.add_argument("--print", dest="only_print", action="store_true",
                    help="파일에 append 하지 않고 텍스트만 출력")
    args = ap.parse_args(argv)
    text = build_report(args.root)
    if not args.only_print:
        rdir = os.path.join(args.root, "state", "reports")
        os.makedirs(rdir, exist_ok=True)
        day = _kst().split(" ")[0]
        with open(os.path.join(rdir, f"{day}.md"), "a") as f:
            f.write(text + "\n")
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
