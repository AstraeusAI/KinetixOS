.pragma library

// Markdown-lite -> QML RichText (Text.RichText's HTML4 subset). Scoped to
// what model replies actually use: fenced code, bold/italic, inline code,
// bullet/numbered lists, links, paragraph breaks. Not a spec-complete
// CommonMark parser — headings, tables, blockquotes and nested lists are
// deliberately out of scope.

function _esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Attribute context (href): a URL is model- or file-controlled text being placed
// inside a double-quoted attribute, so quotes need escaping on top of _esc, and
// only schemes the OS can safely open are allowed through as links at all.
function _escAttr(s) {
    return _esc(s).replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function _safeHref(url) {
    return /^(https?|mailto):/i.test(String(url).trim());
}

// Kept in sync by hand with AgentPanel.qml's `pAccent2` (the panel's ominous
// red palette) — a .js pragma library has no access to that QML property.
var ACCENT2 = "#E8752E";

// Placeholder sentinels for text pulled out of the flow: one for inline code
// (resolved by _inline from its own local slot list) and a separate one for
// fenced blocks (resolved at the end of toRich from `blocks`). They must be
// distinct characters that cannot occur in a reply, and they must not be bare
// digits — the original used a space-delimited index for both ends, which both
// failed to substitute (the fence placeholder was " 0 " while the substitution
// searched for "\u0001"+"0"+"\u0001") and matched ordinary prose, so every code
// block *and* every number in a reply rendered as the literal "undefined".
var MARK = "\u0001";
var MARK_RE = /\u0001(\d+)\u0001/g;
var FENCE = "\u0002";
var FENCE_RE = /\u0002(\d+)\u0002/g;

// Bold before italic (∗∗ contains ∗), inline code before both (its contents
// must not be touched by either), links last so `[x](y)` text isn't eaten
// by the emphasis regexes first.
function _inline(s) {
    var codeSlots = [];
    s = s.replace(/`([^`\n]+?)`/g, function (_m, code) {
        // s was already passed through _esc(), so code is already safely escaped
        codeSlots.push(code);
        return MARK + (codeSlots.length - 1) + MARK;
    });
    s = s.replace(/\*\*([^*]+?)\*\*/g, "<b>$1</b>");
    s = s.replace(/__([^_]+?)__/g, "<b>$1</b>");
    s = s.replace(/\*([^*\n]+?)\*/g, "<i>$1</i>");
    s = s.replace(/(^|[^\w])_([^_\n]+?)_(?!\w)/g, "$1<i>$2</i>");
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (_m, label, url) {
        if (!_safeHref(url)) return label + " (" + url + ")";
        return '<a href="' + _escAttr(url) + '" style="color:' + ACCENT2 + '; text-decoration:underline;">' + label + "</a>";
    });
    s = s.replace(MARK_RE, function (_m, i) {
        return '<font face="JetBrains Mono" color="' + ACCENT2 + '">' + codeSlots[parseInt(i, 10)] + "</font>";
    });
    return s;
}

function toRich(text) {
    if (!text) return "";
    // Pull fenced code blocks out first so nothing inside them is touched
    // by inline formatting or escaped twice.
    var blocks = [];
    var withoutFences = String(text).replace(/```([a-zA-Z0-9_+-]*)\n?([\s\S]*?)```/g, function (_m, lang, code) {
        var langTag = (lang || "").trim();
        var header = langTag
            ? '<div style="font-family:\'JetBrains Mono\', monospace; font-size:9px; font-weight:bold; color:' + ACCENT2 + '; padding:5px 10px; border-bottom:1px solid rgba(255,255,255,0.09); text-transform:uppercase; letter-spacing:1.5px; background-color:rgba(255,255,255,0.03);">' + _esc(langTag) + '</div>'
            : '';
        // border-top simulates a rim-light highlight — Qt's rich-text subset has
        // no CSS gradients/box-shadow, so a slightly brighter single hairline is
        // the whole "lift this off the bubble behind it" budget available here.
        blocks.push('<div style="background-color:#140708; border:1px solid rgba(255,255,255,0.10); border-top:1px solid rgba(255,255,255,0.16); border-radius:10px; margin:6px 0; overflow:hidden;">' + header + '<pre style="color:#EFE3E2; font-family:\'JetBrains Mono\', monospace; font-size:11px; padding:9px 12px; margin:0; line-height:1.5;">' + _esc(code.replace(/\n$/, "")) + '</pre></div>');
        return FENCE + (blocks.length - 1) + FENCE;
    });

    var lines = withoutFences.split("\n");
    var out = [];
    var i = 0;
    while (i < lines.length) {
        var line = lines[i];
        var bullet = line.match(/^(\s*)[-*]\s+(.*)$/);
        var numbered = line.match(/^(\s*)\d+[.)]\s+(.*)$/);
        if (bullet || numbered) {
            var tag = bullet ? "ul" : "ol";
            var items = [];
            while (i < lines.length) {
                var m = lines[i].match(bullet ? /^(\s*)[-*]\s+(.*)$/ : /^(\s*)\d+[.)]\s+(.*)$/);
                if (!m) break;
                items.push("<li>" + _inline(_esc(m[2])) + "</li>");
                i++;
            }
            out.push("<" + tag + ">" + items.join("") + "</" + tag + ">");
            continue;
        }
        if (line.trim() === "") { out.push(""); i++; continue; }
        out.push(_inline(_esc(line)));
        i++;
    }

    // Collapse consecutive plain lines with <br>, keep a blank line as a
    // paragraph gap, leave list/pre blocks (already full elements) alone.
    var html = "";
    for (var k = 0; k < out.length; k++) {
        var seg = out[k];
        if (seg === "") { html += "<br>"; continue; }
        if (seg.indexOf("<ul>") === 0 || seg.indexOf("<ol>") === 0) { html += seg; continue; }
        html += (html && html.slice(-4) !== "<br>" && html.slice(-4) !== "</ul>" && html.slice(-4) !== "</ol>" ? "<br>" : "") + seg;
    }

    html = html.replace(FENCE_RE, function (_m, i2) { return blocks[parseInt(i2, 10)]; });
    return html;
}
