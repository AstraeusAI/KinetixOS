#!/usr/bin/env python3
"""Argus execution runtime.

A real agent loop: journaled, sandboxed, policy-gated, with a coding tool
surface (files, search, exec, LSP) alongside computer use.

Architecture
------------
  journal (SQLite)      every turn, tool call, result, approval, checkpoint
  workspace             one declared project root, plus the whole user home
                        directory; all paths validated against that union
  policy                auto / prompt / deny per capability, with saved rules
  sandbox               bwrap isolation + cgroup limits for executed commands
  tool registry         tools as data (lib/tools.py) — policy, checkpoints and
                        verification are inherited, not re-implemented
  verify pipeline       after any write: syntax check, then lint if available
  providers             OpenAI / Anthropic / OpenRouter / OpenCode / Codex,
                        key or subscription auth, one neutral message format

Streaming: with --stream the runtime emits NDJSON — {"type":"event",...} as
work happens and a final {"type":"result",...} envelope — so the shell can show
progress instead of waiting for the whole task.

NOTE: the SQLite journal is plaintext at rest; `doctor` reports this.

Compatibility facade: implementation lives in lib/* — this module only
re-binds the historical ``argusd.<name>`` surface that tests, tools and
shells patch and call. Exports use plain assignments (not ``from-import``
alone) so a stray ``ruff --fix F401`` can never strip them again.
"""

import sys
import time as _time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import approvals as _approvals
from lib import cli as _cli
from lib import config as _cfg
from lib import errlog as _errlog
from lib import journal as _journal
from lib import kwin as _kwin
from lib import loop as _loop
from lib import out as _out
from lib import policy as _policy
from lib import prompt as _prompt
from lib import render as _render
from lib import sandbox as _sandbox
from lib import checkpoints as _checkpoints
from lib import tools as _tools
from lib import workspace as _workspace
from lib.providers import adapters as _adapters
from lib.providers import anthropic as _anthropic_stream
from lib.providers import codex as _codex_stream
from lib.providers import openai_chat as _openai_chat
from lib.providers import service as _service
from lib.providers import sse as _sse

# --- stdlib / lib modules (tests patch attributes on these objects) -------
time = _time
kwin = _kwin
sandbox = _sandbox
errlog = _errlog
toolreg = _tools

# --- config ----------------------------------------------------------------
prefs = _cfg.prefs
vault = _cfg.vault
auth_mode = _cfg.auth_mode
MAX_TASK_SECONDS = _cfg.MAX_TASK_SECONDS
MAX_STEPS = _cfg.MAX_STEPS
MAX_STREAM_TRUNCATIONS = _cfg.MAX_STREAM_TRUNCATIONS
_MAX_STREAM_TRUNCATIONS = _cfg.MAX_STREAM_TRUNCATIONS  # historical alias
HTTP_TIMEOUT = _cfg.HTTP_TIMEOUT

# --- prompt ----------------------------------------------------------------
SYSTEM_PROMPT = _prompt.SYSTEM_PROMPT
CLAUDE_IDENTITY = _prompt.CLAUDE_IDENTITY

# --- journal ---------------------------------------------------------------
connect = _journal.connect
event = _journal.event
set_state = _journal.set_state
get_state = _journal.get_state
add_memory = _journal.add_memory
delete_memory = _journal.delete_memory
list_memories = _journal.list_memories
compact = _journal.compact
context = _journal.context
list_sessions = _journal.list_sessions
session_transcript = _journal.session_transcript
extract_memory = _journal.extract_memory
_drop_orphan_tool_results = _journal._drop_orphan_tool_results
abandon_calls = _journal.abandon_calls
grants = _journal.grants
now = _journal.now
_safe_window_start = _journal._safe_window_start
_IMAGE_CACHE = _journal._IMAGE_CACHE
image_payload = _journal.image_payload
KEEP_EVENTS = _journal.KEEP_EVENTS
SUMMARY_CHARS = _journal.SUMMARY_CHARS
MAX_CONTEXT_CHARS = _journal.MAX_CONTEXT_CHARS
MAX_CONTEXT_EVENTS = _journal.MAX_CONTEXT_EVENTS
MAX_IMAGES = _journal.MAX_IMAGES
tool_result_text = _render.tool_result_text
journal_approval_outcome = _journal.journal_approval_outcome

# --- loop / approvals / render --------------------------------------------
run = _loop.run
Context = _loop.Context
policy_decision = _loop.policy_decision
verify = _loop.verify
_clean_workspace_caches = _loop._clean_workspace_caches
approve = _approvals.approve
tool_detail = _render.tool_detail

# --- providers -------------------------------------------------------------
provider_call = _service.provider_call
ProviderError = _sse.ProviderError
_post_stream = _sse._post_stream
_sse_iter = _sse._sse_iter
_call_stream = _sse._call_stream
_MAX_PROVIDER_RETRIES = _sse._MAX_PROVIDER_RETRIES
_RETRYABLE_HTTP = _sse._RETRYABLE_HTTP
_clean_http_detail = _sse._clean_http_detail
_stream_openai_chat = _openai_chat._stream_openai_chat
_stream_anthropic = _anthropic_stream._stream_anthropic
_stream_codex = _codex_stream._stream_codex
to_openai = _adapters.to_openai
to_anthropic = _adapters.to_anthropic
anthropic_system_blocks = _adapters.anthropic_system_blocks
cached_tools = _adapters.cached_tools
to_codex = _adapters.to_codex
TOOLS = _adapters.TOOLS

# --- policy / checkpoints / workspace classes ------------------------------
Policy = _policy.Policy
Checkpoints = _checkpoints.Checkpoints
Workspace = _workspace.Workspace

# --- output ----------------------------------------------------------------
emit = _out.emit

# --- CLI -------------------------------------------------------------------
main = _cli.main
doctor = _cli.doctor


if __name__ == "__main__":
    if sys.argv[1:2] == ["worker"]:
        # pre-started daemon worker (see lib/daemon.py worker_main)
        from lib import daemon as _daemon

        sys.exit(_daemon.worker_main(main))
    main()
