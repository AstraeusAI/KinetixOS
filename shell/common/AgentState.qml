pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// UI-facing agent state. The bridge (ArgusBridge) drives these properties.
QtObject {
    property bool panelOpen: false
    property bool paletteOpen: false
    property bool launcherOpen: false
    property string activeWindowTitle: ""
    property string activeWindowApp: ""

    // ── quick terminal ───────────────────────────────────────────────
    // Preferred path: Ghostty's own native drop-down (shell/terminal/), a
    // real wlr-layer-shell surface — see ghostty.conf's header comment for
    // why we don't reimplement that in QML. KinetixOS requires Ghostty and
    // does not substitute a second terminal emulator if it is missing.
    property bool terminalOpen: false
    property Process terminalToggleProc: Process {
        stdout: StdioCollector {
            onStreamFinished: AgentState.terminalOpen = (this.text.trim() === "open")
        }
    }
    property Process terminalStatusProbe: Process {
        command: [Quickshell.shellDir + "/terminal/toggle.sh", "--status"]
        running: true
        stdout: StdioCollector {
            onStreamFinished: AgentState.terminalOpen = (this.text.trim() === "open")
        }
    }
    function toggleTerminal() {
        terminalToggleProc.command = [Quickshell.shellDir + "/terminal/toggle.sh"];
        terminalToggleProc.running = true;
    }

    property bool sysHovered: false
    property bool sysOpen: false
    property real sysRightMargin: 16
    function toggleSys() {
        if (!sysOpen) appCenterOpen = false;
        sysOpen = !sysOpen;
    }
    property bool notifOpen: false
    function toggleNotifs() {
        if (!notifOpen) { sysOpen = false; appCenterOpen = false; }
        notifOpen = !notifOpen;
    }
    property bool appCenterOpen: false
    property real appCenterRightMargin: 16
    function toggleAppCenter() {
        if (!appCenterOpen) {
            sysOpen = false;
            paletteOpen = false;
            launcherOpen = false;
        }
        appCenterOpen = !appCenterOpen;
    }
    property bool agentActive: false      // true while an agent holds input control → EdgeGlow
    property bool computerUse: true
    property string status: "idle"        // idle | watching | working | blocked
    property string activeTab: "chat"     // chat | actions | mcp | history
    property bool settingsOpen: false
    property bool compacting: false
    property real compactionProgress: 0
    property string compactionLabel: ""

    // Plan state reported by the runtime's todo_write tool.
    property var todos: []

    // Conversation id handed to the runtime. Each task is journaled under it,
    // so clearing the feed starts a genuinely new conversation instead of
    // interleaving every task into one shared "default" session.
    property string sessionId: "s" + Date.now().toString(36)
    function newSession() { sessionId = "s" + Date.now().toString(36); }

    // A real ListModel, not a plain JS array: live streaming edits one row
    // at a time (setProperty on the last index) via a handful of live token
    // and tool-call deltas per second. A plain `property var` array has to be
    // reassigned wholesale to notify bindings, which makes Qt Quick's views
    // tear down and recreate every delegate in the whole chat history on
    // every single delta — including any already-rendered xterm.js tool-call
    // cards, which is both slow and visibly flickers. ListModel.setProperty
    // updates exactly the one row that changed.
    property ListModel messages: ListModel {}
    // Bumped on every messages mutation. ListModel.setProperty() (used for
    // live in-place segment edits) doesn't retroactively notify a plain JS
    // binding that earlier read messages.get(i).text — reading `rev` inside
    // such a binding forces it to re-run whenever anything here changes.
    property int rev: 0

    Component.onCompleted: {
        // Starts empty so the hero greeting, capability badges, and prompt starters render cleanly
    }

    function togglePanel() { panelOpen = !panelOpen; }
    function openPalette() { paletteOpen = true; }
    function togglePalette() { paletteOpen = !paletteOpen; }
    function openLauncher() { launcherOpen = true; }
    function toggleLauncher() { launcherOpen = !launcherOpen; }
    function setTab(t) { activeTab = t; }
    function toggleSettings() { settingsOpen = !settingsOpen; }

    function pushMessage(role, text) {
        messages.append({ "role": role, "text": text,
                          "time": new Date().toLocaleTimeString([], "hh:mm"), "segments": [] });
        rev++;
    }
    function clearMessages() {
        // The conversation being left behind is exactly the moment
        // extraction is worth its one provider call — see extract_memory's
        // own docstring for why this is not fired per task. Skipped for a
        // session that never actually said anything (a fresh panel open
        // immediately followed by "New Session").
        if (messages.count > 0) SessionHistory.extractMemory(sessionId);
        messages.clear();
        todos = [];
        turnLive = false;
        resetTelemetry();
        status = "idle";
        agentActive = false;
        rev++;
        newSession();
        ArgusBridge.clearActions();
        ArgusBridge.pendingApproval = null;
        if (ArgusBridge.busy) ArgusBridge.panic();
    }

    // Called by SessionHistory when the user picks a past conversation from
    // the History tab. Replaces the live message list with that session's
    // transcript and switches this session id so the *next* message sent
    // continues it — run() already treats any session id as continuable.
    function loadSession(id, transcript) {
        messages.clear();
        for (var i = 0; i < transcript.length; i++) {
            var m = transcript[i];
            messages.append({ "role": m.role, "text": m.text,
                              "time": new Date(m.ts).toLocaleTimeString([], "hh:mm"),
                              "segments": [] });
        }
        todos = [];
        turnLive = false;
        resetTelemetry();
        status = "idle";
        sessionId = id;
        rev++;
        setTab("chat");
    }

    // Flat text preview of the most recent message (segments joined, for
    // agent turns whose prose lives in segments rather than the `text`
    // role) — used by surfaces like the desktop AgentWidget that just want
    // "what did Argus last say", not the rich per-segment structure.
    function lastMessageText() {
        if (messages.count === 0) return "";
        var m = messages.get(messages.count - 1);
        var segs = m.segments;
        if (segs && segs.count > 0) {
            var out = "";
            for (var i = 0; i < segs.count; i++) {
                var s = segs.get(i);
                if (s.type === "text") out += s.text;
            }
            if (out !== "") return out;
        }
        return m.text || "";
    }

    // Reactive cached version for QML bindings (updates when rev changes)
    property string lastMessageTextCache: (rev, lastMessageText())

    // ── live streaming turn ────────────────────────────────────────────
    // An agent reply is a message with `segments`: an ordered mix of prose
    // ("text") and tool calls ("tool"), built up live as NDJSON arrives from
    // the runtime — text deltas grow the current text segment, a tool call
    // opens a new segment that fills in (name, then streamed arguments, then
    // execution status and output) in place.
    property bool turnLive: false

    // Live streaming telemetry (resets per turn)
    property int streamTtft: 0
    property real streamTps: 0.0
    property int streamTokens: 0
    property int streamPromptTokens: 0
    property int streamCompletionTokens: 0
    property int streamTotalTokens: 0

    function setMetrics(m) {
        if (!m) return;
        if (m.ttft !== undefined && m.ttft > 0) streamTtft = m.ttft;
        if (m.tps !== undefined) streamTps = m.tps;
        if (m.tokens !== undefined) streamTokens = m.tokens;
        rev++;
    }

    function setUsage(u) {
        if (!u) return;
        if (u.prompt_tokens !== undefined) streamPromptTokens = u.prompt_tokens;
        if (u.completion_tokens !== undefined) streamCompletionTokens = u.completion_tokens;
        if (u.total_tokens !== undefined) streamTotalTokens = u.total_tokens;
        rev++;
    }

    function resetTelemetry() {
        streamTtft = 0;
        streamTps = 0.0;
        streamTokens = 0;
        streamPromptTokens = 0;
        streamCompletionTokens = 0;
        streamTotalTokens = 0;
        rev++;
    }

    // Compact "what's the agent doing right now" label for surfaces that
    // don't render the full segment stream (e.g. the desktop AgentWidget).
    property string liveToolText: ""

    function ensureAgentTurn() {
        if (turnLive) return;
        resetTelemetry();
        liveToolText = "";
        messages.append({ "role": "agent", "text": "",
                          "time": new Date().toLocaleTimeString([], "hh:mm"),
                          "segments": [{ "type": "text", "text": "" }] });
        turnLive = true;
    }

    // `segments` is a nested ListModel (QML auto-promotes an array-of-objects
    // role value written on append into one), mutated in place via
    // get()/setProperty()/append() — never reassigned wholesale. Reassigning
    // a freshly-parsed array on every delta (the old JSON-string approach)
    // made the segment Repeater in AgentPanel.qml destroy and recreate every
    // delegate — every finished text bubble, every tool card, every terminal
    // card — on every single streamed chunk, since a plain JS array gives Qt
    // Quick no way to know only one element changed. A real ListModel updates
    // only the row that changed. `tool.args`/`tool.detail` are the one
    // exception: ListModel rejects plain object role values outright, so
    // those stay JSON-string roles (`argsJson`/`detailJson`) — fine, since
    // they're written once per tool call, never per streamed character.
    function liveSegmentsModel() {
        return messages.get(messages.count - 1).segments;
    }

    // Marks a still-open trailing "reasoning" segment done. Called whenever
    // anything else starts appending after it — prose or a tool call — since
    // that's the actual signal a model is done thinking, not any explicit
    // event a provider sends. Absent `status` means "still thinking" (the
    // reasoningComp delegate treats undefined the same as anything not
    // "done"), so a freshly created reasoning segment needs no field for it.
    function _closeTrailingReasoning(segs) {
        if (segs.count === 0) return;
        var last = segs.get(segs.count - 1);
        if (last.type === "reasoning" && last.status !== "done")
            segs.setProperty(segs.count - 1, "status", "done");
    }

    function appendDelta(text) {
        ensureAgentTurn();
        var segs = liveSegmentsModel();
        _closeTrailingReasoning(segs);
        var n = segs.count;
        if (n > 0 && segs.get(n - 1).type === "text") {
            segs.setProperty(n - 1, "text", segs.get(n - 1).text + text);
        } else {
            segs.append({ "type": "text", "text": text });
        }
        rev++;
    }

    // Chain-of-thought / extended-thinking tokens some models stream ahead
    // of their real answer (Anthropic `thinking_delta`, OpenRouter/DeepSeek
    // `reasoning`, Codex reasoning summaries). Kept as its own segment type
    // so the UI can show it de-emphasized and collapsible, and it is never
    // sent back to the model as conversation history (see argusd.py).
    function appendReasoning(text) {
        ensureAgentTurn();
        var segs = liveSegmentsModel();
        var n = segs.count;
        if (n > 0 && segs.get(n - 1).type === "reasoning") {
            segs.setProperty(n - 1, "text", segs.get(n - 1).text + text);
        } else {
            segs.append({ "type": "reasoning", "text": text });
        }
        rev++;
    }

    function findToolSegment(segs, id) {
        for (var i = segs.count - 1; i >= 0; i--)
            if (segs.get(i).type === "tool" && segs.get(i).id === id) return i;
        return -1;
    }

    function startToolSegment(id, name) {
        ensureAgentTurn();
        var segs = liveSegmentsModel();
        if (findToolSegment(segs, id) >= 0) return;
        _closeTrailingReasoning(segs);
        segs.append({ "type": "tool", "id": id, "name": name || "", "argsText": "",
                      "argsJson": "", "status": "building", "summary": "", "detailJson": "" });
        liveToolText = name || "";
        rev++;
    }

    function appendToolArgsDelta(id, chunk) {
        var segs = liveSegmentsModel();
        var i = findToolSegment(segs, id);
        if (i < 0) return;
        segs.setProperty(i, "argsText", (segs.get(i).argsText || "") + chunk);
        rev++;
    }

    function toolReady(id, name, args) {
        var segs = liveSegmentsModel();
        var i = findToolSegment(segs, id);
        if (i < 0) return;
        if (name) { segs.setProperty(i, "name", name); liveToolText = name; }
        segs.setProperty(i, "argsJson", JSON.stringify(args !== undefined ? args : null));
        rev++;
    }

    // Routes a runtime {"type":"event",...} with an `id` into the matching
    // live tool card. If no card exists yet (e.g. an approval's own action,
    // resumed outside the streamed tool-call sequence, or the runtime
    // exiting before this turn's segments could reconstruct) one is created
    // on the spot — nothing observable from the runtime is ever dropped.
    function toolEvent(id, status, summary, detail) {
        ensureAgentTurn();
        var segs = liveSegmentsModel();
        var i = findToolSegment(segs, id);
        if (i < 0) {
            segs.append({ "type": "tool", "id": id, "name": summary || "", "argsText": "",
                          "argsJson": "", "status": status, "summary": summary || "",
                          "detailJson": detail ? JSON.stringify(detail) : "" });
            if (status === "running") liveToolText = summary || "";
            rev++;
            return;
        }
        segs.setProperty(i, "status", status);
        if (detail) segs.setProperty(i, "detailJson", JSON.stringify(detail));
        segs.setProperty(i, "summary", summary || "");
        if (status === "running") liveToolText = summary || segs.get(i).name || "";
        rev++;
    }

    // Called once the runtime's final {"type":"result"} arrives. If a live
    // turn was built, it's simply marked done in place (its segments are
    // already the message); otherwise this falls back to a plain text
    // message, e.g. for a reply that made no tool calls and — on some
    // provider hiccup — streamed no deltas either.
    function finishAgentTurn(text) {
        if (!turnLive) { pushMessage("agent", text); return; }
        turnLive = false;
        liveToolText = "";
        var segs = liveSegmentsModel();
        _closeTrailingReasoning(segs);
        var hasText = false;
        for (var i = 0; i < segs.count; i++) {
            var s = segs.get(i);
            if (s.type === "text" && s.text && s.text.trim() !== "") { hasText = true; break; }
        }
        if (!hasText && text) segs.append({ "type": "text", "text": text });
        rev++;
    }
    function abortAgentTurn() {
        turnLive = false;
        liveToolText = "";
        // Drop a live turn that never produced visible content, so cancel /
        // watchdog / runtime-exit doesn't leave a header-only empty bubble
        // sitting above the explanatory message that follows.
        if (messages.count === 0) return;
        var last = messages.get(messages.count - 1);
        if (!last || last.role !== "agent") return;
        var segs = last.segments;
        var empty = !segs || segs.count === 0 ||
                    (segs.count === 1 && segs.get(0).type === "text" && segs.get(0).text === "");
        if (empty) { messages.remove(messages.count - 1); rev++; }
    }

    function startCompaction(before, after) {
        compacting = true;
        compactionProgress = 0;
        compactionLabel = "Condensing " + Math.round(before / 1000) + "k context → durable memory";
        compactionTimer.restart();
    }
    property Timer compactionTimer: Timer {
        interval: 28; repeat: true
        onTriggered: {
            AgentState.compactionProgress = Math.min(1, AgentState.compactionProgress + 0.035);
            if (AgentState.compactionProgress >= 1) { stop(); AgentState.compacting = false; }
        }
    }

}
