// Tests for shell/agent/Markdown.js — run with:  node shell/agent/tests/markdown.test.js
//
// Markdown.js is a .pragma library QML JS file that uses no Qt APIs in the
// markdown-to-HTML path, so node can load it directly (the pragma line is
// stripped) and its output inspected, rather than trusting that the rendering
// works because the regexes look plausible.
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'Markdown.js'), 'utf8')
    .replace(/^\.pragma library\s*$/m, '');
const { toRich } = new Function(src + '\nreturn { toRich: toRich };')();

const cases = [
    ['a fenced block renders as <pre>',
        '```python\nprint("hi")\n```',
        html => html.includes('<pre') && html.includes('print("hi")')],
    ['a fenced block never renders as "undefined"',
        'before\n\n```\ncode\n```\n\nafter',
        html => !html.includes('undefined')],
    ['both of two fences render',
        '```\na\n```\ntext\n```\nb\n```',
        html => (html.match(/<pre/g) || []).length === 2],
    ['numbers in prose survive',
        'There are 3 files and 12 tests to update.',
        html => html.includes('3 files') && html.includes('12 tests') && !html.includes('undefined')],
    ['inline code survives next to a number',
        'Use `printf` with 2 args.',
        html => html.includes('>printf<') && html.includes('2 args') && !html.includes('undefined')],
    ['bold, italic and bullets still render',
        '**bold** and *italic*\n\n- one\n- two',
        html => html.includes('<b>bold</b>') && html.includes('<i>italic</i>') &&
                html.includes('<ul><li>one</li><li>two</li></ul>')],
    ['an https link becomes an anchor',
        'See [docs](https://example.com/x).',
        html => html.includes('href="https://example.com/x"')],
    ['a quote in a URL cannot break out of the attribute',
        '[x](y"><img/src=file:///etc/passwd>)',
        html => !html.includes('<img') && !html.includes('href="y"')],
    ['file:// and javascript: are not turned into links',
        '[local](file:///etc/passwd) and [click](javascript:foo)',
        html => !html.includes('<a ') && html.includes('file:///etc/passwd')],
    ['a code fence cannot be reached by inline formatting',
        '```\n**not bold**\n```',
        html => !html.includes('<b>')],
    ['empty input is empty output', '', html => html === ''],
];

let failed = 0;
for (const [label, input, check] of cases) {
    const html = toRich(input);
    const ok = check(html);
    console.log((ok ? 'PASS  ' : 'FAIL  ') + label);
    if (!ok) {
        failed++;
        console.log('        input: ' + JSON.stringify(input));
        console.log('        html : ' + html);
    }
}
console.log(failed === 0 ? `\nALL ${cases.length} PASS` : `\n${failed} of ${cases.length} FAILED`);
process.exit(failed === 0 ? 0 : 1);
