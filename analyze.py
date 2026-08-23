"""Measure where Claude Code time actually goes: feature work vs tests.

Reads every session transcript under ~/.claude/projects, rebuilds each session
as an ordered event stream, and attributes the wall-clock gap between
consecutive events to a work phase (feature, test authoring, test execution,
verification, exploration) or to human turnaround (review / manual testing).

Emits a single JSON document consumed by build_report.py.

Usage:
    python analyze.py [--projects-dir DIR] [--out data.json] [--jobs N]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from classify import classify_prompt, classify_tool

# --------------------------------------------------------------------------
# Attribution tuning
# --------------------------------------------------------------------------

# A gap longer than this between two machine events is not work -- the user
# walked away mid-turn, or the transcript has a hole in it.
ACTIVE_CAP_S = 240.0
# Test runs and builds legitimately block for minutes; give them more rope.
SLOW_CAP_S = 900.0
SLOW_PHASES = {"test_run", "verify", "run_app"}
# Human turnaround: reading the diff, testing by hand, deciding what is next.
# Anything longer is a break between work sessions, not measured effort.
HUMAN_CAP_S = 1200.0
# Any gap above this splits the session into separate work blocks.
SESSION_BREAK_S = 2700.0

PHASES = [
    "feature", "test_write", "test_run", "verify", "run_app",
    "explore", "docs_write", "config_write", "planning", "vcs", "other",
]
HUMAN_KINDS = ["manual_test", "review", "direction"]

_SKIP_PREFIXES = (
    '{"type":"last-prompt"',
    '{"type":"ai-title"',
    '{"type":"file-history-delta"',
    '{"type":"file-history-snapshot"',
    '{"type":"queue-operation"',
    '{"type":"attachment"',
    '{"type":"summary"',
    '{"type":"system"',
)


def _parse_ts(raw: str) -> float | None:
    if not raw:
        return None
    try:
        # Timestamps are ISO-8601 with a trailing Z.
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _count_lines(text) -> int:
    if not isinstance(text, str) or not text:
        return 0
    return text.count("\n") + 1


def _blank_bucket() -> dict:
    return {
        "phase_s": {p: 0.0 for p in PHASES},
        "phase_calls": {p: 0 for p in PHASES},
        "human_s": {k: 0.0 for k in HUMAN_KINDS},
        # Wall-clock that was deliberately NOT counted, so the report can show
        # how much of the raw span was discarded rather than hiding it.
        "audit_s": {
            "span": 0.0,        # first to last event of the session
            "capped_out": 0.0,  # gap time above the per-event caps
            "breaks": 0.0,      # gaps long enough to be a break, dropped whole
        },
        "loc": {
            "feature_added": 0, "feature_touched": 0,
            "test_added": 0, "test_touched": 0,
            "docs_added": 0, "config_added": 0,
        },
        "counts": {
            "sessions": 0, "prompts": 0, "tool_uses": 0,
            "test_runs": 0, "verifies": 0, "edits": 0, "writes": 0,
            "subagents": 0, "work_blocks": 0,
        },
    }


def _merge(dst: dict, src: dict) -> None:
    for group in ("phase_s", "phase_calls", "human_s", "audit_s", "loc", "counts"):
        for k, v in src[group].items():
            dst[group][k] = dst[group].get(k, 0) + v


# --------------------------------------------------------------------------
# Per-file parsing
# --------------------------------------------------------------------------

def parse_session(path: str) -> dict | None:
    """Extract an ordered event stream from one transcript file."""
    events = []          # (ts, kind, phase, payload)
    loc = defaultdict(int)
    counts = defaultdict(int)
    cwd = None
    version = None
    tool_phase = {}      # tool_use_id -> phase, so a tool_result inherits it

    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return None

    with fh:
        for line in fh:
            if not line or line[0] != "{":
                continue
            if line.startswith(_SKIP_PREFIXES):
                continue
            try:
                ev = json.loads(line)
            except (ValueError, RecursionError):
                continue

            etype = ev.get("type")
            if etype not in ("assistant", "user"):
                continue
            ts = _parse_ts(ev.get("timestamp"))
            if ts is None:
                continue
            if cwd is None:
                cwd = ev.get("cwd")
            if version is None:
                version = ev.get("version")

            sidechain = bool(ev.get("isSidechain"))
            msg = ev.get("message") or {}
            content = msg.get("content")

            if etype == "assistant":
                blocks = content if isinstance(content, list) else []
                emitted = False
                for b in blocks:
                    if not isinstance(b, dict):
                        continue
                    btype = b.get("type")
                    if btype == "tool_use":
                        name = b.get("name") or ""
                        tin = b.get("input") if isinstance(b.get("input"), dict) else {}
                        phase = classify_tool(name, tin)
                        counts["tool_uses"] += 1
                        if phase == "test_run":
                            counts["test_runs"] += 1
                        elif phase == "verify":
                            counts["verifies"] += 1
                        if name in ("Task", "Agent", "Explore"):
                            counts["subagents"] += 1

                        # Line accounting for write-type tools.
                        if name in ("Write", "Update"):
                            counts["writes"] += 1
                            n = _count_lines(tin.get("content"))
                            kind = phase
                            if kind == "feature":
                                loc["feature_added"] += n
                                loc["feature_touched"] += n
                            elif kind == "test_write":
                                loc["test_added"] += n
                                loc["test_touched"] += n
                            elif kind == "docs_write":
                                loc["docs_added"] += n
                            elif kind == "config_write":
                                loc["config_added"] += n
                        elif name in ("Edit", "MultiEdit", "NotebookEdit"):
                            counts["edits"] += 1
                            new_n = _count_lines(tin.get("new_string") or tin.get("new_source"))
                            old_n = _count_lines(tin.get("old_string") or tin.get("old_source"))
                            net = max(0, new_n - old_n)
                            touched = max(new_n, old_n)
                            if phase == "feature":
                                loc["feature_added"] += net
                                loc["feature_touched"] += touched
                            elif phase == "test_write":
                                loc["test_added"] += net
                                loc["test_touched"] += touched
                            elif phase == "docs_write":
                                loc["docs_added"] += net
                            elif phase == "config_write":
                                loc["config_added"] += net

                        events.append((ts, "tool", phase, sidechain))
                        tool_phase[b.get("id")] = phase
                        emitted = True
                    elif btype in ("text", "thinking"):
                        if not emitted:
                            events.append((ts, "text", None, sidechain))
                            emitted = True
                if not blocks:
                    events.append((ts, "text", None, sidechain))
                continue

            # etype == "user"
            if isinstance(content, list):
                types = {b.get("type") for b in content if isinstance(b, dict)}
                if "tool_result" in types:
                    phase = None
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            phase = tool_phase.get(b.get("tool_use_id"))
                            break
                    events.append((ts, "result", phase, sidechain))
                    continue
                has_image = "image" in types
                text = " ".join(
                    b.get("text") or "" for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            elif isinstance(content, str):
                has_image = False
                text = content
            else:
                continue

            # Slash-command scaffolding and system reminders are not the human
            # typing a fresh instruction, but they do mark a turn boundary.
            counts["prompts"] += 1
            events.append((ts, "prompt", classify_prompt(text, has_image), sidechain))

    if not events:
        return None

    events.sort(key=lambda e: e[0])
    return {
        "path": path,
        "cwd": cwd,
        "version": version,
        "events": events,
        "loc": dict(loc),
        "counts": dict(counts),
    }


def attribute(session: dict) -> dict:
    """Turn an event stream into seconds per phase."""
    events = session["events"]
    phase_s = defaultdict(float)
    phase_calls = defaultdict(int)
    human_s = defaultdict(float)
    capped_out = 0.0
    breaks = 0.0
    work_blocks = 1
    context = "explore"     # what Claude is currently working on
    pending_prompt = None   # index of a prompt awaiting a lookahead phase

    # Pre-compute, for each index, the phase of the next categorizable tool.
    next_tool_phase = [None] * len(events)
    nxt = None
    for i in range(len(events) - 1, -1, -1):
        if events[i][1] == "tool" and events[i][2]:
            nxt = events[i][2]
        next_tool_phase[i] = nxt

    for i in range(len(events) - 1):
        ts, kind, phase, _side = events[i]
        if kind == "tool" and phase:
            phase_calls[phase] += 1
        gap = events[i + 1][0] - ts
        if gap <= 0:
            continue
        if gap > SESSION_BREAK_S:
            work_blocks += 1
            breaks += gap
            continue

        nkind = events[i + 1][1]

        if kind == "prompt":
            # Time from the human's instruction until Claude's first action
            # belongs to whatever Claude then went and did.
            target = next_tool_phase[i] or "explore"
            billed = min(gap, ACTIVE_CAP_S)
            phase_s[target] += billed
            capped_out += gap - billed
            context = target
            continue

        if kind == "tool":
            target = phase or context
            cap = SLOW_CAP_S if target in SLOW_PHASES else ACTIVE_CAP_S
            billed = min(gap, cap)
            phase_s[target] += billed
            capped_out += gap - billed
            context = target
            continue

        if kind == "result":
            target = phase or context
            billed = min(gap, ACTIVE_CAP_S)
            phase_s[target] += billed
            capped_out += gap - billed
            if phase:
                context = phase
            continue

        # kind == "text"
        if nkind == "prompt":
            # Claude stopped and is waiting on the human: review + hands-on
            # testing time. Attributed to what the human's reply reveals.
            hkind = events[i + 1][2] or "direction"
            billed = min(gap, HUMAN_CAP_S)
            human_s[hkind] += billed
            capped_out += gap - billed
        else:
            target = next_tool_phase[i] or context
            billed = min(gap, ACTIVE_CAP_S)
            phase_s[target] += billed
            capped_out += gap - billed
            context = target

    # The final event has no successor, so count its tool call too.
    if events and events[-1][1] == "tool" and events[-1][2]:
        phase_calls[events[-1][2]] += 1

    return {
        "phase_s": {p: phase_s.get(p, 0.0) for p in PHASES},
        "phase_calls": {p: phase_calls.get(p, 0) for p in PHASES},
        "human_s": {k: human_s.get(k, 0.0) for k in HUMAN_KINDS},
        "audit_s": {
            "span": events[-1][0] - events[0][0] if len(events) > 1 else 0.0,
            "capped_out": capped_out,
            "breaks": breaks,
        },
        "work_blocks": work_blocks,
    }


def process_file(path: str) -> dict | None:
    s = parse_session(path)
    if not s:
        return None
    attr = attribute(s)
    counts = s["counts"]
    counts["sessions"] = 1
    counts["work_blocks"] = attr["work_blocks"]
    loc = s["loc"]
    blank = _blank_bucket()
    for k in blank["loc"]:
        blank["loc"][k] = loc.get(k, 0)
    for k, v in counts.items():
        blank["counts"][k] = blank["counts"].get(k, 0) + v
    blank["phase_s"] = attr["phase_s"]
    blank["phase_calls"] = attr["phase_calls"]
    blank["human_s"] = attr["human_s"]
    blank["audit_s"] = attr["audit_s"]

    events = s["events"]
    return {
        "bucket": blank,
        "cwd": s["cwd"],
        "version": s["version"],
        "start": events[0][0],
        "end": events[-1][0],
        "session_id": Path(path).stem,
        "project_dir": Path(path).parent.name,
    }


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------

def month_key(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--projects-dir",
                    default=str(Path.home() / ".claude" / "projects"))
    ap.add_argument("--out", default="data.json")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    args = ap.parse_args()

    root = Path(args.projects_dir)
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 1

    # One level deep only: <project>/<session>.jsonl. Deeper paths hold subagent
    # and workflow transcripts (<project>/<session>/subagents/...). Those are
    # deliberately skipped -- the parent session is already accruing wall-clock
    # while a subagent runs, so parsing both would count that time twice.
    # Measured separately it is ~1.9% of active work; see README limitations.
    files = sorted(str(p) for p in root.glob("*/*.jsonl"))
    total_mb = sum(os.path.getsize(f) for f in files) / 1e6
    print(f"parsing {len(files)} transcripts ({total_mb:.0f} MB) "
          f"with {args.jobs} workers...", file=sys.stderr)

    results = []
    if args.jobs > 1:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            for i, r in enumerate(pool.map(process_file, files, chunksize=4), 1):
                if r:
                    results.append(r)
                if i % 100 == 0:
                    print(f"  {i}/{len(files)}", file=sys.stderr)
    else:
        for i, f in enumerate(files, 1):
            r = process_file(f)
            if r:
                results.append(r)
            if i % 100 == 0:
                print(f"  {i}/{len(files)}", file=sys.stderr)

    if not results:
        print("no usable transcripts found", file=sys.stderr)
        return 1

    totals = _blank_bucket()
    projects: dict[str, dict] = {}
    months: dict[str, dict] = {}
    sessions = []

    for r in results:
        b = r["bucket"]
        _merge(totals, b)

        pname = r["project_dir"]
        proj = projects.setdefault(pname, {
            **_blank_bucket(),
            "name": pname,
            "cwd": r["cwd"],
            "start": r["start"],
            "end": r["end"],
        })
        _merge(proj, b)
        if r["cwd"] and not proj.get("cwd"):
            proj["cwd"] = r["cwd"]
        proj["start"] = min(proj["start"], r["start"])
        proj["end"] = max(proj["end"], r["end"])

        mk = month_key(r["start"])
        mo = months.setdefault(mk, {**_blank_bucket(), "month": mk})
        _merge(mo, b)

        active = sum(b["phase_s"].values())
        sessions.append({
            "id": r["session_id"],
            "project": pname,
            "start": r["start"],
            "end": r["end"],
            "active_s": round(active, 1),
            "human_s": round(sum(b["human_s"].values()), 1),
            "phase_s": {k: round(v, 1) for k, v in b["phase_s"].items() if v > 0},
            "loc": {k: v for k, v in b["loc"].items() if v},
            "test_runs": b["counts"]["test_runs"],
        })

        # Per-project monthly detail, for the maturity view.
        pm = proj.setdefault("months", {})
        pmo = pm.setdefault(mk, _blank_bucket())
        _merge(pmo, b)

    def _round(bucket: dict) -> dict:
        return {
            "phase_s": {k: round(v, 1) for k, v in bucket["phase_s"].items()},
            "phase_calls": dict(bucket["phase_calls"]),
            "human_s": {k: round(v, 1) for k, v in bucket["human_s"].items()},
            "audit_s": {k: round(v, 1) for k, v in bucket["audit_s"].items()},
            "loc": dict(bucket["loc"]),
            "counts": dict(bucket["counts"]),
        }

    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "attribution": {
            "active_cap_s": ACTIVE_CAP_S,
            "slow_cap_s": SLOW_CAP_S,
            "human_cap_s": HUMAN_CAP_S,
            "session_break_s": SESSION_BREAK_S,
        },
        "totals": _round(totals),
        "projects": [
            {
                "name": p["name"],
                "cwd": p.get("cwd"),
                "start": p["start"],
                "end": p["end"],
                **_round(p),
                "months": {mk: _round(mv) for mk, mv in sorted(p.get("months", {}).items())},
            }
            for p in sorted(projects.values(),
                            key=lambda x: -sum(x["phase_s"].values()))
        ],
        "months": [
            {"month": mk, **_round(mv)} for mk, mv in sorted(months.items())
        ],
        "sessions": sorted(sessions, key=lambda s: s["start"]),
    }

    out = Path(args.out)
    out.write_text(json.dumps(doc, indent=1), encoding="utf-8")

    act = sum(totals["phase_s"].values())
    hum = sum(totals["human_s"].values())
    print(f"\nwrote {out} -- {len(results)} sessions, "
          f"{act/3600:.1f}h Claude-active, {hum/3600:.1f}h human turnaround",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
