"""Neutral NDJSON emitter, shared by loop, approvals and cli."""

import json


def emit(obj, stream=False):
    """Emit one NDJSON line. In stream mode events are tagged so the shell can
    distinguish progress from the final result."""
    print(json.dumps(obj, ensure_ascii=False), flush=True)
