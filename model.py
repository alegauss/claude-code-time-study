"""Turn the raw measurements into a model: rates, fits, and a compact dataset.

Three jobs:

1. Join the three raw inputs (transcript time, repo shape, git deliveries) into
   one per-project record.
2. Fit the relationships the estimator needs -- how test effort scales with
   project maturity, and how many delivered lines an hour buys.
3. Emit a compact JSON the HTML report inlines, so every "what if" the reader
   asks (different human baseline rates, a different project size) is recomputed
   in the browser rather than baked in here.

The counterfactual -- "how long would this have taken without Claude Code" --
is deliberately NOT computed here. It cannot be measured, only assumed, so the
assumptions live as adjustable parameters in the report and the arithmetic
happens in front of the reader.

Usage:
    python model.py [--out report_data.json]
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

# Directory names that identify nothing on their own -- version worktrees and
# generic folders both collide across projects, so they borrow their parent.
_AMBIGUOUS = {"general", "app", "src", "latest", "main", "master", "web", "docs"}


def project_owner(cwd: str | None) -> str | None:
    """Owning organisation, taken as the directory right below the git root.

    Paths look like D:/Git/<owner>/<project>[/<worktree>], so the segment after
    "Git" identifies whose codebase it is. Used to keep client repositories out
    of the per-project listing.
    """
    if not cwd:
        return None
    parts = [p for p in cwd.replace("\\", "/").split("/") if p]
    for i, seg in enumerate(parts):
        if seg.lower() == "git" and i + 1 < len(parts):
            return parts[i + 1].lower()
    return None


def project_label(cwd: str | None, fallback: str) -> str:
    parts = (cwd or fallback).replace("\\", "/").rstrip("/").split("/")
    last = parts[-1]
    if len(parts) > 1 and (re.fullmatch(r"[\d._-]+", last) or last.lower() in _AMBIGUOUS):
        return "/".join(parts[-2:])
    return last

# Phases grouped the way the report talks about them.
PHASE_GROUPS = {
    "feature": ["feature"],
    "tests": ["test_write", "test_run"],
    "docs": ["docs_write", "planning"],
    "verify": ["verify", "run_app"],
    "explore": ["explore"],
    "overhead": ["vcs", "config_write", "other"],
}

# Default human baseline rates, in delivered lines per hour of focused work.
# These are the report's headline assumption and every one of them is a slider
# in the UI. Documented in README.md; sourced from the usual industry ranges for
# net delivered code including debugging and rework, not raw typing speed.
DEFAULT_BASELINE = {
    "rate_code": 20.0,
    "rate_test": 30.0,
    "rate_docs": 45.0,
    "rate_config": 25.0,
    # Integration, code review and rework that sits on top of authoring.
    "overhead_pct": 15.0,
    # Manual verification a human does that Claude's test runs replace.
    "manual_verify_pct": 20.0,
}

MIN_HOURS_FOR_FIT = 2.0


def hours(d: dict) -> float:
    return sum(d.values()) / 3600.0


def group_hours(phase_s: dict) -> dict:
    return {
        g: sum(phase_s.get(p, 0.0) for p in members) / 3600.0
        for g, members in PHASE_GROUPS.items()
    }


def linfit(pts: list[tuple[float, float, float]]) -> dict:
    """Weighted least squares y = a + b*x. pts = (x, y, weight)."""
    sw = sum(w for _, _, w in pts)
    if sw <= 0 or len(pts) < 3:
        return {"a": 0.0, "b": 0.0, "r2": 0.0, "n": len(pts)}
    mx = sum(x * w for x, _, w in pts) / sw
    my = sum(y * w for _, y, w in pts) / sw
    sxx = sum(w * (x - mx) ** 2 for x, _, w in pts)
    sxy = sum(w * (x - mx) * (y - my) for x, y, w in pts)
    b = sxy / sxx if sxx > 0 else 0.0
    a = my - b * mx
    sst = sum(w * (y - my) ** 2 for _, y, w in pts)
    sse = sum(w * (y - (a + b * x)) ** 2 for x, y, w in pts)
    r2 = 1 - sse / sst if sst > 0 else 0.0
    return {"a": round(a, 5), "b": round(b, 5), "r2": round(r2, 3), "n": len(pts)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data.json")
    ap.add_argument("--repos", default="repos.json")
    ap.add_argument("--git", default="git_delta.json")
    ap.add_argument("--out", default="report_data.json")
    args = ap.parse_args()

    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    repos = {}
    gitd = {}
    rp = Path(args.repos)
    if rp.exists():
        repos = json.loads(rp.read_text(encoding="utf-8")).get("repos", {})
    gp = Path(args.git)
    if gp.exists():
        gitd = json.loads(gp.read_text(encoding="utf-8")).get("repos", {})

    projects = []
    for p in data["projects"]:
        name = p["name"]
        ph = p["phase_s"]
        act = hours(ph)
        if act <= 0:
            continue
        hum = hours(p["human_s"])
        r = repos.get(name, {})
        g = gitd.get(name, {})
        mat = r.get("maturity") or {}
        # Delivered = the endpoint diff (window start -> HEAD). Negative net on
        # a kind means code was removed on balance; clamp so it never credits
        # negative work to a rate.
        ep = g.get("endpoint") or {}
        ep_net = ep.get("net") or {}
        delivered = {k: max(0, ep_net.get(k, 0)) for k in ("code", "test", "docs", "config")}
        gross_added = sum((g.get("added") or {}).values())
        net_total = sum(delivered.values())

        projects.append({
            "name": name,
            "label": project_label(p.get("cwd"), name),
            "owner": project_owner(p.get("cwd")),
            "cwd": p.get("cwd"),
            "start": p["start"],
            "end": p["end"],
            "sessions": p["counts"]["sessions"],
            "prompts": p["counts"]["prompts"],
            "test_runs": p["counts"]["test_runs"],
            "active_h": round(act, 2),
            "human_h": round(hum, 2),
            "human_breakdown_h": {k: round(v / 3600, 2) for k, v in p["human_s"].items()},
            "groups_h": {k: round(v, 2) for k, v in group_hours(ph).items()},
            "phases_h": {k: round(v / 3600, 3) for k, v in ph.items()},
            "phase_calls": p["phase_calls"],
            "audit_h": {k: round(v / 3600, 2) for k, v in p["audit_s"].items()},
            "typed_loc": p["loc"],
            "delivered": delivered,
            "gross_added": gross_added,
            "churn": round(gross_added / net_total, 2) if net_total > 0 else None,
            "files_delivered": sum((ep.get("files") or {}).values()),
            "base_commit": ep.get("base_commit"),
            "commits": g.get("commits", 0),
            "repo": {
                "code_loc": r.get("code_loc"),
                "test_loc": r.get("test_loc"),
                "docs_loc": r.get("docs_loc"),
                "age_days": (r.get("git") or {}).get("age_days"),
                "commits_total": (r.get("git") or {}).get("commits"),
                "maturity": mat.get("score"),
                "test_ratio": mat.get("test_ratio"),
            },
        })

    projects.sort(key=lambda x: -x["active_h"])

    # ---- fits -----------------------------------------------------------
    fitset = [
        p for p in projects
        if p["active_h"] >= MIN_HOURS_FOR_FIT and p["repo"]["maturity"] is not None
    ]

    test_share_fit = linfit([
        (p["repo"]["maturity"],
         100.0 * p["groups_h"]["tests"] / p["active_h"],
         p["active_h"])
        for p in fitset if p["active_h"] > 0
    ])

    feature_share_fit = linfit([
        (p["repo"]["maturity"],
         100.0 * p["groups_h"]["feature"] / p["active_h"],
         p["active_h"])
        for p in fitset if p["active_h"] > 0
    ])

    # Delivered lines per Claude-hour, against maturity: mature codebases cost
    # more hours per line.
    throughput_fit = linfit([
        (p["repo"]["maturity"],
         sum(p["delivered"].values()) / (p["active_h"] + p["human_h"]),
         p["active_h"])
        for p in fitset
        if sum(p["delivered"].values()) > 0 and (p["active_h"] + p["human_h"]) > 0
    ])

    # ---- totals ---------------------------------------------------------
    t = data["totals"]
    tot_act = hours(t["phase_s"])
    tot_hum = hours(t["human_s"])
    tot_delivered = {"code": 0, "test": 0, "docs": 0, "config": 0}
    tot_gross = 0
    tot_commits = 0
    tot_files = 0
    for p in projects:
        for k in tot_delivered:
            tot_delivered[k] += p["delivered"][k]
        tot_gross += p["gross_added"]
        tot_commits += p["commits"]
        tot_files += p["files_delivered"]

    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "first_session": min(p["start"] for p in projects),
            "last_session": max(p["end"] for p in projects),
        },
        "attribution": data["attribution"],
        "phase_groups": PHASE_GROUPS,
        "baseline_defaults": DEFAULT_BASELINE,
        "totals": {
            "active_h": round(tot_act, 2),
            "human_h": round(tot_hum, 2),
            "phases_h": {k: round(v / 3600, 2) for k, v in t["phase_s"].items()},
            "phase_calls": t["phase_calls"],
            "audit_h": {k: round(v / 3600, 2) for k, v in t["audit_s"].items()},
            "groups_h": {k: round(v, 2) for k, v in group_hours(t["phase_s"]).items()},
            "human_breakdown_h": {k: round(v / 3600, 2) for k, v in t["human_s"].items()},
            "typed_loc": t["loc"],
            "delivered": tot_delivered,
            "gross_added": tot_gross,
            "churn": round(tot_gross / sum(tot_delivered.values()), 2)
                     if sum(tot_delivered.values()) > 0 else None,
            "commits": tot_commits,
            "files_delivered": tot_files,
            "counts": t["counts"],
        },
        "months": [
            {
                "month": m["month"],
                "active_h": round(hours(m["phase_s"]), 2),
                "human_h": round(hours(m["human_s"]), 2),
                "groups_h": {k: round(v, 2) for k, v in group_hours(m["phase_s"]).items()},
                "sessions": m["counts"]["sessions"],
                "test_runs": m["counts"]["test_runs"],
                "typed_loc": m["loc"],
            }
            for m in data["months"]
        ],
        "projects": projects,
        "fits": {
            "test_share_vs_maturity": test_share_fit,
            "feature_share_vs_maturity": feature_share_fit,
            "throughput_vs_maturity": throughput_fit,
            "min_hours_for_fit": MIN_HOURS_FOR_FIT,
        },
    }

    Path(args.out).write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")

    print(f"wrote {args.out}")
    print(f"  projects: {len(projects)}  (in fit: {len(fitset)})")
    print(f"  active {tot_act:.1f}h  human {tot_hum:.1f}h")
    print(f"  delivered lines: {tot_delivered}")
    print(f"  test_share  = {test_share_fit['a']:.2f} + {test_share_fit['b']:.3f}*maturity"
          f"   r2={test_share_fit['r2']}  n={test_share_fit['n']}")
    print(f"  feat_share  = {feature_share_fit['a']:.2f} + {feature_share_fit['b']:.3f}*maturity"
          f"   r2={feature_share_fit['r2']}  n={feature_share_fit['n']}")
    print(f"  lines/hour  = {throughput_fit['a']:.1f} + {throughput_fit['b']:.2f}*maturity"
          f"   r2={throughput_fit['r2']}  n={throughput_fit['n']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
