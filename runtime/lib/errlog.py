"""Structured incident logging for the Argus runtime.

This is deliberately separate from the SQLite journal in argusd.py. The
journal is a conversation/audit trail — it gets compacted, it mixes normal
turns with failures, and it never stores a traceback. This is a small,
append-only, never-compacted log purpose-built for one question: when a task
goes wrong, what broke, where, and with what context?

Every record is one JSON line (so it's greppable and diffable) with at least
`ts`, `level` and `event`; callers add whatever fields matter for that event
(session, step, tool, duration, args_summary, ...). `exception()` also
captures the full traceback, which `str(e)` alone throws away.

Written to `$XDG_DATA_HOME/argus/argus.log` (same data root argusd.py uses),
rotated at 5MB x 3 backups so a runaway loop can't fill the disk.
"""

import json
import logging
import logging.handlers
import os
import time
import traceback
from pathlib import Path

_DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "argus"
LOG_FILE = _DATA / "argus.log"

_logger = None


def _get_logger():
    global _logger
    if _logger is not None:
        return _logger
    _DATA.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("argus.incidents")
    logger.setLevel(logging.DEBUG)
    # Avoid duplicate handlers if a module is re-imported (tests do this a lot).
    if not any(
        isinstance(h, logging.handlers.RotatingFileHandler)
        and getattr(h, "baseFilename", None) == str(LOG_FILE)
        for h in logger.handlers
    ):
        handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.propagate = False
    _logger = logger
    return logger


def _write(level, event, fields):
    rec = {"ts": round(time.time(), 3), "level": level, "event": event}
    rec.update(fields)
    try:
        line = json.dumps(rec, default=str, ensure_ascii=False)
    except Exception:
        line = json.dumps(
            {
                "ts": rec["ts"],
                "level": level,
                "event": event,
                "error": "record was not JSON-serializable",
            }
        )
    _get_logger().log(getattr(logging, level), line)


def info(event, **fields):
    _write("INFO", event, fields)


def warning(event, **fields):
    _write("WARNING", event, fields)


def error(event, **fields):
    _write("ERROR", event, fields)


def exception(event, exc, **fields):
    """Log an exception with its full traceback plus arbitrary context.

    Use this at the point an `except` clause actually has the exception in
    hand — `str(e)` alone (what argusd.py's tool-call and provider-call
    handlers fall back to for the user-facing message) drops the traceback,
    which is usually the only thing that makes a crash reproducible.
    """
    _write(
        "ERROR",
        event,
        {
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            **fields,
        },
    )


def tail(n=50):
    """The last `n` log records, newest last. Malformed lines are returned
    as {"raw": line} rather than dropped, so a partial/corrupted write from a
    killed process doesn't hide the records around it."""
    if not LOG_FILE.exists():
        return []
    lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            out.append({"raw": line})
    return out
