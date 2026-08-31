#!/usr/bin/env python3
"""Syntax-check every ```python code fence in the docs.

Snippets are illustrative fragments (often assuming an ``async def main()``
and an open ``client``), not standalone scripts, so we parse rather than run
them, and allow top-level ``await``/``async for`` the same way a Python REPL
would.

    python scripts/check_snippets.py
"""

import ast
import pathlib
import re
import sys
import textwrap

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "node_modules", ".mint", ".mintlify"}

FENCE_RE = re.compile(r"```python\n(.*?)```", re.DOTALL)
# A bare `Name(` ... `)` block is a constructor/method *signature* shown for
# documentation, not executable code — e.g. `AsyncCominty(*, user_id=None, ...)`.
# `*,` (keyword-only marker) is only valid in a `def`, not a call, so we
# reparse these as a function definition instead of flagging them.
SIGNATURE_RE = re.compile(r"^([A-Za-z_]\w*)\(\s*$")


def iter_doc_files():
    for ext in ("*.mdx", "*.md"):
        for path in ROOT.rglob(ext):
            if not any(part in SKIP_DIRS for part in path.parts):
                yield path


def parses(snippet, filename):
    try:
        compile(snippet, filename, "exec", ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
        return True
    except SyntaxError:
        return False


def check_file(path):
    errors = []
    text = path.read_text()
    for i, match in enumerate(FENCE_RE.finditer(text), start=1):
        snippet = textwrap.dedent(match.group(1))
        name = f"{path}#snippet-{i}"
        if parses(snippet, name):
            continue

        lines = snippet.strip("\n").splitlines()
        sig_match = lines and SIGNATURE_RE.match(lines[0])
        if sig_match and lines[-1].rstrip().endswith(")"):
            as_def = "def " + lines[0] + "\n" + "\n".join(lines[1:-1]) + "\n): ...\n"
            if parses(as_def, name):
                continue

        try:
            compile(snippet, name, "exec", ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
        except SyntaxError as exc:
            errors.append(f"{name}: {exc}")
    return errors


def main():
    all_errors = []
    checked = 0
    for path in iter_doc_files():
        checked += 1
        all_errors.extend(check_file(path))

    print(f"checked {checked} doc file(s)")
    if all_errors:
        print(f"found {len(all_errors)} invalid python snippet(s):")
        for e in all_errors:
            print(f"  {e}")
        return 1

    print("all python snippets parse cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
