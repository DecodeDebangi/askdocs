// Product page demo: test questions feed the inline chat, and each answer is broken down
// in the "How it answered" panel from the widget's askdocs:answer event.
(function () {
  "use strict";
  const trace = document.getElementById("trace");
  const chat = document.getElementById("chat");
  const empty = trace.innerHTML;

  const OUTCOMES = {
    answered: ["ok", "Answered from the help center", (used, found) =>
      `Written only from ${used === 1 ? "the 1 section" : `${used} sections`} it cites, out of ${found} it found.`],
    escalated: ["stop", "Passed straight to a person", () => "Billing, legal and account problems go to the team. The AI never sees them."],
    no_sources: ["stop", "Refused: nothing relevant found", () => "No help-center section matched closely enough, so it didn't guess."],
    no_answer: ["stop", "Refused: the sections don't say", () => "It found related sections, but none answered this question, so it didn't guess."],
    error: ["stop", "AI provider busy", () => "The language model didn't respond. Nothing was made up; try again in a moment."],
  };

  function escape(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  }

  // Cosine similarity is already 0..1; reranker scores are logits, so squash them.
  function strength(score) {
    const v = score >= 0 && score <= 1 ? score : 1 / (1 + Math.exp(-score));
    return Math.round(v * 100);
  }

  function seconds(ms) {
    return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
  }

  function render({ question, sources, done }) {
    const [kind, title, why] = OUTCOMES[done.reason] || OUTCOMES.error;
    const cited = done.cited || [];
    let html = `<p class="t-q">“${escape(question)}”</p>
      <div class="outcome ${kind}"><span class="dot"></span><div><b>${title}</b>${why(cited.length, sources.length)}</div></div>`;

    if (sources.length) {
      html += `<div class="t-h">Sections found (${sources.length})</div><ul class="hits">` + sources.map((s) => {
        const used = cited.includes(s.n);
        const where = s.section ? `${s.title} › ${s.section}` : s.title;
        return `<li class="hit${used ? " cited" : ""}"><a href="${escape(new URL(s.url).pathname + new URL(s.url).hash)}" target="_blank" rel="noopener">` +
          `<span>${escape(where)}</span><span class="tag">${used ? `cited [${s.n}]` : "not used"}</span></a>` +
          `<div class="bar" title="Match ${strength(s.score)}%"><i style="width:${strength(s.score)}%"></i></div></li>`;
      }).join("") + "</ul>";
    } else if (done.reason === "escalated") {
      html += `<div class="t-h">Sections found</div><p style="margin:0;color:var(--muted);font-size:14px">None searched: the question matched the hand-off rules first.</p>`;
    }

    const t = done.timings || {};
    if (done.reason !== "escalated") {
      html += `<div class="t-h">Time</div><div class="times">
        <div><b>${seconds(t.retrieve_ms || 0)}</b>search</div><div><b>${seconds(t.llm_ms || 0)}</b>writing the answer</div></div>`;
    }

    const test = [...document.querySelectorAll(".dq")].find((b) => b.dataset.ask === question);
    if (test) {
      html += `<div class="t-h">${test.dataset.href ? "What the help center says" : "Expected"}</div><div class="expected">${escape(test.dataset.expect)}` +
        (test.dataset.href ? `<br><a href="${escape(test.dataset.href)}" target="_blank" rel="noopener">Check: ${escape(test.dataset.title)} →</a>` : "") + "</div>";
    }
    trace.innerHTML = html;
  }

  window.addEventListener("askdocs:answer", (e) => render(e.detail));
  window.addEventListener("askdocs:reset", () => {
    trace.innerHTML = empty;
    document.querySelectorAll(".dq.active").forEach((b) => b.classList.remove("active"));
  });

  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".dq");
    if (!btn || !window.AskDocs || window.AskDocs.busy()) return;
    document.querySelectorAll(".dq.active").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    trace.innerHTML = `<p class="t-q">“${escape(btn.dataset.ask)}”</p><div class="trace-empty">Searching the help center…</div>`;
    // On narrow screens the questions sit below the chat: bring the chat into view.
    const r = chat.getBoundingClientRect();
    if (r.top < 0 || r.bottom > innerHeight) chat.scrollIntoView({ behavior: "smooth", block: "start" });
    window.AskDocs.ask(btn.dataset.ask);
  });
})();
