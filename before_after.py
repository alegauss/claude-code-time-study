"""The natural experiment: the same repos, the same author, before vs after.

Every other number in this report needs an assumption to become a comparison.
This one does not. For each repo it takes the window in which Claude Code was
used and an equal-length window immediately before it, and measures what landed
in git in each -- same codebase, same developer, same tooling except for one
variable.

Bot commits (dependabot, copilot) are excluded so the comparison is
human-directed work only. Author identities are used for filtering and are
never written to the output.

Usage:
    python before_after.py [--data data.json] [--out before_after.json]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from classify import classify_path
from git_delta import GENERATED_RE, run_git

SEP = "\x01"

# Automated committers: their line counts are dependency bumps, not authored work.
BOT_RE = re.compile(r"\[bot\]|dependabot|copilot-swe-agent|renovate|github-actions",
                    re.I)

# A repo needs at least this much Claude time before a comparison means anything.
MIN_ACTIVE_H = 3.0


def window_stats(root: Path, start: datetime, end: datetime) -> dict:
    """Human-authored line and commit activity inside [start, end)."""
    out = run_git(root, [
        "log", "--no-merges",
        f"--since={start:%Y-%m-%dT%H:%M:%S}",
        f"--until={end:%Y-%m-%dT%H:%M:%S}",
        f"--format={SEP}%ae{SEP}%ad", "--date=format:%Y-%m-%d",
        "--numstat",
    ])
    if out is None:
        return {}

    kinds = ("code", "test", "docs", "config")
    added = defaultdict(int)
    removed = defaultdict(int)
    commits = 0
    active_days: set[str] = set()
    files: set[str] = set()
    skip_commit = False

    for line in out.splitlines():
        if line.startswith(SEP):
            parts = line.split(SEP)
            author = parts[1] if len(parts) > 1 else ""
            day = parts[2] if len(parts) > 2 else ""
            skip_commit = bool(BOT_RE.search(author))
            if not skip_commit:
                commits += 1
                if day:
                    active_days.add(day)
            continue
        if skip_commit or not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) != 3 or cols[0] == "-":
            continue
        try:
            a, d = int(cols[0]), int(cols[1])
        except ValueError:
            continue
        path = cols[2]
        if GENERATED_RE.search(path):
            continue
        kind = classify_path(path)
        if kind not in kinds:
            continue
        added[kind] += a
        removed[kind] += d
        files.add(path)

    return {
        "added": {k: added.get(k, 0) for k in kinds},
        "net": {k: added.get(k, 0) - removed.get(k, 0) for k in kinds},
        "added_total": sum(added.values()),
        "net_total": sum(added.values()) - sum(removed.values()),
        "commits": commits,
        "active_days": len(active_days),
        "files_touched": len(files),
        "from": f"{start:%Y-%m-%d}",
        "to": f"{end:%Y-%m-%d}",
        "span_days": round((end - start).total_seconds() / 86400, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data.json")
    ap.add_argument("--out", default="before_after.json")
    args = ap.parse_args()

    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    rows = []

    for p in data["projects"]:
        cwd = p.get("cwd")
        active_h = sum(p["phase_s"].values()) / 3600
        if not cwd or active_h < MIN_ACTIVE_H or not Path(cwd).is_dir():
            continue
        root = Path(cwd)
        inside = run_git(root, ["rev-parse", "--is-inside-work-tree"])
        if not inside or inside.strip() != "true":
            continue

        after_start = datetime.fromtimestamp(p["start"], timezone.utc)
        after_end = datetime.fromtimestamp(p["end"], timezone.utc)
        span = after_end - after_start
        if span < timedelta(days=3):
            continue
        before_start = after_start - span

        before = window_stats(root, before_start, after_start)
        after = window_stats(root, after_start, after_end)
        if not before or not after:
            continue

        rows.append({
            "name": p["name"],
            "label": cwd.replace("\\", "/").rstrip("/").split("/")[-1],
            "active_h": round(active_h, 2),
            "human_h": round(sum(p["human_s"].values()) / 3600, 2),
            "before": before,
            "after": after,
        })
        b, a = before["net_total"], after["net_total"]
        print(f"  {p['name'][:38]:38s} before {b:>8,} / after {a:>8,}  "
              f"({(a / b if b > 0 else 0):5.1f}x)   days {before['active_days']:>3}->"
              f"{after['active_days']:>3}", flush=True)

    # Totals across every repo that qualified.
    def _sum(side: str, field: str) -> int:
        return sum(r[side][field] for r in rows)

    totals = {
        side: {
            "net_total": _sum(side, "net_total"),
            "added_total": _sum(side, "added_total"),
            "commits": _sum(side, "commits"),
            "active_days": _sum(side, "active_days"),
            "files_touched": _sum(side, "files_touched"),
            "net": {
                k: sum(r[side]["net"][k] for r in rows)
                for k in ("code", "test", "docs", "config")
            },
        }
        for side in ("before", "after")
    }

    Path(args.out).write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "min_active_h": MIN_ACTIVE_H,
        "note": "bot commits excluded; equal-length windows per repo",
        "repos": rows,
        "totals": totals,
    }, indent=1), encoding="utf-8")

    b, a = totals["before"], totals["after"]
    print(f"\nTOTAL  before net {b['net_total']:,} in {b['active_days']} active days"
          f"  ({b['net_total'] / max(1, b['active_days']):.0f}/day, {b['commits']} commits)")
    print(f"       after  net {a['net_total']:,} in {a['active_days']} active days"
          f"  ({a['net_total'] / max(1, a['active_days']):.0f}/day, {a['commits']} commits)")
    print(f"\nwrote {args.out} -- {len(rows)} repos compared")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
