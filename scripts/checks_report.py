#!/usr/bin/env python3
"""run-checks.sh 의 실행 결과를 checks.json(기계용)/checks.md(사람용) 로 직렬화한다.

run-checks.sh 가 명령별 결과를 탭 구분 라인(`exit\tduration\tcmd`)으로 RESULTS 파일에
쌓아두면, 이 스크립트가 전체 로그 tail 과 함께 구조화 산출물로 만든다.
status.json 처럼 직접 편집을 피하고 단일 통로로 일관된 포맷을 보장하기 위함."""
import argparse
import json
import os
from datetime import datetime, timezone

LOG_TAIL_LINES = 120
LOG_TAIL_CHARS = 6000


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_results(path):
    cmds = []
    if not path or not os.path.exists(path):
        return cmds
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t", 2)
            if len(parts) != 3:
                continue
            rc, dur, cmd = parts
            try:
                rc = int(rc)
            except ValueError:
                rc = None
            try:
                dur = int(dur)
            except ValueError:
                dur = None
            cmds.append({"cmd": cmd, "exit": rc, "duration_s": dur})
    return cmds


def _log_tail(path):
    if not path or not os.path.exists(path):
        return ""
    with open(path, errors="replace") as f:
        lines = f.readlines()
    tail = "".join(lines[-LOG_TAIL_LINES:])
    if len(tail) > LOG_TAIL_CHARS:
        tail = "…(truncated)…\n" + tail[-LOG_TAIL_CHARS:]
    return tail


def build(task_id, status, source, cwd, results_path, log_path):
    cmds = _read_results(results_path)
    passed = sum(1 for c in cmds if c["exit"] == 0)
    return {
        "task_id": task_id,
        "status": status,                       # passed | failed | skipped
        "source": source,                       # override | manifest | autodetect:* | none
        "cwd": cwd,
        "generated": _now(),
        "total": len(cmds),
        "passed": passed,
        "failed": len(cmds) - passed,
        "commands": cmds,
        "log_path": log_path,
        "log_tail": _log_tail(log_path),
    }


_BADGE = {"passed": "✅ PASSED", "failed": "❌ FAILED", "skipped": "⏭️ SKIPPED"}


def render_md(d):
    out = []
    out.append(f"# checks: {d['task_id']} — {_BADGE.get(d['status'], d['status'])}")
    out.append("")
    out.append(f"- 생성: {d['generated']}")
    out.append(f"- 소스: `{d['source']}`")
    out.append(f"- 실행 위치(cwd): `{d['cwd']}`")
    if d["status"] == "skipped":
        out.append("")
        out.append("검증 명령을 찾지 못해 자동 테스트를 건너뜀. "
                   "필요하면 `state/tasks/<id>/check.cmd` 또는 레포 `.tokendance-checks` 로 명령을 지정.")
    else:
        out.append(f"- 결과: {d['passed']}/{d['total']} 명령 통과")
        out.append("")
        out.append("| # | 명령 | exit | 시간(s) |")
        out.append("|---|------|------|---------|")
        for i, c in enumerate(d["commands"], 1):
            mark = "✅" if c["exit"] == 0 else "❌"
            cmd = c["cmd"].replace("|", "\\|")
            out.append(f"| {i} | `{cmd}` {mark} | {c['exit']} | {c['duration_s']} |")
    if d["log_tail"].strip():
        out.append("")
        out.append("<details><summary>로그 tail</summary>")
        out.append("")
        out.append("```")
        out.append(d["log_tail"].rstrip("\n"))
        out.append("```")
        out.append("")
        out.append("</details>")
    out.append("")
    out.append(f"전체 로그: `{d['log_path']}`")
    out.append("")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--status", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--cwd", required=True)
    ap.add_argument("--results", default="")
    ap.add_argument("--log", default="")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md", required=True)
    args = ap.parse_args(argv)

    d = build(args.task_id, args.status, args.source, args.cwd, args.results, args.log)
    with open(args.out_json, "w") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
        f.write("\n")
    with open(args.out_md, "w") as f:
        f.write(render_md(d))


if __name__ == "__main__":
    main()
