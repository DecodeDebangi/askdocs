// Help center search: instant article matches as you type; Enter (or "Ask") sends the
// question to the assistant, which answers from the same articles.
(function () {
  "use strict";
  const data = document.getElementById("search-index");
  const index = data ? JSON.parse(data.textContent) : [];

  function ask(q) {
    if (window.AskDocs) window.AskDocs.ask(q);
  }

  // Any element with data-ask opens the assistant (with its value as the question, if set).
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-ask]");
    if (!el) return;
    e.preventDefault();
    if (el.dataset.ask) ask(el.dataset.ask);
    else if (window.AskDocs) window.AskDocs.open();
  });

  function score(entry, words) {
    let s = 0;
    for (const w of words) {
      if (entry.title.toLowerCase().includes(w)) s += 3;
      else if (entry.text.includes(w)) s += 1;
      else return 0;
    }
    return s;
  }

  document.querySelectorAll(".search").forEach((box) => {
    const form = box.querySelector("form");
    const input = box.querySelector("input");
    const list = box.querySelector(".results");
    let items = [];
    let active = -1;

    function escape(s) {
      return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
    }

    function render() {
      const q = input.value.trim();
      const words = q.toLowerCase().split(/\s+/).filter((w) => w.length > 1);
      if (!q) { list.classList.remove("open"); items = []; return; }
      const hits = index.map((e) => [e, score(e, words)]).filter(([, s]) => s > 0)
        .sort((a, b) => b[1] - a[1]).slice(0, 5).map(([e]) => e);
      list.innerHTML = hits.map((e) => `<a href="/help/${e.slug}">${escape(e.title)} <small>${escape(e.category)}</small></a>`).join("")
        + `<button type="button" class="ask">Ask the assistant: “${escape(q)}”</button>`;
      items = [...list.children];
      active = -1;
      list.classList.add("open");
    }

    function move(delta) {
      if (!items.length) return;
      active = (active + delta + items.length) % items.length;
      items.forEach((el, i) => el.classList.toggle("active", i === active));
    }

    input.addEventListener("input", render);
    input.addEventListener("focus", render);
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
      else if (e.key === "Escape") { list.classList.remove("open"); }
    });
    list.addEventListener("click", (e) => {
      if (e.target.closest(".ask")) { e.preventDefault(); list.classList.remove("open"); ask(input.value.trim()); }
    });
    document.addEventListener("click", (e) => { if (!box.contains(e.target)) list.classList.remove("open"); });
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const q = input.value.trim();
      if (!q) return;
      list.classList.remove("open");
      if (active >= 0 && items[active].tagName === "A") { window.location = items[active].href; return; }
      ask(q);
    });
  });
})();
