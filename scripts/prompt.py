#!/usr/bin/env python3
"""프롬프트 조립.

  python3 scripts/prompt.py build master   # prompts/master/*.md 정렬 연결, 또는 prompts/master.md

`prompts/<name>/` 디렉토리가 있으면 그 안 `*.md` 를 파일명 정렬 순으로 이어 붙인다
(예: 01-persona.md, 02-tools.md, 03-process.md, 04-rules.md).
없으면 단일 파일 `prompts/<name>.md` 를 쓴다. 둘 다 없으면 에러.
"""
import argparse
import glob
import os
import sys


def build(root, name):
    base = os.path.join(root, "prompts")
    d = os.path.join(base, name)
    if os.path.isdir(d):
        parts = sorted(glob.glob(os.path.join(d, "*.md")))
        if not parts:
            raise ValueError(f"empty prompt dir: {d}")
        return "\n\n".join(open(p).read().rstrip() for p in parts) + "\n"
    f = os.path.join(base, f"{name}.md")
    with open(f) as fh:
        return fh.read()


def _default_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build"])
    ap.add_argument("name")
    ap.add_argument("--root", default=_default_root())
    args = ap.parse_args(argv)
    sys.stdout.write(build(args.root, args.name))


if __name__ == "__main__":
    main()
