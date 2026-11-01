/*
 * askdocs chat widget. Add to any page:
 *
 *   <script src="https://YOUR-API/widget.js" defer
 *           data-api="https://YOUR-API"
 *           data-title="Ask the docs"
 *           data-color="#2563eb"
 *           data-greeting="Hi! Ask me anything about our docs."></script>
 *
 * Plain JS in a Shadow DOM, so it works with any framework and the host page's CSS
 * can't break it (or be broken by it).
 */
(function () {
  "use strict";

  // ---------- Markdown (small, escape-first: model output is never inserted as raw HTML) ----------

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  function safeUrl(url) {
    return /^https?:\/\//i.test(url) ? url : "#";
  }

  function renderInline(text, sources) {
    // Odd segments are `inline code`: shown literally, so `arr[1]` never becomes a citation.
    return text.split(/(`[^`]+`)/).map((seg, i) => {
      if (i % 2 === 1) return `<code>${escapeHtml(seg.slice(1, -1))}</code>`;
      let html = escapeHtml(seg);
      html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, (_, label, url) =>
        `<a href="${safeUrl(url)}" target="_blank" rel="noopener">${label}</a>`);
      html = html.replace(/\[(\d+)\]/g, (match, n) => {
        const src = sources.find((s) => s.n === Number(n));
        if (!src) return match;
        return `<a class="cite" href="${escapeHtml(safeUrl(src.url))}" target="_blank" rel="noopener" title="${escapeHtml(sourceLabel(src))}">${n}</a>`;
      });
      return html;
    }).join("");
  }

  function renderMarkdown(md, sources) {
    const out = [];
    const parts = md.split(/```[^\n]*\n?/);
    parts.forEach((part, i) => {
      if (i % 2 === 1) {
        out.push(`<pre><code>${escapeHtml(part.replace(/\n$/, ""))}</code></pre>`);
        return;
      }
      let list = null;
      const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
      let para = [];
      const flushPara = () => { if (para.length) { out.push(`<p>${para.map((l) => renderInline(l, sources)).join("<br>")}</p>`); para = []; } };
      for (const line of part.split("\n")) {
        const bullet = line.match(/^\s*[-*]\s+(.*)$/);
        const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
        const heading = line.match(/^#{1,6}\s+(.*)$/);
        if (bullet || numbered) {
          flushPara();
          const type = bullet ? "ul" : "ol";
          if (list !== type) { closeList(); out.push(`<${type}>`); list = type; }
          out.push(`<li>${renderInline((bullet || numbered)[1], sources)}</li>`);
        } else if (heading) {
          flushPara(); closeList();
          out.push(`<p><strong>${renderInline(heading[1], sources)}</strong></p>`);
        } else if (!line.trim()) {
          flushPara(); closeList();
        } else {
          closeList();
          para.push(line);
        }
      }
      flushPara(); closeList();
    });
    return out.join("");
  }

  function sourceLabel(src) {
    return src.section ? `${src.title} › ${src.section}` : src.title;
  }

  // ---------- Server-sent events over POST (EventSource only supports GET) ----------

  async function* streamEvents(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const data = block.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)).join("\n");
        if (data) yield JSON.parse(data);
      }
    }
  }

  // Exposed for tests; the widget itself only needs the DOM below.
  const api = { escapeHtml, renderMarkdown, streamEvents };
  if (typeof module !== "undefined") module.exports = api;
  if (typeof document === "undefined") return;

  // ---------- Widget ----------

  const script = document.currentScript;
  const cfg = {
    api: (script && script.dataset.api) || new URL(script.src).origin,
    title: (script && script.dataset.title) || "Ask the docs",
    color: (script && script.dataset.color) || "#2563eb",
    greeting: (script && script.dataset.greeting) || "Hi! Ask me anything about the docs. I'll answer with links to the exact sections.",
  };

  const STYLE = `
    :host { all: initial; }
    * { box-sizing: border-box; }
    .root {
      --accent: ${cfg.color};
      --bg: #ffffff; --fg: #111827; --muted: #6b7280; --border: #e5e7eb;
      --bubble: #f3f4f6; --code: #f6f8fa;
      font: 14px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      color: var(--fg);
    }
    @media (prefers-color-scheme: dark) {
      .root { --bg: #111827; --fg: #f3f4f6; --muted: #9ca3af; --border: #374151; --bubble: #1f2937; --code: #0b1220; }
    }
    .launcher {
      position: fixed; right: 20px; bottom: 20px; width: 56px; height: 56px; border-radius: 50%;
      border: 0; background: var(--accent); color: #fff; cursor: pointer; z-index: 2147483000;
      box-shadow: 0 6px 20px rgba(0,0,0,.2); display: grid; place-items: center;
    }
    .launcher:focus-visible { outline: 3px solid var(--fg); outline-offset: 2px; }
    .panel {
      position: fixed; right: 20px; bottom: 88px; width: 380px; height: min(600px, calc(100vh - 120px));
      background: var(--bg); border: 1px solid var(--border); border-radius: 14px; z-index: 2147483000;
      box-shadow: 0 12px 40px rgba(0,0,0,.18); display: none; flex-direction: column; overflow: hidden;
    }
    .panel.open { display: flex; }
    @media (max-width: 480px) {
      .panel { right: 0; bottom: 0; width: 100vw; height: 100dvh; border-radius: 0; }
      .panel.open + .launcher { display: none; }
    }
    header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid var(--border); }
    header h2 { margin: 0; font-size: 15px; font-weight: 600; }
    header button { background: none; border: 0; color: var(--muted); cursor: pointer; font-size: 20px; line-height: 1; padding: 4px; }
    .log { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
    .msg { max-width: 88%; padding: 10px 12px; border-radius: 12px; overflow-wrap: anywhere; }
    .msg.user { align-self: flex-end; background: var(--accent); color: #fff; border-bottom-right-radius: 4px; }
    .msg.bot { align-self: flex-start; background: var(--bubble); border-bottom-left-radius: 4px; }
    .msg p { margin: 0 0 8px; } .msg p:last-child { margin-bottom: 0; }
    .msg ul, .msg ol { margin: 0 0 8px; padding-left: 20px; }
    .msg code { font: 12.5px ui-monospace, SFMono-Regular, Menlo, monospace; background: var(--code); padding: 1px 4px; border-radius: 4px; }
    .msg pre { background: var(--code); padding: 10px; border-radius: 8px; overflow-x: auto; margin: 0 0 8px; }
    .msg pre code { padding: 0; background: none; }
    .msg a { color: var(--accent); }
    .cite { display: inline-block; min-width: 18px; padding: 0 4px; margin: 0 1px; border-radius: 9px; font-size: 11px; line-height: 18px;
            text-align: center; text-decoration: none; background: var(--accent); color: #fff !important; vertical-align: 1px; }
    .sources { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border); font-size: 12.5px; }
    .sources a { display: block; color: var(--muted); text-decoration: none; padding: 2px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .sources a:hover { color: var(--accent); }
    .sources b { color: var(--accent); margin-right: 4px; }
    .note { font-size: 12px; color: var(--muted); margin-top: 6px; }
    .typing span { display: inline-block; width: 6px; height: 6px; margin-right: 3px; border-radius: 50%; background: var(--muted); animation: blink 1.2s infinite; }
    .typing span:nth-child(2) { animation-delay: .2s; } .typing span:nth-child(3) { animation-delay: .4s; }
    @keyframes blink { 0%, 80%, 100% { opacity: .25; } 40% { opacity: 1; } }
    @media (prefers-reduced-motion: reduce) { .typing span { animation: none; } }
    form { display: flex; gap: 8px; padding: 12px; border-top: 1px solid var(--border); }
    textarea { flex: 1; resize: none; border: 1px solid var(--border); border-radius: 10px; padding: 9px 10px; font: inherit; color: var(--fg);
               background: var(--bg); max-height: 120px; }
    textarea:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
    form button { border: 0; border-radius: 10px; padding: 0 14px; background: var(--accent); color: #fff; font: inherit; font-weight: 600; cursor: pointer; }
    form button:disabled { opacity: .5; cursor: default; }
    .footer { text-align: center; font-size: 11px; color: var(--muted); padding: 0 0 8px; }
  `;

  const ICON_CHAT = '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
  const ICON_CLOSE = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>';

  function mount() {
    const host = document.createElement("div");
    host.id = "askdocs-widget";
    document.body.appendChild(host);
    const shadow = host.attachShadow({ mode: "open" });
    shadow.innerHTML = `
      <style>${STYLE}</style>
      <div class="root">
        <section class="panel" role="dialog" aria-label="${escapeHtml(cfg.title)}">
          <header><h2>${escapeHtml(cfg.title)}</h2><button type="button" class="close" aria-label="Close chat">×</button></header>
          <div class="log" aria-live="polite"></div>
          <form>
            <textarea rows="1" placeholder="Ask a question…" aria-label="Your question" maxlength="2000"></textarea>
            <button type="submit">Send</button>
          </form>
          <div class="footer">Answers come from the docs and may be incomplete.</div>
        </section>
        <button type="button" class="launcher" aria-label="Open chat" aria-expanded="false">${ICON_CHAT}</button>
      </div>`;

    const $ = (sel) => shadow.querySelector(sel);
    const panel = $(".panel"), launcher = $(".launcher"), log = $(".log");
    const form = $("form"), input = $("textarea"), send = $("form button");
    const history = [];
    let busy = false;

    function setOpen(open) {
      panel.classList.toggle("open", open);
      launcher.innerHTML = open ? ICON_CLOSE : ICON_CHAT;
      launcher.setAttribute("aria-expanded", String(open));
      launcher.setAttribute("aria-label", open ? "Close chat" : "Open chat");
      if (open) {
        if (!log.children.length) addMessage("bot").body.innerHTML = renderMarkdown(cfg.greeting, []);
        input.focus();
      }
    }

    function addMessage(role) {
      const el = document.createElement("div");
      el.className = `msg ${role}`;
      const body = document.createElement("div");
      el.appendChild(body);
      log.appendChild(el);
      log.scrollTop = log.scrollHeight;
      return { el, body };
    }

    function renderSources(el, sources, cited) {
      const shown = sources.filter((s) => cited.includes(s.n));
      if (!shown.length) return;
      const box = document.createElement("div");
      box.className = "sources";
      box.innerHTML = shown.map((s) =>
        `<a href="${escapeHtml(safeUrl(s.url))}" target="_blank" rel="noopener" title="${escapeHtml(sourceLabel(s))}"><b>${s.n}</b>${escapeHtml(sourceLabel(s))}</a>`).join("");
      el.appendChild(box);
    }

    async function ask(question) {
      busy = true; send.disabled = true;
      addMessage("user").body.textContent = question;
      const { el, body } = addMessage("bot");
      body.innerHTML = '<span class="typing" aria-label="Thinking"><span></span><span></span><span></span></span>';

      let text = "", sources = [];
      try {
        const res = await fetch(`${cfg.api}/chat/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question, history: history.slice(-6) }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        for await (const event of streamEvents(res)) {
          if (event.type === "sources") sources = event.sources;
          else if (event.type === "token") {
            text += event.text;
            body.innerHTML = renderMarkdown(text, sources);
            log.scrollTop = log.scrollHeight;
          } else if (event.type === "done") {
            body.innerHTML = renderMarkdown(event.answer, sources);
            if (event.answered) renderSources(el, sources, event.cited);
            if (event.handoff) {
              const note = document.createElement("div");
              note.className = "note";
              note.textContent = "Passed to the team";
              el.appendChild(note);
            }
            history.push({ role: "user", content: question }, { role: "assistant", content: event.answer });
          }
        }
      } catch (err) {
        body.textContent = "Sorry, I couldn't reach the server. Please try again.";
      } finally {
        busy = false; send.disabled = false;
        log.scrollTop = log.scrollHeight;
        input.focus();
      }
    }

    launcher.addEventListener("click", () => setOpen(!panel.classList.contains("open")));
    $(".close").addEventListener("click", () => { setOpen(false); launcher.focus(); });
    shadow.addEventListener("keydown", (e) => { if (e.key === "Escape" && panel.classList.contains("open")) { setOpen(false); launcher.focus(); } });
    input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = `${input.scrollHeight}px`; });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
    });
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const q = input.value.trim();
      if (!q || busy) return;
      input.value = ""; input.style.height = "auto";
      ask(q);
    });

    // Lets the host page open the chat or send a question, e.g. from an "Ask AI" button.
    window.AskDocs = {
      open: () => setOpen(true),
      close: () => setOpen(false),
      ask: (q) => { setOpen(true); if (!busy && q) ask(String(q)); },
    };
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
