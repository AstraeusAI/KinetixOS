pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Session history + cross-session memory for the Agent Panel's History tab.
// Mirrors McpConfig.qml's pattern: one-shot Process calls into `argusd.py`
// (list-sessions / session-transcript / list-memories / delete-memory /
// extract-memory), since both live in the runtime's SQLite journal —
// nothing here is a plain file QML could read/write directly the way
// ProviderConfig reads prefs.json.
QtObject {
    property var sessions: []   // [{session, title, started, last, events}]
    property var memories: []   // [{id, ts, text, source}]
    property bool loading: false
    property bool extracting: false

    readonly property string scriptPath: Quickshell.shellDir + "/../runtime/argusd.py"

    function refresh() {
        loading = true;
        listProc.command = ["sh", "-c", "python3 '" + scriptPath + "' list-sessions 2>/dev/null"];
        listProc.running = true;
        memProc.command = ["sh", "-c", "python3 '" + scriptPath + "' list-memories 2>/dev/null"];
        memProc.running = true;
    }

    property Process listProc: Process {
        stdout: StdioCollector {
            onStreamFinished: {
                SessionHistory.loading = false;
                try {
                    var j = JSON.parse(this.text);
                    if (j.ok) SessionHistory.sessions = j.sessions || [];
                } catch (e) { /* leave the last known-good list */ }
            }
        }
    }

    property Process memProc: Process {
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    var j = JSON.parse(this.text);
                    if (j.ok) SessionHistory.memories = j.memories || [];
                } catch (e) { /* leave the last known-good list */ }
            }
        }
    }

    // Loads a past session's transcript straight into AgentState, which
    // replaces the live message list and switches to the Chat tab. Sending
    // the next message continues this same session id — run() already
    // treats any session id as continuable, no special "resume" call needed.
    function openSession(sessionId) {
        var esc = String(sessionId).replace(/'/g, "'\\''");
        transcriptProc.sessionId = sessionId;
        transcriptProc.command = ["sh", "-c", "python3 '" + scriptPath +
            "' session-transcript --session '" + esc + "' 2>/dev/null"];
        transcriptProc.running = true;
    }

    property Process transcriptProc: Process {
        property string sessionId: ""
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    var j = JSON.parse(this.text);
                    if (j.ok) AgentState.loadSession(transcriptProc.sessionId, j.messages || []);
                } catch (e) { /* malformed reply — nothing to load */ }
            }
        }
    }

    function deleteMemory(id) {
        // Optimistic local removal so the card disappears immediately
        // instead of waiting on a full round trip.
        memories = memories.filter(function (m) { return m.id !== id; });
        deleteProc.command = ["sh", "-c", "python3 '" + scriptPath +
            "' delete-memory --id " + parseInt(id) + " 2>/dev/null"];
        deleteProc.running = true;
    }

    property Process deleteProc: Process {}

    // Fire-and-forget: called when a conversation is actually left behind
    // (AgentState.clearMessages, "New Session"), not per task — see
    // argusd.py's extract_memory for why. Refreshes the memory list once
    // it lands so a newly-learned fact shows up without the user asking.
    function extractMemory(sessionId) {
        if (extracting) return;
        extracting = true;
        var esc = String(sessionId).replace(/'/g, "'\\''");
        extractProc.command = ["sh", "-c", "python3 '" + scriptPath +
            "' extract-memory --session '" + esc + "' 2>/dev/null"];
        extractProc.running = true;
    }

    property Process extractProc: Process {
        stdout: StdioCollector {
            onStreamFinished: {
                SessionHistory.extracting = false;
                SessionHistory.refresh();
            }
        }
    }

    Component.onCompleted: refresh()
}
