"""Ground-truth output: lines actually landed in git while Claude Code was used.

The line counts taken from transcripts measure *typing*, not delivery -- a file
rewritten five times counts five times. To get a denominator that survives
scrutiny, this asks git how much code actually changed in each repo since the
first Claude Code session for that repo, split into source / test / docs, and
broken down per author so someone else's commits don't get credited.

Usage:
    python git_delta.py [--data data.json] [--out git_delta.json]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from classify import classify_path

SEP = "\x01"

# Paths whose lines nobody authored: lockfiles, build output, minified bundles,
# generated data. Counting them as delivered work would inflate every rate.
GENERATED_RE = re.compile(
    r"(?:^|/)(?:dist|build|out|target|node_modules|vendor|coverage|__snapshots__"
    r"|\.next|\.nuxt|generated|gen|_generated)/"
    r"|(?:^|/)(?:package-lock\.json|pnpm-lock\.yaml|yarn\.lock|poetry\.lock"
    r"|Cargo\.lock|composer\.lock|Gemfile\.lock|go\.sum|packages\.lock\.json)$"
    r"|\.(?:min\.js|min\.css|map|bundle\.js|lock)$",
    re.I,
)


def run_git(root: Path, args: list[str]) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0 or r.stdout is None:
        return None
    return r.stdout.decode("utf-8", errors="replace")


def endpoint_diff(root: Path, since_ts: float) -> dict | None:
    """The authoritative delivery measure: one diff, start of window to HEAD.

    Reproducible by hand in two commands, which is what makes it defensible:
        git rev-list -1 --before=<date> HEAD
        git diff --numstat <that>..HEAD
    Unlike summing per-commit numstat, this cannot double-count a file that was
    revised many times -- it compares two snapshots.
    """
    since = datetime.fromtimestamp(since_ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    base = run_git(root, ["rev-list", "-1", f"--before={since}", "HEAD"])
    if not base or not base.strip():
        return None
    base = base.strip().splitlines()[0]
    out = run_git(root, ["diff", "--numstat", f"{base}..HEAD"])
    if out is None:
        return None

    kinds = ("code", "test", "docs", "config")
    added = defaultdict(int)
    removed = defaultdict(int)
    files = defaultdict(int)
    excluded = 0
    for line in out.splitlines():
        cols = line.split("\t")
        if len(cols) != 3 or cols[0] == "-":
            continue
        try:
            a, d = int(cols[0]), int(cols[1])
        except ValueError:
            continue
        path = cols[2]
        if GENERATED_RE.search(path):
            excluded += a
            continue
        kind = classify_path(path)
        if kind not in kinds:
            continue
        added[kind] += a
        removed[kind] += d
        files[kind] += 1

    return {
        "base_commit": base[:12],
        "base_date": since,
        "added": {k: added.get(k, 0) for k in kinds},
        "removed": {k: removed.get(k, 0) for k in kinds},
        "net": {k: added.get(k, 0) - removed.get(k, 0) for k in kinds},
        "files": {k: files.get(k, 0) for k in kinds},
        "generated_added_excluded": excluded,
    }


def collect(root: Path, since_ts: float) -> dict | None:
    since = datetime.fromtimestamp(since_ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    out = run_git(root, [
        "log", "--no-merges", f"--since={since}",
        f"--format={SEP}%ct{SEP}%ae", "--numstat",
    ])
    if out is None:
        return None

    kinds = ("code", "test", "docs", "config")
    added = defaultdict(int)
    removed = defaultdict(int)
    commits = 0
    files_touched = set()
    generated_added = 0

    for line in out.splitlines():
        if line.startswith(SEP):
            commits += 1
            continue
        if not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) != 3:
            continue
        a_raw, d_raw, path = cols
        if a_raw == "-" or d_raw == "-":
            continue  # binary
        try:
            a, d = int(a_raw), int(d_raw)
        except ValueError:
            continue
        if GENERATED_RE.search(path):
            generated_added += a
            continue
        kind = classify_path(path)
        if kind not in kinds:
            continue
        added[kind] += a
        removed[kind] += d
        files_touched.add(path)

    return {
        "since": since,
        "commits": commits,
        "files_touched": len(files_touched),
        # Gross additions across every commit: a file edited 50 times is
        # counted 50 times. This is churn, not delivery.
        "added": {k: added.get(k, 0) for k in kinds},
        "removed": {k: removed.get(k, 0) for k in kinds},
        # Additions minus deletions: the lines that actually survived. This is
        # the denominator every rate in the report uses.
        "net": {k: added.get(k, 0) - removed.get(k, 0) for k in kinds},
        "generated_added_excluded": generated_added,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data.json")
    ap.add_argument("--out", default="git_delta.json")
    args = ap.parse_args()

    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    result = {}
    for p in data["projects"]:
        cwd = p.get("cwd")
        if not cwd or not Path(cwd).is_dir():
            continue
        root = Path(cwd)
        info = collect(root, p["start"])
        if info is None:
            print(f"  skip (not git) {p['name']}")
            continue
        ep = endpoint_diff(root, p["start"])
        result[p["name"]] = {"cwd": cwd, **info, "endpoint": ep}
        gross = sum(info["added"].values())
        ep_net = sum(ep["net"].values()) if ep else 0
        churn = gross / ep_net if ep_net > 0 else 0
        print(f"  {p['name'][:40]:40s} delivered {ep_net:>8,}  churn {churn:4.1f}x  "
              f"{info['commits']:>4} commits", flush=True)

    Path(args.out).write_text(
        json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "repos": result,
        }, indent=1),
        encoding="utf-8",
    )
    print(f"\nwrote {args.out} -- {len(result)} repos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
