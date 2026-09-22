pragma Singleton
import QtQuick
import Quickshell.Io

// LLM provider registry — exactly four providers:
//   OpenAI, Anthropic, OpenRouter (direct cloud) and OpenCode Go (gateway).
//
// Two auth modes per provider where supported:
//   "key" — classic API key (usage billing).
//   "sub" — subscription login: Claude Pro/Max OAuth token (Anthropic) or
//           ChatGPT Plus/Pro via the Codex backend (OpenAI).
//
// Secrets are NEVER stored here. They live in ~/.config/argus/keys.env
// (mode 0600, `export VAR='…'` lines), with the process environment as fallback.
// UI prefs (provider, model, auth modes) live in ~/.config/argus/prefs.json.
// `kind` selects the request/response shape:
//   openai    → {baseUrl}/v1/chat/completions, Authorization: Bearer
//   anthropic → {baseUrl}/v1/messages, x-api-key (or Bearer+beta for sub)
//   codex     → https://chatgpt.com/backend-api/codex/responses (Responses API)
QtObject {
    property string provider: "openai"
    property string model: "gpt-5.6-terra"
    property string baseUrl: "https://api.openai.com"

    property string systemPrompt: "You are Argus, the resident agent of an agent-native Linux desktop. You can see the screen and control input when granted. Be concise. When asked to act on the computer, briefly describe the perceive/plan/act/verify steps you would take — full computer-use execution lands in Phase 2."

    // Extended thinking / reasoning effort: "off" | "low" | "medium" | "high".
    // Global, not per-provider — argusd.py maps it to each provider's own
    // shape (Anthropic's thinking budget_tokens, OpenAI/OpenRouter/OpenCode's
    // reasoning.effort) and only includes the parameter at all when this is
    // not "off", so a model that doesn't support reasoning sees no change to
    // its request whatsoever at the default setting.
    property string reasoningEffort: "off"

    // capability grants (the human is root). shell defaults on, same as
    // screen/net: code execution is core to what the agent does, and the
    // runtime instructs the model to verify its own work via syntax_check/
    // lint/run_tests after every change — with shell off, every one of
    // those came back blocked and the model had no way to actually check
    // what it had just done. input (desktop mouse/keyboard control) also
    // defaults on, alongside the rest: the master "Computer Use Engine"
    // toggle (AgentState.computerUse) is the actual consent gate for
    // controlling the desktop at all, and a user who flips that on means
    // it — confirmed live: it silently blocked every click/type/launch
    // behind an unrelated, separately-off toggle with no in-context way to
    // discover that short of the agent hitting the wall, screenshotting its
    // own header, and explaining the mismatch back to the user. These four
    // chips (AgentPanel.qml's grantCard) stay in the header for someone who
    // wants to selectively *revoke* one capability for a session — e.g.
    // screen-only, no input — not to opt into it from a silent off state.
    property bool grantScreen: true
    property bool grantInput: true
    property bool grantClipboard: false
    property bool grantShell: true
    property bool grantNet: true

    // Project root the agent may read and edit. Empty = the Argus repo itself.
    // Everything outside this directory is refused by the runtime's workspace
    // check, and writes inside it are auto-approved while writes outside prompt.
    property string workspace: ""

    // auth mode per provider key: "key" | "sub"
    property var authMode: ({})

    // live model catalogs per provider key (from GET /v1/models)
    property var live: ({})

    // ── key vault (~/.config/argus/keys.env, mode 0600) ──
    readonly property string keysDir: "$HOME/.config/argus"
    readonly property string keysPath: keysDir + "/keys.env"
    readonly property string prefsPath: keysDir + "/prefs.json"
    property var keys: ({})
    property bool keysLoaded: false

    property Process keysReader: Process {
        command: ["sh", "-c", "cat " + ProviderConfig.keysPath + " 2>/dev/null"]
        running: true
        stdout: StdioCollector {
            onStreamFinished: ProviderConfig.loadKeys(this.text)
        }
    }
    // The vault can be updated by the runtime, a terminal, or a hot-reloaded
    // shell. Keep singleton state honest instead of showing a stale “NO KEY”.
    property Timer keysRefreshTimer: Timer {
        interval: 2500
        repeat: true
        running: true
        onTriggered: {
            if (!ProviderConfig.keysReader.running)
                ProviderConfig.keysReader.running = true;
        }
    }
    property Process keysWriter: Process {}

    function loadKeys(text) {
        var m = {};
        var lines = String(text || "").split("\n");
        for (var i = 0; i < lines.length; i++) {
            var mt = lines[i].match(/^export ([A-Z][A-Z0-9_]*)='(.*)'$/);
            if (mt) m[mt[1]] = mt[2].replace(/'\\''/g, "'");
        }
        keys = m;
        keysLoaded = true;
    }
    function hasKey(envKey) {
        return !!(keys[envKey] && keys[envKey] !== "");
    }
    function masked(envKey) {
        var k = keys[envKey] || "";
        if (k === "") return "";
        if (k.length <= 8) return "••••••••";
        return "••••" + k.slice(-4);
    }
    function setKey(envKey, value) {
        var v = String(value || "").replace(/[\r\n]/g, "").trim();
        var m = {};
        for (var k in keys) m[k] = keys[k];
        if (v === "") delete m[envKey]; else m[envKey] = v;
        keys = m;
        saveKeysNow(m);
    }
    function saveKeysNow(m) {
        var lines = [];
        for (var k in m)
            lines.push("export " + k + "='" + String(m[k]).replace(/'/g, "'\\''") + "'");
        var body = lines.join("\n") + (lines.length > 0 ? "\n" : "");
        keysWriter.environment = { "ARGUS_KEYS_PAYLOAD": body };
        keysWriter.command = ["sh", "-c",
            "umask 077 && mkdir -p \"$1\" && printf '%s' \"$ARGUS_KEYS_PAYLOAD\" > \"$2\" && chmod 600 \"$2\"",
            "sh", keysDir, keysPath];
        keysWriter.running = true;
    }

    // ── Codex login import (~/.codex/auth.json) ──
    // Tolerant recursive extraction: the file schema is Codex's business,
    // we just need an access token and, ideally, an account id.
    property string codexImport: ""
    signal codexImported(var ok)
    property Process codexReader: Process {
        stdout: StdioCollector {
            onStreamFinished: ProviderConfig.parseCodex(this.text)
        }
    }
    function importCodex() {
        codexImport = "";
        codexReader.command = ["sh", "-c", "cat $HOME/.codex/auth.json 2>/dev/null"];
        codexReader.running = true;
    }
    function findToken(obj, names) {
        var stack = [obj];
        while (stack.length > 0) {
            var o = stack.pop();
            if (o && typeof o === "object") {
                for (var k in o) {
                    if (names.indexOf(k) >= 0 && typeof o[k] === "string" && o[k] !== "")
                        return o[k];
                    stack.push(o[k]);
                }
            }
        }
        return "";
    }
    function parseCodex(text) {
        if (!text || text.trim() === "") {
            codexImport = "No Codex login found — run `codex login` first";
            codexImported(false);
            return;
        }
        try {
            var j = JSON.parse(text);
            var tok = findToken(j, ["access_token", "accessToken"]);
            var acc = findToken(j, ["account_id", "accountId", "accountID"]);
            if (tok === "") {
                codexImport = "No token in auth.json — re-run `codex login`";
                codexImported(false);
                return;
            }
            var m = {};
            for (var k in keys) m[k] = keys[k];
            m["OPENAI_CODEX_TOKEN"] = tok;
            if (acc !== "") m["OPENAI_CODEX_ACCOUNT"] = acc;
            keys = m;
            saveKeysNow(m);
            codexImport = "Imported Codex login" + (acc !== "" ? "" : " (no account id — chat may fail)");
            codexImported(true);
        } catch (e) {
            codexImport = "auth.json unreadable — re-run `codex login`";
            codexImported(false);
        }
    }
    property Process prefsReader: Process {
        command: ["sh", "-c", "cat " + ProviderConfig.prefsPath + " 2>/dev/null"]
        running: true
        stdout: StdioCollector {
            onStreamFinished: ProviderConfig.loadPrefs(this.text)
        }
    }
    property Process prefsWriter: Process {}
    property Timer prefsSaveTimer: Timer {
        interval: 600
        onTriggered: ProviderConfig.savePrefsNow()
    }

    readonly property var reasoningLevels: ["off", "low", "medium", "high"]

    function loadPrefs(text) {
        if (!text || text.trim() === "") return;
        try {
            var j = JSON.parse(text);
            if (j.provider && byKey(j.provider)) {
                provider = j.provider;
                baseUrl = byKey(j.provider).baseUrl;
            }
            if (j.model && typeof j.model === "string" && j.model !== "") model = j.model;
            if (j.auth && typeof j.auth === "object") authMode = j.auth;
            if (j.reasoning && reasoningLevels.indexOf(j.reasoning) >= 0) reasoningEffort = j.reasoning;
        } catch (e) { /* corrupt → keep defaults */ }
    }
    function savePrefs() { prefsSaveTimer.restart(); }
    function savePrefsNow() {
        var json = JSON.stringify({ "provider": provider, "model": model, "auth": authMode,
                                     "reasoning": reasoningEffort });
        var esc = json.replace(/'/g, "'\\''");
        prefsWriter.command = ["sh", "-c",
            "(umask 077; mkdir -p " + keysDir +
            " && printf '%s' '" + esc + "' > " + prefsPath +
            " && chmod 600 " + prefsPath + ")"];
        prefsWriter.running = true;
    }

    function isSub(key) { return authMode[key || provider] === "sub"; }
    function setAuthMode(key, mode) {
        var m = {};
        for (var k in authMode) m[k] = authMode[k];
        m[key] = mode;
        authMode = m;
        // switching auth resets the model to that mode's default
        var p = byKey(key);
        if (key === provider) {
            if (mode === "sub" && p.subModels && p.subModels.length) model = p.subModels[0];
            else if (p.models && p.models.length) model = p.models[0];
        }
        savePrefs();
    }
    function setModel(m) { model = m; savePrefs(); }
    function setReasoning(level) {
        if (reasoningLevels.indexOf(level) < 0) return;
        reasoningEffort = level;
        savePrefs();
    }

    function setLive(key, arr) {
        var l = {};
        for (var k in live) l[k] = live[k];
        l[key] = arr;
        live = l;
    }
    function modelsFor(key) {
        var p = byKey(key);
        if (isSub(key) && p.subModels) return p.subModels;
        var l = live[key];
        if (l && l.length > 0) return l;
        return p.models || [];
    }

    readonly property var providers: [
        { "key":"openai", "label":"OpenAI", "group":"Cloud", "kind":"openai",
          "baseUrl":"https://api.openai.com", "envKey":"OPENAI_API_KEY",
          "site":"https://platform.openai.com/api-keys",
          "authModes":["key","sub"], "subKind":"codex",
          "subSite":"https://learn.chatgpt.com/docs/auth",
          "subTokenVar":"OPENAI_CODEX_TOKEN", "subAccountVar":"OPENAI_CODEX_ACCOUNT",
          "subSteps":["Install the Codex CLI and run `codex login`, or paste a Codex access token below.",
                      "Tip: if ~/.codex/auth.json exists we can import it automatically."],
          "models":["gpt-5.6-terra","gpt-5.6-sol","gpt-5.6-luna","gpt-5.4-mini",
                    "gpt-5-mini","gpt-4o","gpt-4o-mini","o4-mini"],
          "subModels":["gpt-5.3-codex","gpt-5.2-codex","gpt-5.1-codex",
                       "gpt-5-codex","gpt-5.3-codex-spark"] },
        { "key":"anthropic", "label":"Anthropic", "group":"Cloud", "kind":"anthropic",
          "baseUrl":"https://api.anthropic.com", "envKey":"ANTHROPIC_API_KEY",
          "site":"https://console.anthropic.com/",
          "authModes":["key","sub"], "subKind":"claude-oauth",
          "subSite":"https://docs.anthropic.com/en/docs/claude-code/authentication",
          "subTokenVar":"ANTHROPIC_SUB_TOKEN", "subAccountVar":"",
          "subSteps":["Run `claude setup-token` in a terminal (Claude Pro/Max login) and paste the token below.",
                      "Subscription calls reuse the Claude Code scope and may be less stable than API keys."],
          "models":["claude-sonnet-4-6","claude-sonnet-4-5","claude-opus-4-6",
                    "claude-opus-5","claude-haiku-4-5","claude-3-5-haiku"] },
        { "key":"openrouter", "label":"OpenRouter", "group":"Cloud", "kind":"openai",
          "baseUrl":"https://openrouter.ai/api", "envKey":"OPENROUTER_API_KEY",
          "site":"https://openrouter.ai/keys",
          "authModes":["key"],
          "models":["openai/gpt-5.2","anthropic/claude-sonnet-4","google/gemini-2.5-pro",
                    "deepseek/deepseek-chat","meta-llama/llama-3.3-70b-instruct",
                    "qwen/qwen-2.5-72b-instruct","x-ai/grok-4","mistralai/mistral-large"] },
        { "key":"opencode", "label":"OpenCode Go", "group":"Gateway", "kind":"openai",
          "baseUrl":"https://opencode.ai/zen/go", "envKey":"OPENCODE_API_KEY",
          "site":"https://opencode.ai/auth",
          "authModes":["key"],
          "models":["kimi-k2.6","deepseek-v4-flash","deepseek-v4-pro","glm-5.2",
                    "minimax-m3","grok-4.5","big-pickle","mimo-v2.5-free"] }
    ]

    function byKey(key) {
        for (var i = 0; i < providers.length; i++)
            if (providers[i].key === key) return providers[i];
        return providers[0];
    }
    function current() { return byKey(provider); }

    function setProvider(key) {
        provider = key;
        var p = byKey(key);
        baseUrl = p.baseUrl;
        var list = modelsFor(key);
        if (list.length) model = list[0];
        savePrefs();
    }
    function models() { return modelsFor(provider); }
    function grouped() {
        var out = [], seen = {};
        for (var i = 0; i < providers.length; i++) {
            var g = providers[i].group;
            if (!seen[g]) { seen[g] = true; out.push(g); }
        }
        return out;
    }
    function inGroup(g) {
        var out = [];
        for (var i = 0; i < providers.length; i++)
            if (providers[i].group === g) out.push(providers[i]);
        return out;
    }
}
