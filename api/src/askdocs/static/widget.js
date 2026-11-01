/*
 * askdocs chat widget. Add to any page:
 *
 *   <script src="https://YOUR-API/widget.js" defer
 *           data-api="https://YOUR-API"
 *           data-title="Ask the docs"
 *           data-subtitle="Answers from our help center"
 *           data-color="#2563eb"
 *           data-label="Ask a question"
 *           data-greeting="Hi! Ask me anything about our docs."
 *           data-suggestions="First question|Second question"></script>
 *
 * Add data-target="#some-element" to show the chat inside that element instead of as a
 * floating button. Each answer is also announced to the page as an `askdocs:answer` event
 * (detail: question, sources, done), so a page can show how the answer was reached.
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
  const data = (script && script.dataset) || {};
  const cfg = {
    api: data.api || new URL(script.src).origin,
    title: data.title || "Ask the docs",
    subtitle: data.subtitle || "Answers from our help center",
    color: data.color || "#2563eb",
    label: data.label || "Ask a question",
    greeting: data.greeting || "Hi! Ask me anything about the docs. I'll answer with links to the exact sections.",
    suggestions: (data.suggestions || "").split("|").map((s) => s.trim()).filter(Boolean).slice(0, 4),
    target: data.target ? document.querySelector(data.target) : null,
  };

  const STYLE = `
    :host { all: initial; }
    * { box-sizing: border-box; }
    .root {
      --accent: ${cfg.color};
      --on-accent: #fff;
      --bg: #ffffff; --fg: #17201b; --muted: #6a756e; --line: #e8e5dd; --soft: #f5f3ee; --code: #f4f2ec;
      --shadow: 0 2px 6px rgba(0,0,0,.06), 0 24px 64px rgba(0,0,0,.18);
      font: 14.5px/1.55 "Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      color: var(--fg);
      -webkit-font-smoothing: antialiased;
    }
    @media (prefers-color-scheme: dark) {
      .root { --bg: #151b18; --fg: #edf1ee; --muted: #9aa69f; --line: #28322d; --soft: #1c2420; --code: #0f1412;
              --shadow: 0 2px 6px rgba(0,0,0,.4), 0 24px 64px rgba(0,0,0,.5); }
    }
    button { font: inherit; }
    .launcher {
      position: fixed; right: 20px; bottom: 20px; z-index: 2147483000; height: 52px; padding: 0 20px 0 16px;
      border: 0; border-radius: 999px; background: var(--accent); color: var(--on-accent); cursor: pointer;
      display: flex; align-items: center; gap: 10px; font-weight: 600; font-size: 15px;
      box-shadow: 0 4px 14px rgba(0,0,0,.18), 0 1px 3px rgba(0,0,0,.12); transition: transform .15s;
    }
    .launcher:hover { transform: translateY(-1px); }
    .launcher:focus-visible { outline: 3px solid var(--fg); outline-offset: 3px; }
    .launcher.open { width: 52px; padding: 0; justify-content: center; }
    .launcher.open .label { display: none; }
    .panel {
      position: fixed; right: 20px; bottom: 84px; z-index: 2147483000; width: 400px; height: min(640px, calc(100vh - 110px));
      background: var(--bg); border: 1px solid var(--line); border-radius: 18px; box-shadow: var(--shadow);
      display: flex; flex-direction: column; overflow: hidden;
      opacity: 0; transform: translateY(12px) scale(.98); transform-origin: bottom right; pointer-events: none; visibility: hidden;
      transition: opacity .18s ease, transform .18s ease, visibility 0s linear .18s;
    }
    .panel.open { opacity: 1; transform: none; pointer-events: auto; visibility: visible; transition: opacity .18s ease, transform .18s ease; }
    @media (prefers-reduced-motion: reduce) { .panel, .panel.open { transition: none; } .launcher { transition: none; } }
    .inline, .inline .panel { height: 100%; }
    .inline .panel { position: relative; right: auto; bottom: auto; z-index: auto; width: 100%; opacity: 1; transform: none; pointer-events: auto; visibility: visible; transition: none; }
    .inline .launcher, .inline .close { display: none; }
    @media (max-width: 480px) {
      .root:not(.inline) .panel { right: 0; bottom: 0; width: 100vw; height: 100dvh; border-radius: 0; border: 0; }
      .launcher { padding: 0; width: 56px; height: 56px; justify-content: center; }
      .launcher .label { display: none; }
      .panel.open ~ .launcher { display: none; }
    }
    header { display: flex; align-items: center; gap: 12px; padding: 14px 14px 14px 16px; border-bottom: 1px solid var(--line); }
    .avatar { flex: none; width: 38px; height: 38px; border-radius: 12px; background: var(--accent); color: var(--on-accent); display: grid; place-items: center; }
    .who { flex: 1; min-width: 0; }
    .who h2 { margin: 0; font-size: 15px; font-weight: 600; line-height: 1.3; }
    .who p { margin: 0; font-size: 12.5px; color: var(--muted); }
    .icon-btn { flex: none; width: 34px; height: 34px; border-radius: 10px; border: 0; background: none; color: var(--muted); cursor: pointer; display: grid; place-items: center; }
    .icon-btn:hover { background: var(--soft); color: var(--fg); }
    .log { flex: 1; overflow-y: auto; padding: 18px 16px 8px; display: flex; flex-direction: column; gap: 14px; scroll-behavior: smooth; }
    .row { display: flex; gap: 10px; align-items: flex-start; }
    .row.user { justify-content: flex-end; }
    .row .mini { flex: none; width: 26px; height: 26px; border-radius: 8px; background: color-mix(in srgb, var(--accent) 14%, transparent); color: var(--accent); display: grid; place-items: center; margin-top: 2px; }
    .msg { max-width: 86%; overflow-wrap: anywhere; }
    .msg.user { background: var(--accent); color: var(--on-accent); padding: 9px 13px; border-radius: 16px 16px 4px 16px; }
    .msg.bot { background: var(--soft); padding: 11px 14px; border-radius: 4px 16px 16px 16px; }
    .msg p { margin: 0 0 8px; } .msg p:last-child { margin-bottom: 0; }
    .msg ul, .msg ol { margin: 0 0 8px; padding-left: 20px; } .msg li { margin: 2px 0; }
    .msg code { font: 12.5px ui-monospace, SFMono-Regular, Menlo, monospace; background: var(--code); padding: 1px 5px; border-radius: 5px; }
    .msg pre { background: var(--code); padding: 10px 12px; border-radius: 10px; overflow-x: auto; margin: 0 0 8px; }
    .msg pre code { padding: 0; background: none; }
    .msg a { color: var(--accent); }
    .msg.user a { color: inherit; }
    .cite { display: inline-grid; place-items: center; min-width: 17px; height: 17px; padding: 0 4px; margin: 0 1px; border-radius: 6px; font-size: 10.5px; font-weight: 600;
            text-decoration: none; background: color-mix(in srgb, var(--accent) 16%, transparent); color: var(--accent) !important; vertical-align: 2px; }
    .cite:hover { background: var(--accent); color: var(--on-accent) !important; }
    .sources { margin-top: 10px; display: grid; gap: 6px; }
    .sources b { font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); font-weight: 600; }
    .sources a { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: 10px; background: var(--bg); border: 1px solid var(--line); text-decoration: none; color: var(--fg); font-size: 13px; }
    .sources a:hover { border-color: var(--accent); }
    .sources .n { flex: none; min-width: 18px; height: 18px; border-radius: 6px; display: grid; place-items: center; font-size: 11px; font-weight: 600; background: color-mix(in srgb, var(--accent) 16%, transparent); color: var(--accent); }
    .sources .t { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .sources .t span { color: var(--muted); }
    .note { display: inline-flex; align-items: center; gap: 6px; margin-top: 10px; font-size: 12.5px; color: var(--muted); background: var(--bg); border: 1px solid var(--line); padding: 4px 10px; border-radius: 999px; }
    .chips { display: flex; flex-wrap: wrap; gap: 8px; padding-left: 36px; }
    .chips button { border: 1px solid var(--line); background: var(--bg); color: var(--fg); border-radius: 999px; padding: 7px 12px; font-size: 13.5px; cursor: pointer; text-align: left; }
    .chips button:hover { border-color: var(--accent); color: var(--accent); }
    .typing { display: inline-flex; gap: 4px; padding: 4px 0; }
    .typing span { width: 6px; height: 6px; border-radius: 50%; background: var(--muted); animation: blink 1.2s infinite; }
    .typing span:nth-child(2) { animation-delay: .2s; } .typing span:nth-child(3) { animation-delay: .4s; }
    @keyframes blink { 0%, 80%, 100% { opacity: .25; } 40% { opacity: 1; } }
    @media (prefers-reduced-motion: reduce) { .typing span { animation: none; } }
    form { margin: 8px 12px 0; display: flex; align-items: flex-end; gap: 8px; border: 1px solid var(--line); border-radius: 14px; padding: 6px 6px 6px 12px; background: var(--bg); }
    form:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 15%, transparent); }
    textarea { flex: 1; resize: none; border: 0; outline: none; background: transparent; color: var(--fg); font: inherit; padding: 7px 0; max-height: 120px; }
    textarea::placeholder { color: var(--muted); }
    .send { flex: none; width: 36px; height: 36px; border: 0; border-radius: 10px; background: var(--accent); color: var(--on-accent); cursor: pointer; display: grid; place-items: center; }
    .send:disabled { opacity: .35; cursor: default; }
    .footer { text-align: center; font-size: 11.5px; color: var(--muted); padding: 8px 12px 12px; }
  `;

  const svg = (d, size = 20, extra = "") => `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${d}</svg>`;
  const ICON_CHAT = svg('<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>', 22);
  const ICON_CLOSE = svg('<path d="M18 6 6 18M6 6l12 12"/>', 20);
  const ICON_SPARK = svg('<path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>', 18);
  const ICON_SEND = svg('<path d="M12 19V5M5 12l7-7 7 7"/>', 18);
  const ICON_PERSON = svg('<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>', 13);
  const ICON_RESET = svg('<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>', 17);

  function mount() {
    const inline = Boolean(cfg.target);
    const host = document.createElement("div");
    host.id = "askdocs-widget";
    if (inline) host.style.cssText = "display:block;height:100%";
    (cfg.target || document.body).appendChild(host);
    const shadow = host.attachShadow({ mode: "open" });
    shadow.innerHTML = `
      <style>${STYLE}</style>
      <div class="root${inline ? " inline" : ""}">
        <section class="panel${inline ? " open" : ""}" role="${inline ? "region" : "dialog"}" aria-label="${escapeHtml(cfg.title)}">
          <header>
            <div class="avatar">${ICON_CHAT}</div>
            <div class="who"><h2>${escapeHtml(cfg.title)}</h2><p>${escapeHtml(cfg.subtitle)}</p></div>
            <button type="button" class="icon-btn reset" aria-label="Start a new conversation" title="New conversation">${ICON_RESET}</button>
            <button type="button" class="icon-btn close" aria-label="Close chat">${ICON_CLOSE}</button>
          </header>
          <div class="log" aria-live="polite"></div>
          <form>
            <textarea rows="1" placeholder="Ask a question…" aria-label="Your question" maxlength="2000"></textarea>
            <button type="submit" class="send" aria-label="Send" disabled>${ICON_SEND}</button>
          </form>
          <div class="footer">AI answers from our help center. Check the linked articles for details.</div>
        </section>
        <button type="button" class="launcher" aria-label="Open chat" aria-expanded="false">${ICON_CHAT}<span class="label">${escapeHtml(cfg.label)}</span></button>
      </div>`;

    const $ = (sel) => shadow.querySelector(sel);
    const panel = $(".panel"), launcher = $(".launcher"), log = $(".log");
    const form = $("form"), input = $("textarea"), send = $(".send");
    let history = [];
    let busy = false;

    function scrollDown() { log.scrollTop = log.scrollHeight; }

    // Inline, the chat sits in the page: focusing it on a phone would pop up the keyboard.
    function focusInput() {
      if (!inline || matchMedia("(pointer: fine)").matches) input.focus({ preventScroll: inline });
    }

    function welcome() {
      const { body } = addMessage("bot");
      body.innerHTML = renderMarkdown(cfg.greeting, []);
      if (cfg.suggestions.length) {
        const chips = document.createElement("div");
        chips.className = "chips";
        cfg.suggestions.forEach((q) => {
          const b = document.createElement("button");
          b.type = "button";
          b.textContent = q;
          b.addEventListener("click", () => { chips.remove(); ask(q); });
          chips.appendChild(b);
        });
        log.appendChild(chips);
      }
    }

    function setOpen(open) {
      panel.classList.toggle("open", open);
      launcher.classList.toggle("open", open);
      launcher.innerHTML = open ? ICON_CLOSE : `${ICON_CHAT}<span class="label">${escapeHtml(cfg.label)}</span>`;
      launcher.setAttribute("aria-expanded", String(open));
      launcher.setAttribute("aria-label", open ? "Close chat" : "Open chat");
      if (open) {
        if (!log.children.length) welcome();
        if (!inline) setTimeout(() => input.focus(), 50);
      }
    }

    function addMessage(role) {
      const row = document.createElement("div");
      row.className = `row ${role}`;
      if (role === "bot") row.innerHTML = `<div class="mini">${ICON_SPARK}</div>`;
      const el = document.createElement("div");
      el.className = `msg ${role}`;
      const body = document.createElement("div");
      el.appendChild(body);
      row.appendChild(el);
      log.appendChild(row);
      scrollDown();
      return { el, body };
    }

    function renderSources(el, sources, cited) {
      const shown = sources.filter((s) => cited.includes(s.n));
      if (!shown.length) return;
      const box = document.createElement("div");
      box.className = "sources";
      box.innerHTML = "<b>Sources</b>" + shown.map((s) =>
        `<a href="${escapeHtml(safeUrl(s.url))}" target="_blank" rel="noopener" title="${escapeHtml(sourceLabel(s))}">` +
        `<span class="n">${s.n}</span><span class="t">${escapeHtml(s.title)}${s.section ? ` <span>› ${escapeHtml(s.section)}</span>` : ""}</span></a>`).join("");
      el.appendChild(box);
    }

    async function ask(question) {
      busy = true; send.disabled = true;
      shadow.querySelectorAll(".chips").forEach((c) => c.remove());
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
            scrollDown();
          } else if (event.type === "done") {
            body.innerHTML = renderMarkdown(event.answer, sources);
            if (event.answered) renderSources(el, sources, event.cited);
            if (event.handoff) {
              const note = document.createElement("div");
              note.className = "note";
              note.innerHTML = `${ICON_PERSON}<span>Passed to our support team</span>`;
              el.appendChild(note);
            }
            history.push({ role: "user", content: question }, { role: "assistant", content: event.answer });
            window.dispatchEvent(new CustomEvent("askdocs:answer", { detail: { question, sources, done: event } }));
          }
        }
      } catch (err) {
        body.textContent = "Sorry, I couldn't connect. Please try again in a moment.";
      } finally {
        busy = false;
        send.disabled = !input.value.trim();
        scrollDown();
        focusInput();
      }
    }

    launcher.addEventListener("click", () => setOpen(!panel.classList.contains("open")));
    $(".close").addEventListener("click", () => { setOpen(false); launcher.focus(); });
    $(".reset").addEventListener("click", () => {
      if (busy) return;
      history = []; log.innerHTML = ""; welcome(); focusInput();
      window.dispatchEvent(new CustomEvent("askdocs:reset"));
    });
    shadow.addEventListener("keydown", (e) => { if (!inline && e.key === "Escape" && panel.classList.contains("open")) { setOpen(false); launcher.focus(); } });
    input.addEventListener("input", () => {
      input.style.height = "auto"; input.style.height = `${input.scrollHeight}px`;
      send.disabled = busy || !input.value.trim();
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
    });
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const q = input.value.trim();
      if (!q || busy) return;
      input.value = ""; input.style.height = "auto"; send.disabled = true;
      ask(q);
    });

    // Lets the host page open the chat or send a question, e.g. from an "Ask AI" button.
    if (inline) welcome();
    window.AskDocs = {
      open: () => setOpen(true),
      close: () => setOpen(false),
      ask: (q) => { setOpen(true); if (!busy && q) ask(String(q)); },
      busy: () => busy,
    };
  }

  function start() {
    mount();
    // Deep link: #askdocs-open opens the chat, #askdocs-ask=<question> also asks it.
    const m = location.hash.match(/^#askdocs-(open|ask=(.+))$/);
    if (m) m[2] ? window.AskDocs.ask(decodeURIComponent(m[2])) : window.AskDocs.open();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
