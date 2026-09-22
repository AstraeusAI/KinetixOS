pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// The agent runtime bridge. Tasks go through argusd, which owns durable
// memory, provider calls, tool policy, and the perceive → act → verify loop.
// See docs/03-agent-runtime.md.
QtObject {
    property var actions: []
    property var pendingApproval: null
    property bool busy: false
    property string lastError: ""
    property string activeRequestId: ""
    property string pendingSocketRequest: ""
    property string directFallbackCommand: ""
    property bool socketRetryPending: false
    readonly property string runtimeSocketPath:
        (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/argus/argusd.sock"

    signal actionLogged(var entry)
    signal approvalRaised(var approval)

    function ts() { return new Date().toLocaleTimeString([], "hh:mm:ss"); }

    function logAction(kind, summary, status) {
        var e = { "kind": kind, "summary": summary,
                  "status": status || "ok", "ts": ts() };
        var a = actions.slice();
        a.push(e);
        // Capped: a long task emits several events per step, and this array
        // both lives in memory for the whole shell session and re-renders
        // the timeline on every append. The newest window is the useful one.
        if (a.length > 300) a = a.slice(a.length - 300);
        actions = a;
        actionLogged(e);
    }

    function clearActions() {
        actions = [];
    }

    function send(text) {
        if (busy) return;
        var t = text.trim();
        if (t === "") return;
        // A new task supersedes an unanswered approval: leaving the banner up
        // over a different task invites approving an action the user has
        // stopped reading, and resolveApproval would otherwise interleave the
        // old action's runner with this task's turn.
        if (pendingApproval) {
            logAction("commit", "Approval superseded by a new task", "blocked");
            pendingApproval = null;
            if (AgentState.status === "blocked") AgentState.status = "idle";
        }
        busy = true;
        lastError = "";
        sawResult = false;      // reset per run, or a later failure is never reported
        noteActivity();
        runStartedAt = Date.now();
        AgentState.status = "working";
        AgentState.agentActive = true;
        AgentState.pushMessage("user", t);

        logAction("perceive", "Runtime collecting task context", "ok");
        logAction("plan", "Routing to " + ProviderConfig.provider + "/" + ProviderConfig.model, "ok");

        activeRequestId = "r-" + Date.now();
        directFallbackCommand = buildRuntime(t);
        startSocketRequest({ "op": "run", "id": activeRequestId, "task": t,
                             "session": AgentState.sessionId,
                             "workspace": ProviderConfig.workspace,
                             "grants": currentGrants() });
    }

    function currentGrants() {
        return { "screen": ProviderConfig.grantScreen,
                 "input": AgentState.computerUse && ProviderConfig.grantInput,
                 "shell": ProviderConfig.grantShell,
                 "net": ProviderConfig.grantNet };
    }

    function startSocketRequest(request) {
        pendingSocketRequest = JSON.stringify(request) + "\n";
        socketRetryPending = true;
        daemonSocket.connected = true;
    }

    function cancelActiveRequest() {
        if (activeRequestId === "") return;
        cancelSocket.requestId = activeRequestId;
        cancelSocket.connected = true;
        daemonSocket.connected = false;
        activeRequestId = "";
    }

    // ── runner watchdog ──────────────────────────────────────────────────
    // finishRun() only fires on process exit; a runtime that hangs (blocked
    // subprocess under the sandbox, wedged provider connection) would leave
    // busy=true forever — the feed silent, the composer dead. Two guards:
    // no output of any kind for 3 minutes while busy, or a single run
    // outliving the runtime's own MAX_TASK_SECONDS budget by a wide margin.
    // Any ingestLine()/metrics delta resets the stall clock, so a healthy
    // long-running task is never killed.
    property real lastActivity: 0
    property real runStartedAt: 0

    function noteActivity() { lastActivity = Date.now(); }

    readonly property int stallMs: 180000      // 3 min without a single line
    readonly property int maxRunMs: 2100000    // 35 min, above the runtime's 30 min cap

    property Timer socketRetryTimer: Timer {
        interval: 300
        repeat: false
        onTriggered: ArgusBridge.daemonSocket.connected = true
    }

    property Timer watchdogTimer: Timer {
        interval: 10000
        running: true
        repeat: true
        onTriggered: {
            if (!ArgusBridge.busy || ArgusBridge.lastActivity === 0) return;
            var now = Date.now();
            var stalled = now - ArgusBridge.lastActivity > ArgusBridge.stallMs;
            var overran = now - ArgusBridge.runStartedAt > ArgusBridge.maxRunMs;
            if (!stalled && !overran) return;
            ArgusBridge.cancelActiveRequest();
            ArgusBridge.runner.running = false;
            ArgusBridge.busy = false;
            AgentState.status = "idle";
            AgentState.agentActive = false;
            AgentState.abortAgentTurn();
            AgentState.pushMessage("agent", "⚠️ Runtime watchdog: task cancelled after "
                                   + (stalled ? "3 minutes with no output" : "15 minutes total")
                                   + ". Retry when ready.");
            ArgusBridge.logAction("act", "Watchdog killed the runtime ("
                                  + (stalled ? "stall" : "overrun") + ")", "blocked");
        }
    }

    // Keep task text out of shell syntax. The runtime receives it as one
    // single-quoted argument; its own SQLite journal is the source of truth.
    function buildRuntime(task) {
        var esc = String(task).replace(/'/g, "'\\''");
        var sid = String(AgentState.sessionId).replace(/'/g, "'\\''");
        var ws = String(ProviderConfig.workspace).replace(/'/g, "'\\''");
        // shellDir is the configured `shell/` directory, including after hot
        // reload. Deriving from it avoids a component-relative URL becoming a
        // qrc/cache location and leaving the runtime with no stdout.
        var script = Quickshell.shellDir + "/../runtime/argusd.py";
        // `exec` matters: Quickshell stops a Process with SIGTERM to its direct
        // child, so without it Stop/panic/watchdog would signal the `sh` wrapper
        // and leave the python runtime (and anything it is doing to the desktop)
        // running after the UI says it stopped.
        return "ARGUS_GRANT_SCREEN=" + (ProviderConfig.grantScreen ? "1" : "0") +
               " ARGUS_GRANT_INPUT=" + ((AgentState.computerUse && ProviderConfig.grantInput) ? "1" : "0") +
               " ARGUS_GRANT_SHELL=" + (ProviderConfig.grantShell ? "1" : "0") +
               " ARGUS_GRANT_NET=" + (ProviderConfig.grantNet ? "1" : "0") +
               " PYTHONUNBUFFERED=1 exec python3 -u '" + script + "' run --stream" +
               " --workspace '" + ws + "'" +
               " --session '" + sid + "' --task '" + esc + "'";
    }

    // Answers a Responses object (the Codex subscription probe) by pulling its
    // output_text. parseTest() calls this as codexText(); it used to be a
    // second, dead `buildTest` that read an undefined `j` and was shadowed by
    // the real one below — so the call raised a ReferenceError that parseTest's
    // own catch swallowed, and a working ChatGPT subscription was always
    // reported as "Unparseable".
    function codexText(j) {
        if (!j || !j.output) return "";
        var out = "";
        for (var i = 0; i < j.output.length; i++) {
            var item = j.output[i];
            if (item && item.type === "message" && item.content) {
                for (var k = 0; k < item.content.length; k++) {
                    var c = item.content[k];
                    if (c && (c.type === "output_text" || c.type === "text") && c.text)
                        out += c.text;
                }
            }
        }
        return out;
    }

    // Keys are injected by sourcing the 0600 vault file first, so `$VAR`
    // resolves from saved keys (environment as fallback) without the secret
    // ever appearing in the process command line.
    readonly property string keyPrelude: '. "' + ProviderConfig.keysPath + '" 2>/dev/null; ';

    // ── connection test (GET /v1/models) ──
    property bool testing: false
    property string testTarget: ""
    property string testResult: ""
    signal testFinished(var ok, var text)

    function buildTest(p) {
        var sub = ProviderConfig.isSub(p.key);
        var headers, url, body = null;
        if (p.kind === "anthropic" && !sub) {
            url = p.baseUrl + "/v1/models?limit=1";
            headers = '-H "x-api-key: $' + p.envKey + '" -H "anthropic-version: 2023-06-01"';
        } else if (p.kind === "anthropic" && sub) {
            url = p.baseUrl + "/v1/models?limit=1";
            headers = '-H "Authorization: Bearer $' + p.subTokenVar + '"' +
                      ' -H "anthropic-version: 2023-06-01"' +
                      ' -H "anthropic-beta: oauth-2025-04-20,claude-code-20250219"';
        } else if (p.key === "openai" && sub) {
            // Codex backend has no model catalog: send a minimal probe instead.
            url = "https://chatgpt.com/backend-api/codex/responses";
            headers = '-H "Authorization: Bearer $' + p.subTokenVar + '"';
            if (ProviderConfig.hasKey(p.subAccountVar))
                headers += ' -H "ChatGPT-Account-Id: $' + p.subAccountVar + '"';
            body = JSON.stringify({ model: ProviderConfig.model, store: false,
                                    max_output_tokens: 8,
                                    instructions: "Reply with exactly: ok",
                                    input: [{ role: "user", content: "ok?" }] });
        } else {
            url = p.baseUrl + "/v1/models";
            headers = '-H "Authorization: Bearer $' + p.envKey + '"';
            if (p.key === "openrouter")
                headers += " -H 'HTTP-Referer: https://argus.os' -H 'X-Title: Argus OS'";
        }
        var cmd = keyPrelude + "curl -s --max-time 20 " + headers;
        if (body !== null) {
            var esc = body.replace(/'/g, "'\\''");
            cmd += " -H 'content-type: application/json' -d '" + esc + "'";
        }
        return cmd + " " + url;
    }

    function testConnection(key) {
        var k = key || ProviderConfig.provider;
        if (testing) return;
        testing = true;
        testTarget = k;
        testResult = "";
        tester.command = ["sh", "-c", buildTest(ProviderConfig.byKey(k))];
        tester.running = true;
    }

    function parseTest(text) {
        if (text === "")
            return { "ok": false, "text": "No response — network down or wrong endpoint?" };
        try {
            var j = JSON.parse(text);
            if (j.error) {
                var m = j.error.message || JSON.stringify(j.error);
                return { "ok": false, "text": "Rejected: " + String(m).slice(0, 140) };
            }
            // Codex probe answers with a Responses object
            var ct = codexText(j);
            if (ct !== "") return { "ok": true, "text": "Subscription live · answered probe" };
            if (j.data && j.data.length !== undefined)
                return { "ok": true, "text": "Connected · " + j.data.length + " model(s)" };
            return { "ok": false, "text": "Unexpected reply" };
        } catch (e) {
            return { "ok": false, "text": "Unparseable: " + text.slice(0, 120) };
        }
    }

    property Process tester: Process {
        stdout: StdioCollector {
            onStreamFinished: {
                var r = ArgusBridge.parseTest(this.text);
                ArgusBridge.testing = false;
                ArgusBridge.testResult = r.text;
                ArgusBridge.testFinished(r.ok, r.text);
                ArgusBridge.logAction("verify",
                    "Key test " + ArgusBridge.testTarget + ": " + r.text,
                    r.ok ? "ok" : "blocked");
            }
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (ArgusBridge.testing && this.text.trim() !== "")
                    ArgusBridge.lastError = this.text.slice(0, 200);
            }
        }
    }

    // ── live model catalog (GET /v1/models → ProviderConfig.live) ──
    property bool modelsLoading: false
    property string modelsTarget: ""
    property string modelsError: ""
    signal modelsFinished(var key, var ok, var count)

    function buildModels(p) {
        var sub = ProviderConfig.isSub(p.key);
        var headers, url;
        if (p.kind === "anthropic" && !sub) {
            url = p.baseUrl + "/v1/models?limit=100";
            headers = '-H "x-api-key: $' + p.envKey + '" -H "anthropic-version: 2023-06-01"';
        } else if (p.kind === "anthropic" && sub) {
            url = p.baseUrl + "/v1/models?limit=100";
            headers = '-H "Authorization: Bearer $' + p.subTokenVar + '"' +
                      ' -H "anthropic-version: 2023-06-01"' +
                      ' -H "anthropic-beta: oauth-2025-04-20,claude-code-20250219"';
        } else {
            url = p.baseUrl + "/v1/models";
            headers = '-H "Authorization: Bearer $' + p.envKey + '"';
            if (p.key === "openrouter")
                headers += " -H 'HTTP-Referer: https://argus.os' -H 'X-Title: Argus OS'";
        }
        return keyPrelude + "curl -s --max-time 25 " + headers + " " + url;
    }

    function refreshModels(key) {
        var k = key || ProviderConfig.provider;
        var p = ProviderConfig.byKey(k);
        // The Codex backend exposes no model catalog — curated list stands.
        if (p.key === "openai" && ProviderConfig.isSub("openai")) {
            modelsError = "Codex backend has no catalog — curated list";
            modelsFinished(k, false, 0);
            return;
        }
        if (modelsLoading) return;
        modelsLoading = true;
        modelsTarget = k;
        modelsError = "";
        modeler.command = ["sh", "-c", buildModels(p)];
        modeler.running = true;
    }

    function parseModels(text, key) {
        try {
            var j = JSON.parse(text);
            if (j.error || !j.data) {
                var m = (j.error && (j.error.message || JSON.stringify(j.error))) || "no catalog";
                return { "ok": false, "ids": [], "text": "Catalog failed: " + String(m).slice(0, 120) };
            }
            var ids = [];
            for (var i = 0; i < j.data.length; i++)
                if (j.data[i] && j.data[i].id) ids.push(j.data[i].id);
            // OpenAI lists every endpoint family — keep chat-capable ids only.
            if (key === "openai") {
                var keep = [];
                for (var q = 0; q < ids.length; q++)
                    if (/^(gpt|o\d|codex|chatgpt)/.test(ids[q])) keep.push(ids[q]);
                ids = keep;
            }
            ids.sort();
            return { "ok": ids.length > 0, "ids": ids,
                     "text": ids.length > 0 ? "" : "Catalog empty" };
        } catch (e) {
            return { "ok": false, "ids": [], "text": "Catalog unparseable" };
        }
    }

    property Process modeler: Process {
        stdout: StdioCollector {
            onStreamFinished: {
                var k = ArgusBridge.modelsTarget;
                var r = ArgusBridge.parseModels(this.text, k);
                ArgusBridge.modelsLoading = false;
                ArgusBridge.modelsError = r.ok ? "" : r.text;
                if (r.ok) {
                    ProviderConfig.setLive(k, r.ids);
                    // keep the selected model if still offered, else take the first
                    if (k === ProviderConfig.provider && r.ids.indexOf(ProviderConfig.model) < 0)
                        ProviderConfig.setModel(r.ids[0]);
                }
                ArgusBridge.modelsFinished(k, r.ok, r.ids.length);
            }
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (ArgusBridge.modelsLoading && this.text.trim() !== "")
                    ArgusBridge.lastError = this.text.slice(0, 200);
            }
        }
    }

    function cancel() {
        if (!busy) return;
        cancelActiveRequest();
        runner.running = false;
        busy = false;
        lastActivity = 0;
        AgentState.status = "idle";
        AgentState.agentActive = false;
        logAction("act", "Request cancelled", "blocked");
        AgentState.abortAgentTurn();
        // Without this the feed goes silent on stop, which reads as "broken".
        AgentState.pushMessage("agent", "Stopped. The action feed shows what was attempted.");
    }

    function retry() {
        if (busy) return;
        var h = AgentState.messages;
        for (var i = h.count - 1; i >= 0; i--) {
            var m = h.get(i);
            if (m.role === "user") { send(m.text); return; }
        }
    }

    // ── capability probe ─────────────────────────────────────────────────
    // Ask the runtime what this desktop can actually do, so the panel can warn
    // about missing input backends up front instead of the user discovering it
    // when a task fails halfway through.
    property var caps: ({})
    property string inputWarning: ""

    function refreshCaps() { doctorProc.running = true; }

    function parseCaps(text) {
        try {
            var j = JSON.parse(text);
            caps = j;
            var k = j.kwin || {};
            var missing = [];
            if (!k.keyboard) missing.push("keyboard");
            if (!k.pointer) missing.push("mouse");
            if (!k.window_inventory || !k.window_control) missing.push("window management");
            if (missing.length === 0) { inputWarning = ""; return; }
            var detail = k.keyboard_detail || k.pointer_detail || "";
            // Trim the long explanation to the actionable part.
            var shortDetail = detail.indexOf("uinput kernel module not loaded") >= 0
                            ? "uinput kernel module not loaded — reboot to enable"
                            : detail.slice(0, 120);
            inputWarning = missing.join(" + ") + " unavailable" + (shortDetail ? ": " + shortDetail : "");
        } catch (e) {
            inputWarning = "";
        }
    }

    property Process doctorProc: Process {
        command: ["sh", "-c", "python3 '" + Quickshell.shellDir +
                  "/../runtime/argusd.py' doctor --workspace '" +
                  String(ProviderConfig.workspace).replace(/'/g, "'\\''") + "' 2>/dev/null"]
        stdout: StdioCollector {
            onStreamFinished: ArgusBridge.parseCaps(this.text)
        }
    }

    // ── session id persistence ───────────────────────────────────────────
    // AgentState.sessionId is "s" + Date.now(), so every shell hot-reload
    // generated a fresh id and silently orphaned the journal session the
    // user was mid-conversation with. Persist it under XDG_STATE_HOME and
    // reload it at startup; every sessionId change (newSession via
    // clearMessages) writes it back.
    readonly property string sessionPath:
        (Quickshell.env("XDG_STATE_HOME") || ((Quickshell.env("HOME") || "/tmp") + "/.local/state"))
        + "/argus/session-id"

    function persistSession() {
        var esc = String(AgentState.sessionId).replace(/'/g, "'\\''");
        var dir = String(sessionPath).substring(0, String(sessionPath).lastIndexOf("/"));
        sessionSaveProc.command = ["sh", "-c",
            "mkdir -p '" + dir + "' && printf '%s' '" + esc + "' > '" + sessionPath + "'"];
        sessionSaveProc.running = true;
    }

    property Connections sessionIdWatcher: Connections {
        target: AgentState
        function onSessionIdChanged() { ArgusBridge.persistSession(); }
    }

    property Process sessionLoadProc: Process {
        command: ["sh", "-c", "cat '" + ArgusBridge.sessionPath + "' 2>/dev/null"]
        stdout: StdioCollector {
            onStreamFinished: {
                var t = this.text.trim();
                if (t !== "") AgentState.sessionId = t;
            }
        }
    }

    property Process sessionSaveProc: Process {}

    property Process daemonStarter: Process {
        command: ["sh", "-c", "systemctl --user start argusd.service 2>/dev/null || " +
                  "(test -S '" + ArgusBridge.runtimeSocketPath + "' || " +
                  "(nohup python3 -u '" + Quickshell.shellDir +
                  "/../runtime/argusd.py' serve >/dev/null 2>&1 &))"]
    }

    Component.onCompleted: {
        refreshCaps();
        sessionLoadProc.running = true;
        daemonStarter.running = true;
    }


    // ── streaming ingest ─────────────────────────────────────────────────
    // The runtime emits NDJSON: {"type":"event",...} lines as work happens and
    // one final {"type":"result",...} envelope. Progress therefore appears in
    // the feed while the task runs instead of after it finishes.
    property bool sawResult: false

    // Prose/reasoning deltas arrive one small SSE chunk at a time — often
    // dozens per second. Calling AgentState.appendDelta() once per raw chunk
    // would mean one QML relayout+repaint pass per chunk, which is far more
    // paint work than any display can show; coalescing into one flush per
    // timer tick keeps the per-character work the same but caps how often a
    // repaint actually happens. (An older version of this comment blamed a
    // JSON.parse/stringify-per-chunk cost plus a Repeater that fully
    // destroyed and recreated every already-rendered segment delegate on
    // every flush — AgentState.liveSegmentsModel() now mutates a real
    // ListModel in place instead, so that cost is gone; this timer's only
    // job now is capping repaint rate.) tool_call_delta is batched the same
    // way, keyed by tool-call id (not that more than one is ever really in
    // flight at once, but nothing here promises that).
    property string _pendingDeltaText: ""
    property string _pendingReasoningText: ""
    property var _pendingToolArgs: ({})
    property Timer deltaFlushTimer: Timer {
        interval: 8      // ~120fps cap — flush cost is now O(one delta), not O(message length)
        repeat: true
        onTriggered: ArgusBridge.flushDeltas()
    }
    function flushDeltas() {
        if (_pendingDeltaText !== "") {
            AgentState.appendDelta(_pendingDeltaText);
            _pendingDeltaText = "";
        }
        if (_pendingReasoningText !== "") {
            AgentState.appendReasoning(_pendingReasoningText);
            _pendingReasoningText = "";
        }
        for (var id in _pendingToolArgs) {
            if (_pendingToolArgs[id] !== "") AgentState.appendToolArgsDelta(id, _pendingToolArgs[id]);
        }
        _pendingToolArgs = {};
        if (_pendingDeltaText === "" && _pendingReasoningText === "") deltaFlushTimer.stop();
    }

    function ingestLine(line) {
        noteActivity();
        var t = String(line).trim();
        if (t === "") return;
        var obj = null;
        try { obj = JSON.parse(t); } catch (e) { return; }
        // Every other event type depends on segment ordering (a tool card
        // has to land after the prose that preceded it), so anything but
        // another chunk of one of the buffered streams flushes first.
        if (obj.type !== "delta" && obj.type !== "reasoning_delta" && obj.type !== "tool_call_delta")
            flushDeltas();
        switch (obj.type) {
        case "event":
            logAction(obj.kind, obj.summary, obj.status);
            if (obj.kind === "perceive") {
                AgentState.status = "watching";
            } else if (obj.status === "blocked") {
                AgentState.status = "blocked";
            } else if (AgentState.status !== "blocked") {
                AgentState.status = "working";
            }
            // Only act/verify/commit carry an id (see argusd.py progress());
            // perceive/plan stay Actions-tab-only — there's no tool card for
            // "here is the workspace context" to attach to.
            if (obj.id !== undefined) AgentState.toolEvent(obj.id, obj.status, obj.summary, obj.detail || null);
            return;
        case "delta":
            _pendingDeltaText += (obj.text || "");
            if (!deltaFlushTimer.running) deltaFlushTimer.start();
            return;
        case "reasoning_delta":
            _pendingReasoningText += (obj.text || "");
            if (!deltaFlushTimer.running) deltaFlushTimer.start();
            return;
        case "tool_call_start":
            AgentState.startToolSegment(obj.id, obj.name);
            if (obj.name === "observe_screen" || obj.name === "active_window" ||
                obj.name === "zoom_region" || obj.name === "find_text" ||
                obj.name === "list_displays" || obj.name === "assert_region_changed" ||
                obj.name === "wait_for_screen_change") {
                AgentState.status = "watching";
            } else if (AgentState.status !== "blocked") {
                AgentState.status = "working";
            }
            return;
        case "tool_call_delta":
            _pendingToolArgs[obj.id] = (_pendingToolArgs[obj.id] || "") + (obj.arguments || "");
            if (!deltaFlushTimer.running) deltaFlushTimer.start();
            return;
        case "tool_call_ready":
            AgentState.toolReady(obj.id, obj.name, obj.arguments);
            return;
        case "todos":
            if (obj.todos && obj.todos.length !== undefined)
                AgentState.todos = obj.todos;
            return;
        case "metrics":
            AgentState.setMetrics(obj);
            return;
        case "usage":
            AgentState.setUsage(obj);
            return;
        case "result":
            handleResult(obj);
            return;
        case "transport_error":
            lastError = obj.text || "Daemon transport failed";
            return;
        case "transport_done":
            activeRequestId = "";
            directFallbackCommand = "";
            daemonSocket.connected = false;
            finishRun(obj.code === undefined ? 1 : obj.code);
            return;
        }
        // non-streamed envelope (e.g. the approve path without --stream) has no `type`
        if (obj.text !== undefined) handleResult(obj);
    }

    function handleResult(obj) {
        sawResult = true;
        if (obj.events) {
            for (var z = 0; z < obj.events.length; z++)
                logAction(obj.events[z].kind, obj.events[z].summary, obj.events[z].status);
        }
        if (obj.compaction && obj.compaction.compacted)
            AgentState.startCompaction(obj.compaction.before, obj.compaction.after);
        if (obj.todos && obj.todos.length !== undefined)
            AgentState.todos = obj.todos;
        if (obj.approval) raiseApproval(obj.approval);
        AgentState.finishAgentTurn(obj.text !== undefined ? obj.text : "(no output)");
        busy = false;
        if (AgentState.status !== "blocked") {
            AgentState.status = "idle";
            AgentState.agentActive = false;
        }
    }

    function finishRun(code) {
        flushDeltas();
        lastActivity = 0;
        if (!sawResult && busy) {
            busy = false;
            AgentState.status = "idle";
            AgentState.agentActive = false;
            AgentState.abortAgentTurn();
            AgentState.pushMessage("agent", "⚠️ Agent runtime exited (code " + code + ") without a result"
                                   + (lastError !== "" ? ": " + lastError.slice(0, 200) : ""));
        }
    }

    property Socket daemonSocket: Socket {
        path: ArgusBridge.runtimeSocketPath
        parser: SplitParser {
            onRead: function (line) { ArgusBridge.ingestLine(line); }
        }
        onConnectedChanged: {
            if (connected && ArgusBridge.pendingSocketRequest !== "") {
                write(ArgusBridge.pendingSocketRequest);
                flush();
                ArgusBridge.pendingSocketRequest = "";
                ArgusBridge.socketRetryPending = false;
            }
        }
        onError: function (error) {
            if (!ArgusBridge.busy || ArgusBridge.directFallbackCommand === "") return;
            connected = false;
            if (ArgusBridge.socketRetryPending) {
                ArgusBridge.socketRetryPending = false;
                ArgusBridge.socketRetryTimer.start();
                return;
            }
            ArgusBridge.runner.command = ["sh", "-c", ArgusBridge.directFallbackCommand];
            ArgusBridge.runner.running = true;
            ArgusBridge.logAction("perceive", "Daemon unavailable — using direct runtime", "blocked");
        }
    }

    property Socket cancelSocket: Socket {
        property string requestId: ""
        path: ArgusBridge.runtimeSocketPath
        onConnectedChanged: {
            if (!connected || requestId === "") return;
            write(JSON.stringify({ "op": "cancel", "id": requestId }) + "\n");
            flush();
            requestId = "";
        }
    }

    property Process runner: Process {
        stdout: SplitParser {
            onRead: function (line) { ArgusBridge.ingestLine(line); }
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (this.text.trim() !== "")
                    ArgusBridge.lastError = this.text.slice(0, 200);
            }
        }
        onExited: function (code, status) { ArgusBridge.finishRun(code); }
    }

    function raiseApproval(a) {
        pendingApproval = a;
        AgentState.status = "blocked";
        AgentState.agentActive = false;
        approvalRaised(a);
    }
    function resolveApproval(allow, always) {
        var a = pendingApproval;
        pendingApproval = null;
        logAction("commit", (allow ? (always ? "Approved (always)" : "Approved") : "Denied")
                  + ": " + (a ? a.summary : ""), allow ? "ok" : "blocked");
        AgentState.status = "idle";
        // Only daemon-raised approvals carry an id. Text-heuristic approvals
        // (non-envelope path) have nothing executable behind them, and a task
        // already in flight must not have its runner command stomped.
        if (!a) return;
        if (!a.id) {
            logAction("commit", "Approved in-feed only — no pending daemon action", "ok");
            return;
        }
        if (busy) {
            logAction("commit", "Busy — approval recorded; re-send the task to continue", "blocked");
            return;
        }
        // The daemon, not QML, executes the approved action and records its
        // result. Grants are re-checked inside the runtime.
        var script = Quickshell.shellDir + "/../runtime/argusd.py";
        directFallbackCommand = "ARGUS_GRANT_SCREEN=" + (ProviderConfig.grantScreen ? "1" : "0") +
                                " ARGUS_GRANT_INPUT=" +
                                ((AgentState.computerUse && ProviderConfig.grantInput) ? "1" : "0") +
                                " ARGUS_GRANT_SHELL=" + (ProviderConfig.grantShell ? "1" : "0") +
                                " ARGUS_GRANT_NET=" + (ProviderConfig.grantNet ? "1" : "0") +
                                " PYTHONUNBUFFERED=1 exec python3 -u '" + script + "' approve '" +
                                String(a.id).replace(/'/g, "'\\''") + "' --stream" +
                                (allow ? " --allow" : "") +
                                (allow && always ? " --always" : "") +
                                " --workspace '" + String(ProviderConfig.workspace).replace(/'/g, "'\\''") + "'";
        activeRequestId = "r-" + Date.now();
        sawResult = false;
        busy = true;
        noteActivity();
        runStartedAt = Date.now();
        if (allow) {
            AgentState.status = "working";
            AgentState.agentActive = true;
        }
        startSocketRequest({ "op": "approve", "id": activeRequestId,
                             "approval_id": a.id, "allow": allow,
                             "always": allow && always,
                             "workspace": ProviderConfig.workspace,
                             "grants": currentGrants() });
    }

    function panic() {
        cancelActiveRequest();
        busy = false;
        runner.running = false;
        lastActivity = 0;
        pendingApproval = null;
        AgentState.agentActive = false;
        AgentState.computerUse = false;
        AgentState.status = "idle";
        logAction("commit", "PANIC — input control revoked, agents halted", "blocked");
    }
}
