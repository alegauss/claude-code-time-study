"""Record the boundaries of each Claude Code work cycle, to measure human time.

Transcripts show when a turn ended and when the next instruction arrived, but a
gap in that record is ambiguous: it could be careful manual testing or a lunch
break, and retrospective analysis has to guess with a cap. This hook removes the
guess by stamping the boundaries as they happen, with the session and project
attached.

Install as a Stop hook (fires when Claude finishes a turn) and a
UserPromptSubmit hook (fires when the developer sends the next instruction):

    python hooks/cycle_stamp.py stop
    python hooks/cycle_stamp.py resume

Both read the hook payload from stdin and append one line to
~/.claude/dev-time-cycles.jsonl. The hook never blocks the tool: any failure is
swallowed and exit is always 0, because losing a measurement is always better
than interrupting the developer.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG = Path.home() / ".claude" / "dev-time-cycles.jsonl"


def main() -> int:
    kind = sys.argv[1] if len(sys.argv) > 1 else "unknown"

    payload = {}
    try:
        # Some shells prepend a UTF-8 BOM when piping; json rejects it.
        raw = sys.stdin.read().lstrip("﻿").strip()
        if raw:
            payload = json.loads(raw)
    except (ValueError, OSError):
        payload = {}

    record = {
        "event": kind,
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": payload.get("session_id"),
        "cwd": payload.get("cwd") or os.getcwd(),
    }

    # UserPromptSubmit carries the instruction. Its text is not stored -- only
    # its length and a coarse hint of whether it reports hands-on testing, so
    # the log stays free of source code and prose.
    prompt = payload.get("prompt")
    if isinstance(prompt, str):
        low = prompt.lower()
        record["prompt_chars"] = len(prompt)
        record["mentions_testing"] = any(
            w in low for w in (
                "test", "tested", "testei", "testando", "funcionou", "error",
                "erro", "broken", "quebrou", "screenshot", "print",
            )
        )

    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # A measurement hook must never break the session it is measuring.
        sys.exit(0)
