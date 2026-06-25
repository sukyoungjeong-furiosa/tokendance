#!/usr/bin/env python3
"""봇 토큰 기반 Slack 연동 (LLM 없이 — urllib 표준 라이브러리).

self/MCP 대신 봇 토큰(`config.local.md` 의 SLACK_BOT_TOKEN)으로 동작한다.
  - poll: 봇↔사용자 DM 의 새 사람 메시지를 inbox 로 옮기고 cursor 전진(공짜 폴링).
  - post: 텍스트를 그 DM 으로 전송.

  python3 scripts/slack.py poll          # 새 메시지 → inbox, 옮긴 건수 출력
  python3 scripts/slack.py post "텍스트"
  python3 scripts/slack.py check         # auth.test (봇 이름/팀 확인)
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import inbox as IB

API = "https://slack.com/api/"


def _call(token, method, **params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(API + method, data=data,
                                 headers={"Authorization": "Bearer " + token})
    return json.load(urllib.request.urlopen(req, timeout=15))


def enabled(root=None):
    return bool(C.get("SLACK_BOT_TOKEN", r=root)) and bool(C.get("SLACK_CHANNEL", r=root))


def _im_channel(token, user_id):
    op = _call(token, "conversations.open", users=user_id)
    return op["channel"]["id"] if op.get("ok") else None


def filter_new(messages, cursor_ts, human_user_id):
    """ts>cursor 이고 사람(human_user_id)이 보낸 메시지만 오래된→최신 순. 반환 [(ts, text)].

    봇 자신/타인/시스템(subtype) 메시지는 제외 → 자기 출력 재흡수·노이즈 방지.
    """
    base = float(cursor_ts) if cursor_ts else 0.0
    out = []
    for m in messages:
        ts = m.get("ts", "0")
        if float(ts) <= base:
            continue
        if m.get("user") != human_user_id or m.get("subtype"):
            continue
        out.append((ts, m.get("text", "")))
    out.sort(key=lambda x: float(x[0]))
    return out


def _read_cursor(root):
    try:
        with open(C.paths(root)["slack_cursor"]) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def _write_cursor(root, ts):
    p = C.paths(root)["slack_cursor"]
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(ts)


def poll_new(root):
    """새 사람 메시지를 inbox 로 옮기고 cursor 전진. 옮긴 건수 반환(비활성/실패 시 0)."""
    token = C.get("SLACK_BOT_TOKEN", r=root)
    user = C.get("SLACK_CHANNEL", r=root)
    if not (token and user):
        return 0
    try:
        ch = _im_channel(token, user)
        if not ch:
            return 0
        cursor = _read_cursor(root)
        h = _call(token, "conversations.history", channel=ch, oldest=cursor or "0", limit=50)
        msgs = h.get("messages", []) if h.get("ok") else []
    except Exception:
        return 0
    new = filter_new(msgs, cursor, user)
    for _ts, text in new:
        IB.add(root, text, slug="slack")
    if new:
        _write_cursor(root, new[-1][0])
    return len(new)


def post(root, text):
    token = C.get("SLACK_BOT_TOKEN", r=root)
    user = C.get("SLACK_CHANNEL", r=root)
    if not (token and user):
        return False
    try:
        ch = _im_channel(token, user)
        if not ch:
            return False
        return bool(_call(token, "chat.postMessage", channel=ch, text=text).get("ok"))
    except Exception:
        return False


def _default_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=_default_root())
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("poll")
    p = sub.add_parser("post")
    p.add_argument("text")
    sub.add_parser("check")
    args = ap.parse_args(argv)
    if args.cmd == "poll":
        print(poll_new(args.root))
    elif args.cmd == "post":
        print("ok" if post(args.root, args.text) else "FAILED")
    elif args.cmd == "check":
        tok = C.get("SLACK_BOT_TOKEN", r=args.root)
        print(json.dumps(_call(tok, "auth.test"), ensure_ascii=False) if tok else "no token")


if __name__ == "__main__":
    main()
