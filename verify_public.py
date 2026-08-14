"""Refuse to publish a page that still carries private detail.

The public report is built by redacting the private dataset, and a redaction
step is exactly the kind of code that silently stops working when a new field
is added upstream. So this checks the built artefact instead of trusting the
builder: it reads the *private* dataset, works out every string that must not
appear, and fails if any of them survived into the output.

Exit code 1 means do not commit.

Usage:
    python verify_public.py [--page docs/index.html] [--data report_data.json]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from build_report import PUBLIC_OWNERS

# Files that must never be tracked by git: they hold the unredacted dataset or
# machine-specific paths. .gitignore covers them, but a file added before the
# ignore rule existed stays tracked, so the build checks rather than assumes.
NEVER_TRACKED = {
    "data.json", "repos.json", "git_delta.json", "before_after.json",
    "report_data.json", "report.html", "report.fragment.html",
}
NEVER_TRACKED_DIRS = (".claude/",)


def check_tracked_files() -> list[str]:
    """Flag any sensitive file that git is currently tracking."""
    try:
        r = subprocess.run(["git", "ls-files"], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if r.returncode != 0 or not r.stdout:
        return []
    problems = []
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        path = line.strip().replace("\\", "/")
        if not path:
            continue
        if path.split("/")[-1] in NEVER_TRACKED or path in NEVER_TRACKED:
            problems.append(f"git is tracking a private data file: {path}")
        elif any(path.startswith(d) for d in NEVER_TRACKED_DIRS):
            problems.append(f"git is tracking a local-config file: {path}")
    return problems

# Absolute paths and user directories, whatever the project they belong to.
PATH_PATTERNS = [
    (r"[A-Za-z]:[\\/]{1,2}(?:Users|Git|Dev|tmp|Temp)", "absolute Windows path"),
    (r"/(?:home|Users)/[A-Za-z0-9._-]+/", "absolute POSIX home path"),
    (r"C:[\\/]{1,2}Users[\\/]{1,2}[A-Za-z0-9._-]+", "Windows user directory"),
    (r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}", "email address"),
    (r"\.claude[\\/]{1,2}projects", "transcript directory"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", default="docs/index.html")
    ap.add_argument("--data", default="report_data.json")
    args = ap.parse_args()

    page_path = Path(args.page)
    if not page_path.exists():
        print(f"FAIL  built page not found: {page_path}", file=sys.stderr)
        return 1
    page = page_path.read_text(encoding="utf-8")

    problems: list[str] = []

    # 1. Generic private-path and identity patterns.
    for pattern, what in PATH_PATTERNS:
        hits = re.findall(pattern, page)
        if hits:
            uniq = sorted(set(hits))[:4]
            problems.append(f"{what}: {len(hits)} occurrence(s), e.g. {uniq}")

    # 2. Every identity the private dataset says must not be published.
    data_path = Path(args.data)
    if data_path.exists():
        data = json.loads(data_path.read_text(encoding="utf-8"))
        forbidden: set[str] = set()
        for p in data.get("projects", []):
            owner = p.get("owner")
            if owner and owner not in PUBLIC_OWNERS:
                forbidden.add(owner)
                forbidden.add(p["label"])
                # The raw project key encodes the whole path, e.g.
                # "d--Git-azul-seat-map-..." -- never publishable.
                forbidden.add(p["name"])
            cwd = p.get("cwd")
            if cwd:
                forbidden.add(cwd)
        for term in sorted(forbidden):
            if len(term) < 4:
                continue
            if re.search(re.escape(term), page, re.I):
                problems.append(f"client identity leaked: {term!r}")
    else:
        print(f"warn  {data_path} not found -- identity check skipped",
              file=sys.stderr)

    # 3. Nothing sensitive may be under git control.
    problems.extend(check_tracked_files())

    size_kb = page_path.stat().st_size / 1024
    if problems:
        print(f"FAIL  {page_path} ({size_kb:.0f} KB) is NOT safe to publish:",
              file=sys.stderr)
        for p in problems:
            print(f"        - {p}", file=sys.stderr)
        return 1

    print(f"OK    {page_path} ({size_kb:.0f} KB) is safe to publish")
    print("      no absolute paths, no emails, no client identities,")
    print("      no private data files under git control")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
