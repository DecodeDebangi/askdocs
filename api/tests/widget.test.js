// Run with: node --test tests/
const { test } = require("node:test");
const assert = require("node:assert/strict");
const { renderMarkdown, streamEvents } = require("../src/askdocs/static/widget.js");

const SOURCES = [{ n: 1, title: "Storage", section: "Limits", url: "https://docs.example.com/storage#limits" }];

test("model output can't inject HTML", () => {
  const html = renderMarkdown('<img src=x onerror="alert(1)"> **hi**', []);
  assert.ok(!html.includes("<img"));
  assert.ok(html.includes("&lt;img"));
  assert.ok(html.includes("<strong>hi</strong>"));
});

test("citations become links to their source, unknown numbers stay text", () => {
  const html = renderMarkdown("The limit is 50 MB [1]. See also [7].", SOURCES);
  assert.match(html, /<a class="cite" href="https:\/\/docs.example.com\/storage#limits"[^>]*>1<\/a>/);
  assert.ok(html.includes("[7]"));
});

test("brackets inside inline code are not citations", () => {
  const html = renderMarkdown("Use `rows[1]` here [1].", SOURCES);
  assert.ok(html.includes("<code>rows[1]</code>"));
  assert.equal((html.match(/class="cite"/g) || []).length, 1);
});

test("code fences are escaped and kept verbatim", () => {
  const html = renderMarkdown("Run:\n```sql\nselect '<b>' from t; -- [1]\n```\nDone [1].", SOURCES);
  assert.ok(html.includes("<pre><code>select &#39;&lt;b&gt;&#39; from t; -- [1]</code></pre>"));
  assert.ok(html.endsWith("Done <a class=\"cite\" href=\"https://docs.example.com/storage#limits\" target=\"_blank\" rel=\"noopener\" title=\"Storage › Limits\">1</a>.</p>"));
});

test("lists and paragraphs", () => {
  const html = renderMarkdown("Steps:\n1. Create\n2. Deploy\n\n- a\n- b", []);
  assert.equal(html, "<p>Steps:</p><ol><li>Create</li><li>Deploy</li></ol><ul><li>a</li><li>b</li></ul>");
});

test("javascript: links are neutralised", () => {
  const html = renderMarkdown("[click](javascript:alert(1))", []);
  assert.ok(!html.includes('href="javascript'));
});

test("parses server-sent events split across network chunks", async () => {
  const wire = 'event: sources\ndata: {"type":"sources","sources":[]}\n\nevent: token\ndata: {"type":"token","text":"Hi"}\n\nevent: done\ndata: {"type":"done"}\n\n';
  const pieces = [wire.slice(0, 17), wire.slice(17, 70), wire.slice(70)];
  const response = {
    body: {
      getReader() {
        let i = 0;
        return { read: async () => (i < pieces.length ? { done: false, value: new TextEncoder().encode(pieces[i++]) } : { done: true }) };
      },
    },
  };
  const types = [];
  for await (const e of streamEvents(response)) types.push(e.type);
  assert.deepEqual(types, ["sources", "token", "done"]);
});
