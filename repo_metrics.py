"""Measure the codebases themselves, to give the time data a maturity axis.

For every project seen in data.json, walks its working tree to count source and
test lines, and asks git how old the repo is and how many commits it carries.
The result is a maturity score used by the report to explain why test effort
varies so much between projects.

Usage:
    python repo_metrics.py [--data data.json] [--out repos.json]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from classify import classify_path

# Directories that are never the user's own code.
SKIP_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "target", "build", "dist", "out",
    "bin", "obj", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".gradle", ".idea", ".vs", ".vscode",
    "vendor", "coverage", ".next", ".nuxt", ".svelte-kit", "site-packages",
    ".terraform", "Pods", "DerivedData", ".angular", ".cache", "tmp",
    "package-lock.json", "webpack", ".yarn", ".pnpm-store",
}

MAX_FILE_BYTES = 2_000_000
MAX_FILES = 60_000


def count_lines(path: Path) -> int:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return 0
        with open(path, "rb") as fh:
            return fh.read().count(b"\n") + 1
    except OSError:
        return 0


def scan_tree(root: Path) -> dict:
    code_loc = test_loc = docs_loc = config_loc = 0
    code_files = test_files = docs_files = 0
    seen = 0

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            seen += 1
            if seen > MAX_FILES:
                return {
                    "code_loc": code_loc, "test_loc": test_loc,
                    "docs_loc": docs_loc, "config_loc": config_loc,
                    "code_files": code_files, "test_files": test_files,
                    "docs_files": docs_files, "truncated": True,
                }
            full = Path(dirpath) / fn
            rel = str(full).replace("\\", "/")
            kind = classify_path(rel)
            if kind == "unknown":
                continue
            n = count_lines(full)
            if n == 0:
                continue
            if kind == "test":
                test_loc += n
                test_files += 1
            elif kind == "code":
                code_loc += n
                code_files += 1
            elif kind == "docs":
                docs_loc += n
                docs_files += 1
            else:
                config_loc += n

    return {
        "code_loc": code_loc, "test_loc": test_loc,
        "docs_loc": docs_loc, "config_loc": config_loc,
        "code_files": code_files, "test_files": test_files,
        "docs_files": docs_files, "truncated": False,
    }


def _git(root: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0 or r.stdout is None:
        return None
    # Author names and commit subjects are not reliably in the console codepage.
    return r.stdout.decode("utf-8", errors="replace").strip()


def git_info(root: Path) -> dict:
    if _git(root, "rev-parse", "--is-inside-work-tree") != "true":
        return {"is_git": False}

    first = _git(root, "log", "--reverse", "--format=%ct", "--max-parents=0")
    last = _git(root, "log", "-1", "--format=%ct")
    count = _git(root, "rev-list", "--count", "HEAD")
    authors = _git(root, "shortlog", "-sn", "--all", "--no-merges")

    first_ts = None
    if first:
        try:
            first_ts = int(first.splitlines()[0])
        except (ValueError, IndexError):
            first_ts = None
    last_ts = None
    if last:
        try:
            last_ts = int(last)
        except ValueError:
            last_ts = None

    age_days = None
    if first_ts and last_ts:
        age_days = round((last_ts - first_ts) / 86400, 1)

    return {
        "is_git": True,
        "first_commit": first_ts,
        "last_commit": last_ts,
        "age_days": age_days,
        "commits": int(count) if count and count.isdigit() else None,
        "authors": len(authors.splitlines()) if authors else None,
    }


def maturity(repo: dict, git: dict) -> dict:
    """A 0-100 maturity score from three independent signals.

    Size (how much code exists), age (how long it has been alive), and test
    coverage ratio -- each capped, then averaged. Deliberately crude: its job
    is to order projects along an axis, not to be an absolute measure.
    """
    code = repo.get("code_loc", 0) or 0
    tests = repo.get("test_loc", 0) or 0

    # 30k LOC of source counts as a full-size codebase.
    size = min(1.0, code / 30_000)
    # Two years of history counts as fully aged.
    age_days = git.get("age_days") or 0
    age = min(1.0, age_days / 730)
    # A 1:1 test-to-source ratio counts as fully tested.
    ratio = (tests / code) if code else 0.0
    cover = min(1.0, ratio)

    score = round(100 * (0.35 * size + 0.25 * age + 0.40 * cover), 1)
    return {
        "score": score,
        "size_factor": round(size, 3),
        "age_factor": round(age, 3),
        "coverage_factor": round(cover, 3),
        "test_ratio": round(ratio, 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data.json")
    ap.add_argument("--out", default="repos.json")
    args = ap.parse_args()

    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    out = {}

    for p in data["projects"]:
        name, cwd = p["name"], p.get("cwd")
        if not cwd:
            out[name] = {"cwd": None, "exists": False}
            continue
        root = Path(cwd)
        if not root.is_dir():
            out[name] = {"cwd": cwd, "exists": False}
            print(f"  missing  {name} -> {cwd}")
            continue

        print(f"  scanning {name} -> {cwd}", flush=True)
        repo = scan_tree(root)
        git = git_info(root)
        out[name] = {
            "cwd": cwd, "exists": True,
            **repo, "git": git, "maturity": maturity(repo, git),
        }

    Path(args.out).write_text(
        json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "repos": out,
        }, indent=1),
        encoding="utf-8",
    )
    have = sum(1 for v in out.values() if v.get("exists"))
    print(f"\nwrote {args.out} -- {have}/{len(out)} repos scanned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
