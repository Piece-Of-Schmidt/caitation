"use strict";

/* ================================================================ helpers */

const $ = (sel, root = document) => root.querySelector(sel);

const els = {
  form: $("#searchForm"),
  query: $("#queryInput"),
  submit: $("#submitBtn"),
  modeHint: $("#modeHint"),
  filterToggle: $("#filterToggle"),
  filterPanel: $("#filterPanel"),
  filterCount: $("#filterCount"),
  results: $("#results"),
  answerBox: $("#answerBox"),
  chatLog: $("#chatLog"),
  statusPill: $("#indexStatus"),
  statusText: $("#indexStatus .status-text"),
  progress: $("#indexProgress"),
  progressBar: $("#indexProgress .index-progress-bar"),
  reindexBtn: $("#reindexBtn"),
  tooltip: $("#tooltip"),
  toast: $("#toast"),
  views: {
    search: $("#view-search"),
    dashboard: $("#view-dashboard"),
    duplicates: $("#view-duplicates"),
  },
};

const HTML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => HTML_ESCAPES[c]);
}

// Zotero titles may carry rich-text markup (<i>, <b>, <sub>, <sup>, <span class="nocase">):
// render the harmless formatting tags, drop the rest.
function formatTitle(title) {
  return escapeHtml(title || "(ohne Titel)")
    .replace(/&lt;(\/?)(i|b|sub|sup)&gt;/g, "<$1$2>")
    .replace(/&lt;\/?span[^&]*?&gt;/g, "");
}

function plainTitle(title) {
  return String(title ?? "").replace(/<[^>]+>/g, "");
}

function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function icon(name, cls = "icon") {
  return `<svg class="${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
}

async function api(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail; } catch { /* not JSON */ }
    throw new Error(detail || `Serverfehler (HTTP ${res.status})`);
  }
  return res.json();
}

function isAbort(err) {
  return err && err.name === "AbortError";
}

let toastTimer;
function toast(message) {
  els.toast.textContent = message;
  els.toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { els.toast.hidden = true; }, 2200);
}

function showTooltip(html, event) {
  const tip = els.tooltip;
  tip.innerHTML = html;
  tip.hidden = false;
  const pad = 14;
  const { innerWidth: vw, innerHeight: vh } = window;
  const rect = tip.getBoundingClientRect();
  let x = event.clientX + pad;
  let y = event.clientY + pad;
  if (x + rect.width > vw - 8) x = event.clientX - rect.width - pad;
  if (y + rect.height > vh - 8) y = event.clientY - rect.height - pad;
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${Math.max(8, y)}px`;
}

function hideTooltip() {
  els.tooltip.hidden = true;
}

const storage = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* private mode */ } },
};

/* ---------------------------------------------------------------- formatting */

const TYPE_LABELS = {
  journalArticle: "Artikel",
  book: "Buch",
  bookSection: "Buchkapitel",
  conferencePaper: "Konferenzbeitrag",
  report: "Bericht",
  thesis: "Abschlussarbeit",
  preprint: "Preprint",
  webpage: "Webseite",
  newspaperArticle: "Zeitungsartikel",
  magazineArticle: "Magazinartikel",
  blogPost: "Blogbeitrag",
  document: "Dokument",
  manuscript: "Manuskript",
  presentation: "Präsentation",
  dataset: "Datensatz",
  encyclopediaArticle: "Lexikonartikel",
  dictionaryEntry: "Wörterbucheintrag",
  interview: "Interview",
  letter: "Brief",
  film: "Film",
  podcast: "Podcast",
  videoRecording: "Video",
  statute: "Gesetz",
  case: "Urteil",
  standard: "Norm",
};

const typeLabel = (t) => TYPE_LABELS[t] || t || "";

function shortAuthors(authors) {
  if (!authors) return "";
  const names = authors.split(", ").filter(Boolean);
  return names.length > 3 ? `${names.slice(0, 2).join(", ")} et al.` : names.join(", ");
}

const numberFmt = new Intl.NumberFormat("de-DE");

const STOPWORDS = new Set((
  "der die das den dem des ein eine einer eines einem einen und oder aber mit von für auf aus bei " +
  "ist sind war waren wird werden wie was wer wo warum welche welcher welches über unter nach vor " +
  "zum zur im in an als auch nicht noch nur sich sie er es wir ihr zu vom beim durch gegen ohne um " +
  "the and for with from that this these those are was were into how what why which about their " +
  "have has not but its our can does did than then there when who whom"
).split(" "));

function queryTerms(query) {
  const words = (query || "").toLowerCase().match(/[\p{L}\p{N}]{3,}/gu) || [];
  return [...new Set(words.filter((w) => !STOPWORDS.has(w)))].sort((a, b) => b.length - a.length);
}

// Escapes text and wraps word-initial matches of the query terms in <mark>.
function highlight(text, terms) {
  if (!terms || !terms.length) return escapeHtml(text);
  const re = new RegExp(`(?<![\\p{L}\\p{N}])(${terms.map(escapeRegex).join("|")})`, "giu");
  return String(text ?? "")
    .split(re)
    .map((part, i) => (i % 2 ? `<mark>${escapeHtml(part)}</mark>` : escapeHtml(part)))
    .join("");
}

/* ---------------------------------------------------------------- markdown */

// Small markdown renderer for Claude's answers. Input is escaped first, so
// nothing from the model can inject HTML.
function renderInline(text) {
  return text
    .replace(/(https?:\/\/[^\s<)]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>')
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, "$1<em>$2</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

const REFS_HEADING = /^(literatur|literaturverzeichnis|quellen|references|bibliograph)/i;

function renderMarkdown(md) {
  const lines = escapeHtml(md).split("\n");
  const out = [];
  let list = null; // "ul" | "ol"
  let para = [];
  let quote = [];

  const flushPara = () => {
    if (para.length) out.push(`<p>${renderInline(para.join("<br>"))}</p>`);
    para = [];
  };
  const flushQuote = () => {
    if (quote.length) out.push(`<blockquote>${renderInline(quote.join("<br>"))}</blockquote>`);
    quote = [];
  };
  const closeList = () => {
    if (list) out.push(`</${list}>`);
    list = null;
  };
  const flushAll = () => { flushPara(); flushQuote(); closeList(); };

  for (const raw of lines) {
    const line = raw.trimEnd();
    let m;
    if ((m = line.match(/^(#{1,4})\s+(.*)$/))) {
      flushAll();
      const tag = m[1].length >= 3 ? "h4" : "h3";
      const cls = REFS_HEADING.test(m[2].replace(/\*/g, "")) ? ' class="refs-heading"' : "";
      out.push(`<${tag}${cls}>${renderInline(m[2])}</${tag}>`);
    } else if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
      flushAll();
      out.push("<hr>");
    } else if ((m = line.match(/^\s*[-*•]\s+(.*)$/))) {
      flushPara(); flushQuote();
      if (list !== "ul") { closeList(); out.push("<ul>"); list = "ul"; }
      out.push(`<li>${renderInline(m[1])}</li>`);
    } else if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
      flushPara(); flushQuote();
      if (list !== "ol") { closeList(); out.push("<ol>"); list = "ol"; }
      out.push(`<li>${renderInline(m[1])}</li>`);
    } else if ((m = line.match(/^\s*&gt;\s?(.*)$/))) {
      flushPara(); closeList();
      quote.push(m[1]);
    } else if (line.trim() === "") {
      flushAll();
    } else {
      flushQuote(); closeList();
      para.push(line);
    }
  }
  flushAll();
  return out.join("");
}

/* ================================================================ views */

const views = { current: null, loaded: { dashboard: false, duplicates: false } };

function showView(name) {
  if (!els.views[name]) name = "search";
  if (views.current === name) return;
  views.current = name;
  for (const [key, section] of Object.entries(els.views)) section.hidden = key !== name;
  for (const link of document.querySelectorAll(".nav a")) {
    if (link.dataset.view === name) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  hideTooltip();
  if (name === "dashboard" && !views.loaded.dashboard) loadDashboard();
  if (name === "duplicates" && !views.loaded.duplicates) loadDuplicates();
  if (name === "search") els.query.focus({ preventScroll: true });
}

window.addEventListener("hashchange", () => showView(location.hash.slice(1)));

/* ================================================================ search panel */

const MODES = {
  search: {
    submit: "Suchen",
    placeholder: "Wonach suchst du? z.B. Interview-Studie zu AI-Adoption in Newsrooms",
    hint: "Hybride Suche über Volltexte, Metadaten und deine Highlights – anschließend präzise nachsortiert.",
    examples: [
      "Interview-Studie zu AI-Adoption in Newsrooms",
      "Framing der Eurokrise in deutschen Zeitungen",
      "LDA topic modeling limitations",
    ],
  },
  ask: {
    submit: "Fragen",
    placeholder: "Stell eine Frage an deine Bibliothek…",
    hint: "Claude beantwortet deine Frage aus den passendsten Quellen – mit APA-Zitaten und Seitenangaben. Folgefragen sind möglich.",
    examples: [
      "Wie beeinflussen Benzinpreise Inflationserwartungen?",
      "Welche Grenzen hat LDA Topic Modeling?",
      "Wie berichten Medien über die EZB-Geldpolitik?",
    ],
  },
  evidence: {
    submit: "Prüfen",
    placeholder: "Behauptung einfügen, die belegt werden soll…",
    hint: "Claude prüft, welche Quellen deine Behauptung stützen oder ihr widersprechen – mit wörtlichen Zitaten inkl. Primärquellen.",
    examples: [
      "Haushalte bilden Inflationserwartungen vor allem aus Alltagspreisen.",
      "Newsrooms stehen unter wachsendem Produktionsdruck.",
      "Negative Wirtschaftsnachrichten erhalten mehr Aufmerksamkeit als positive.",
    ],
  },
};

function currentMode() {
  return els.form.querySelector('input[name="mode"]:checked').value;
}

function applyMode(mode) {
  const cfg = MODES[mode] || MODES.search;
  els.query.placeholder = cfg.placeholder;
  els.modeHint.textContent = cfg.hint;
  if (!state.streaming) els.submit.textContent = cfg.submit;
  if (!state.hasResults) renderEmptyState();
}

els.form.addEventListener("change", (e) => {
  if (e.target.name === "mode") {
    storage.set("caitation.mode", e.target.value);
    applyMode(e.target.value);
  }
});

/* ---------------------------------------------------------------- filters */

const FILTER_FIELDS = {
  year_from: $("#yearFrom"),
  year_to: $("#yearTo"),
  item_type: $("#itemType"),
  collection: $("#collectionSelect"),
  library: $("#librarySelect"),
  tag: $("#tagInput"),
};
const annotationsOnly = $("#annotationsOnly");

function currentFilters() {
  const filters = {};
  for (const [key, el] of Object.entries(FILTER_FIELDS)) if (el.value.trim()) filters[key] = el.value.trim();
  if (annotationsOnly.checked) filters.annotations_only = true;
  return filters;
}

function updateFilterCount() {
  const n = Object.keys(currentFilters()).length;
  els.filterCount.hidden = n === 0;
  els.filterCount.textContent = n;
}

function setFilterPanel(open) {
  els.filterPanel.hidden = !open;
  els.filterToggle.setAttribute("aria-expanded", String(open));
}

els.filterToggle.addEventListener("click", () => setFilterPanel(els.filterPanel.hidden));
els.filterPanel.addEventListener("input", updateFilterCount);
els.filterPanel.addEventListener("change", updateFilterCount);

$("#clearFilters").addEventListener("click", () => {
  for (const el of Object.values(FILTER_FIELDS)) el.value = "";
  annotationsOnly.checked = false;
  updateFilterCount();
});

async function loadFilters() {
  try {
    const data = await api("/api/filters");
    const typeSel = FILTER_FIELDS.item_type;
    const collSel = FILTER_FIELDS.collection;
    typeSel.length = 1;
    collSel.length = 1;
    const types = data.item_types.map((t) => [t, typeLabel(t)]).sort((a, b) => a[1].localeCompare(b[1], "de"));
    for (const [value, label] of types) typeSel.appendChild(new Option(label, value));
    for (const c of data.collections) collSel.appendChild(new Option(c, c));
    const libSel = FILTER_FIELDS.library;
    libSel.length = 1;
    for (const lib of data.libraries || []) libSel.appendChild(new Option(lib, lib));
    libSel.closest(".field").hidden = (data.libraries || []).length < 2; // only with group libraries
    $("#tagList").innerHTML = data.tags.map((t) => `<option value="${escapeHtml(t)}"></option>`).join("");
    if (data.year_min) FILTER_FIELDS.year_from.placeholder = data.year_min;
    if (data.year_max) FILTER_FIELDS.year_to.placeholder = data.year_max;
  } catch { /* status pill already reports a dead server */ }
}

function applyFilterAndSearch(key, value, label) {
  FILTER_FIELDS[key].value = value;
  updateFilterCount();
  setFilterPanel(true);
  location.hash = "search";
  showView("search");
  toast(`Filter gesetzt: ${label}`);
}

/* ================================================================ results */

const state = {
  searchCtrl: null,
  streamCtrl: null,
  streaming: false,
  hasResults: false,
  chatHistory: [],
  lastRender: null,
};

const EMPTY_TITLES = {
  search: "Durchsuche deine Bibliothek",
  ask: "Frag deine Bibliothek",
  evidence: "Prüfe eine Behauptung",
};

function renderEmptyState() {
  const mode = currentMode();
  const cfg = MODES[mode];
  els.results.innerHTML = `
    <div class="empty-state">
      <h2>${EMPTY_TITLES[mode]}</h2>
      <p>Zum Beispiel – oder drück <kbd class="inline-kbd">/</kbd>, um jederzeit loszutippen:</p>
      <div class="examples">
        ${cfg.examples.map((ex) => `<button type="button" class="example-chip" data-example="${escapeHtml(ex)}">${escapeHtml(ex)}</button>`).join("")}
      </div>
    </div>`;
}

function renderSkeleton(note = "") {
  const card = `
    <div class="skeleton-card">
      <div class="skeleton-line title"></div>
      <div class="skeleton-line meta"></div>
      <div class="skeleton-line"></div>
      <div class="skeleton-line short"></div>
    </div>`;
  els.results.innerHTML = `
    <div class="results-head">
      <h2 class="results-title">${note ? escapeHtml(note) : "Suche…"}</h2>
    </div>
    <div class="result-list">${card.repeat(3)}</div>`;
}

function renderError(err) {
  els.results.innerHTML = `
    <div class="notice notice-error" role="alert">
      <strong>Das hat nicht geklappt.</strong> ${escapeHtml(err.message || String(err))}
    </div>`;
}

function resultCard(r, terms) {
  const isHighlight = r.chunk_type === "annotation";
  const meta = [];
  const authors = shortAuthors(r.authors);
  if (authors) meta.push(`<span title="${escapeHtml(r.authors)}">${escapeHtml(authors)}</span>`);
  if (r.year) meta.push(`<span>${r.year}</span>`);
  const metaHtml = meta.join('<span class="sep">·</span>');
  const pills = [
    r.item_type ? `<span class="pill">${escapeHtml(typeLabel(r.item_type))}</span>` : "",
    isHighlight ? `<span class="pill pill-good" title="Fundstelle aus deinen PDF-Highlights">${icon("highlight")}Dein Highlight</span>` : "",
    r.duplicate_count ? `<span class="pill pill-warn" title="Weitere identische Einträge wurden zusammengefasst">+${r.duplicate_count} Dublette${r.duplicate_count > 1 ? "n" : ""}</span>` : "",
  ].join("");

  const page = (p) => (p ? ` <span class="rc-page">S. ${p}</span>` : "");
  const snippet = r.snippet
    ? `<p class="rc-snippet${isHighlight ? " is-highlight" : ""}">${highlight(r.snippet, terms)}${page(r.page)}</p>`
    : "";
  const more = r.matches && r.matches.length
    ? `<details class="more-matches">
         <summary>${r.matches.length} weitere Fundstelle${r.matches.length > 1 ? "n" : ""}</summary>
         ${r.matches.map((m) => `<p class="rc-snippet">${highlight(m.snippet, terms)}${page(m.page)}</p>`).join("")}
       </details>`
    : "";
  const key = encodeURIComponent(r.item_key);

  return `
    <article class="result-card">
      <h3 class="rc-title">${formatTitle(r.title)}</h3>
      <div class="rc-meta">${metaHtml}${pills}</div>
      ${snippet}
      ${more}
      <div class="rc-actions">
        <a class="rc-action" href="${escapeHtml(r.zotero_link)}">${icon("zotero")}In Zotero</a>
        ${r.has_pdf ? `<a class="rc-action" href="/api/pdf/${key}#page=${r.page || 1}" target="_blank" rel="noopener">${icon("file")}PDF${r.page ? ` · S. ${r.page}` : ""}</a>` : ""}
        <button type="button" class="rc-action" data-related="${escapeHtml(r.item_key)}" data-title="${escapeHtml(plainTitle(r.title))}">${icon("network")}Ähnliche Paper</button>
        <a class="rc-action" href="/api/bibtex?keys=${key}" download>${icon("download")}BibTeX</a>
      </div>
    </article>`;
}

function renderResults(results, { title = "Treffer", terms = [], preview = false, back = false } = {}) {
  state.hasResults = true;
  if (!back) state.lastRender = { results, title, terms };
  if (!results.length) {
    els.results.innerHTML = `
      <div class="empty-state">
        <h2>Keine Treffer</h2>
        <p>Versuch andere Begriffe oder lockere die Filter.</p>
      </div>`;
    return;
  }
  const keys = results.map((r) => r.item_key).join(",");
  els.results.innerHTML = `
    <div class="results-head">
      ${back ? `<button type="button" class="btn btn-ghost btn-sm" data-back>${icon("back")}Zurück</button>` : ""}
      <h2 class="results-title">${escapeHtml(title)} <strong>${results.length}</strong></h2>
      ${preview ? '<span class="refine-hint">Ranking wird präzisiert…</span>' : ""}
      <span class="spacer"></span>
      <a class="btn btn-ghost btn-sm" href="/api/bibtex?keys=${encodeURIComponent(keys)}" download>${icon("download")}BibTeX (${results.length})</a>
    </div>
    <div class="result-list${preview ? " is-preview" : ""}">${results.map((r) => resultCard(r, terms)).join("")}</div>`;
}

els.results.addEventListener("click", async (e) => {
  const example = e.target.closest("[data-example]");
  if (example) {
    els.query.value = example.dataset.example;
    els.form.requestSubmit();
    return;
  }
  if (e.target.closest("[data-back]")) {
    const last = state.lastRender;
    if (last) renderResults(last.results, { title: last.title, terms: last.terms });
    return;
  }
  const related = e.target.closest("[data-related]");
  if (related) showRelated(related.dataset.related, related.dataset.title);
});

async function showRelated(itemKey, title) {
  state.searchCtrl?.abort();
  const ctrl = (state.searchCtrl = new AbortController());
  els.answerBox.hidden = true;
  renderSkeleton("Suche ähnliche Paper…");
  window.scrollTo({ top: 0, behavior: "smooth" });
  try {
    const data = await api(`/api/related/${encodeURIComponent(itemKey)}`, { signal: ctrl.signal });
    renderResults(data.results, {
      title: title ? `Ähnlich zu „${title}"` : "Ähnliche Paper",
      back: Boolean(state.lastRender),
    });
  } catch (err) {
    if (!isAbort(err)) renderError(err);
  }
}

/* ---------------------------------------------------------------- search flow */

async function runSearch(query, filters) {
  state.searchCtrl?.abort();
  const ctrl = (state.searchCtrl = new AbortController());
  els.answerBox.hidden = true;
  const terms = queryTerms(query);
  renderSkeleton(serverStatus.ready ? "" : "Modelle werden geladen (einmalig nach dem Start)…");

  const params = new URLSearchParams({ q: query, ...filters });
  try {
    // Fast preview (hybrid retrieval only), then the cross-encoder ranking. The
    // second request reuses the server-side retrieval cache.
    const preview = await api(`/api/search?${params}&rerank=false`, { signal: ctrl.signal });
    renderResults(preview.results, { terms, preview: preview.results.length > 0 });
    if (!preview.results.length) return;
    const full = await api(`/api/search?${params}`, { signal: ctrl.signal });
    renderResults(full.results, { terms });
    els.results.querySelector(".result-list")?.classList.add("no-anim");
  } catch (err) {
    if (!isAbort(err)) renderError(err);
  }
}

/* ---------------------------------------------------------------- ask flow */

function appendMessage(role, html) {
  const div = document.createElement("div");
  div.className = `chat-msg chat-${role}`;
  div.innerHTML = html;
  els.chatLog.appendChild(div);
  return div;
}

function setStreaming(on) {
  state.streaming = on;
  els.submit.classList.toggle("is-stop", on);
  els.submit.innerHTML = on ? `${icon("stop")}Stopp` : MODES[currentMode()].submit;
}

async function streamAsk(query, mode, filters) {
  els.answerBox.hidden = false;
  appendMessage("user", escapeHtml(query));
  const msg = appendMessage(
    "assistant",
    `<span class="chat-status"><span class="typing"><i></i><i></i><i></i></span>Suche passende Quellen…</span>`,
  );
  msg.scrollIntoView({ block: "nearest", behavior: "smooth" });
  els.query.value = "";
  const terms = queryTerms(query);
  renderSkeleton("Quellen werden gesucht…");

  state.searchCtrl?.abort();
  const ctrl = (state.streamCtrl = new AbortController());
  setStreaming(true);

  let answer = "";
  let aborted = false;
  let failed = null;
  let quoteChecks = [];
  let frame = 0;
  const paint = () => {
    frame = 0;
    msg.innerHTML = renderMarkdown(answer);
  };

  try {
    const res = await fetch("/api/ask/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, mode, history: state.chatHistory, ...filters }),
      signal: ctrl.signal,
    });
    if (!res.ok) throw new Error(`Serverfehler (HTTP ${res.status}): ${(await res.text()).slice(0, 200)}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop();
      for (const raw of events) {
        if (!raw.startsWith("data: ")) continue;
        const event = JSON.parse(raw.slice(6));
        if (event.type === "sources") {
          renderResults(event.sources, { title: "Quellen", terms });
          if (!answer) {
            msg.innerHTML = `<span class="chat-status"><span class="typing"><i></i><i></i><i></i></span>Formuliere Antwort…</span>`;
          }
        } else if (event.type === "quotes") {
          quoteChecks = event.quotes || [];
        } else if (event.type === "delta") {
          answer += event.text;
          msg.classList.add("is-streaming");
          if (!frame) frame = requestAnimationFrame(paint); // at most one re-render per frame
        }
      }
    }
  } catch (err) {
    if (isAbort(err)) aborted = true;
    else failed = err;
  } finally {
    cancelAnimationFrame(frame);
    setStreaming(false);
    state.streamCtrl = null;
    msg.classList.remove("is-streaming");
  }

  if (failed && !answer) {
    msg.innerHTML = `<div class="notice notice-error">${escapeHtml(failed.message)}</div>`;
    return;
  }
  msg.innerHTML = answer ? renderMarkdown(answer) : "";
  if (quoteChecks.length) {
    markQuotes(msg, quoteChecks);
    msg.appendChild(quoteSummary(quoteChecks));
  }
  const note = aborted ? "Antwort abgebrochen." : failed ? `Verbindung unterbrochen: ${failed.message}` : "";
  const actions = document.createElement("div");
  actions.className = "msg-actions";
  if (answer) {
    actions.innerHTML = `<button type="button" class="btn btn-ghost btn-sm" data-copy>${icon("copy")}Kopieren</button>`;
    actions.querySelector("[data-copy]").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(answer);
        toast("Antwort in die Zwischenablage kopiert");
      } catch {
        toast("Kopieren nicht möglich");
      }
    });
  }
  if (note) actions.insertAdjacentHTML("beforeend", `<span class="msg-note">${escapeHtml(note)}</span>`);
  msg.appendChild(actions);

  if (answer) {
    state.chatHistory.push({ role: "user", content: query });
    state.chatHistory.push({ role: "assistant", content: answer });
  }
}

/* ---------------------------------------------------------------- quote checks */

const QUOTE_STATUS = {
  verified: { cls: "is-verified", mark: "✓", label: "wörtlich im Quelltext gefunden" },
  deviates: { cls: "is-deviates", mark: "≈", label: "weicht vom Quelltext ab" },
  not_found: { cls: "is-missing", mark: "✗", label: "nicht im Quelltext gefunden" },
};

function quoteSource(q) {
  if (!q.item_key) return "";
  return `${plainTitle(q.title) || "Quelle"}${q.page ? `, S. ${q.page}` : ""}`;
}

function pageWarning(q) {
  return q.page_mismatch ? `Seitenangabe prüfen: zitiert S. ${q.cited_page}, im Quelltext ab S. ${q.page}` : "";
}

// Marks each checked quote inside the rendered answer (when it sits in one text node).
function markQuotes(root, checks) {
  for (const q of checks) {
    const status = QUOTE_STATUS[q.status];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const at = node.data.indexOf(q.quote);
      if (at < 0 || node.parentElement.closest(".quote-check")) continue;
      const range = document.createRange();
      range.setStart(node, at);
      range.setEnd(node, at + q.quote.length);
      const span = document.createElement("span");
      span.className = `quote-check ${status.cls}`;
      span.title = [`Zitat ${status.label}`, quoteSource(q), pageWarning(q)].filter(Boolean).join(" – ");
      range.surroundContents(span);
      // badge after the closing quotation mark, so the mark never wraps onto its own line
      let anchor = span;
      const next = span.nextSibling;
      if (next?.nodeType === Node.TEXT_NODE && /^[“”"«»‘’]/.test(next.data)) {
        next.splitText(1);
        anchor = next;
      }
      anchor.after(Object.assign(document.createElement("sup"), {
        className: `quote-badge ${status.cls}`,
        textContent: status.mark,
        ariaLabel: status.label,
      }));
      break;
    }
  }
}

function quoteSummary(checks) {
  const counts = { verified: 0, deviates: 0, not_found: 0 };
  for (const q of checks) counts[q.status] += 1;
  const pageIssues = checks.filter((q) => q.page_mismatch).length;
  const allGood = counts.verified === checks.length && !pageIssues;
  const box = document.createElement("details");
  box.className = `quote-summary ${allGood ? "is-verified" : counts.not_found ? "is-missing" : "is-deviates"}`;
  box.open = !allGood;
  const parts = [];
  if (counts.verified) parts.push(`${counts.verified} wörtlich belegt`);
  if (counts.deviates) parts.push(`${counts.deviates} abweichend`);
  if (counts.not_found) parts.push(`${counts.not_found} nicht gefunden`);
  if (pageIssues) parts.push(`${pageIssues}× Seitenangabe prüfen`);
  box.innerHTML = `
    <summary>Zitatprüfung: ${parts.join(" · ")}</summary>
    <ul>${checks.map((q) => {
      const status = QUOTE_STATUS[q.status];
      const text = q.quote.length > 110 ? `${q.quote.slice(0, 107)}…` : q.quote;
      return `<li><span class="quote-badge ${status.cls}" aria-label="${status.label}">${status.mark}</span>
        „${escapeHtml(text)}"<span class="quote-src">${escapeHtml(quoteSource(q) || status.label)}</span>
        ${pageWarning(q) ? `<span class="quote-src quote-page-warning">${escapeHtml(pageWarning(q))}</span>` : ""}</li>`;
    }).join("")}</ul>
    ${counts.not_found ? '<p class="quote-hint">Nicht gefundene Zitate vor dem Übernehmen unbedingt im PDF prüfen.</p>' : ""}`;
  return box;
}

$("#newChatBtn").addEventListener("click", () => {
  state.streamCtrl?.abort();
  state.chatHistory = [];
  els.chatLog.innerHTML = "";
  els.answerBox.hidden = true;
  state.hasResults = false;
  renderEmptyState();
  els.query.focus();
});

/* ---------------------------------------------------------------- submit */

els.form.addEventListener("submit", (e) => {
  e.preventDefault();
  if (state.streaming) {
    state.streamCtrl?.abort();
    return;
  }
  const query = els.query.value.trim();
  if (!query) {
    els.query.focus();
    return;
  }
  const mode = currentMode();
  const filters = currentFilters();
  if (mode === "search") runSearch(query, filters);
  else streamAsk(query, mode === "evidence" ? "evidence" : "answer", filters);
});

/* ================================================================ dashboard */

const SERIES = 8; // categorical slots; the backend caps clusters to this

function kpi(label, value, sub = "") {
  return `
    <div class="kpi">
      <div class="kpi-label">${escapeHtml(label)}</div>
      <div class="kpi-value">${value}</div>
      ${sub ? `<div class="kpi-sub">${escapeHtml(sub)}</div>` : ""}
    </div>`;
}

function hbarList(rows, { labelFn = (x) => x, dataAttr = "" } = {}) {
  const max = Math.max(1, ...rows.map(([, n]) => n));
  return `<div class="hbar-list">${rows.map(([name, n]) => `
    <div class="hbar"${dataAttr ? ` ${dataAttr}="${escapeHtml(name)}"` : ""}>
      <span class="hbar-label" title="${escapeHtml(labelFn(name))}">${escapeHtml(labelFn(name))}</span>
      <div class="hbar-track"><div class="hbar-fill" style="width:${((n / max) * 100).toFixed(1)}%"></div></div>
      <span class="hbar-value">${numberFmt.format(n)}</span>
    </div>`).join("")}</div>`;
}

function yearChart(years) {
  const recent = years.filter(([y]) => y >= 1990);
  if (!recent.length) return "<p class=\"kpi-sub\">Keine Jahresangaben.</p>";
  const counts = new Map(recent);
  const first = recent[0][0];
  const last = recent[recent.length - 1][0];
  const series = [];
  for (let y = first; y <= last; y++) series.push([y, counts.get(y) || 0]);

  const W = 560, H = 190, left = 30, bottom = 22, top = 8;
  const plotW = W - left - 4;
  const plotH = H - bottom - top;
  const max = Math.max(...series.map(([, n]) => n));
  const step = Math.pow(10, Math.floor(Math.log10(max))) * (max / Math.pow(10, Math.floor(Math.log10(max))) > 5 ? 2 : 1);
  const tickMax = Math.ceil(max / step) * step;
  const slot = plotW / series.length;
  const barW = Math.max(1, slot - 2); // 2px gap between bars
  const yOf = (n) => top + plotH - (n / tickMax) * plotH;

  let grid = "";
  for (let v = 0; v <= tickMax; v += step) {
    const y = yOf(v).toFixed(1);
    grid += `<line class="${v === 0 ? "baseline" : "gridline"}" x1="${left}" x2="${W - 4}" y1="${y}" y2="${y}"/>`;
    grid += `<text class="axis-label" x="${left - 6}" y="${(+y + 3.5).toFixed(1)}" text-anchor="end">${v}</text>`;
  }

  let bars = "";
  series.forEach(([year, n], i) => {
    const x = left + i * slot + 1;
    const y = yOf(n);
    const h = top + plotH - y;
    const r = Math.min(4, barW / 2, h);
    const d = n
      ? `M${x},${top + plotH}V${y + r}Q${x},${y} ${x + r},${y}H${x + barW - r}Q${x + barW},${y} ${x + barW},${y + r}V${top + plotH}Z`
      : "";
    bars += `<g data-year="${year}" data-count="${n}">
      <rect class="bar-hit" x="${left + i * slot}" y="${top}" width="${slot}" height="${plotH}"/>
      ${d ? `<path class="bar" d="${d}"/>` : ""}
    </g>`;
    if (year % 5 === 0) {
      bars += `<text class="axis-label" x="${(x + barW / 2).toFixed(1)}" y="${H - 6}" text-anchor="middle">${year}</text>`;
    }
  });

  return `<svg class="bar-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Einträge pro Erscheinungsjahr">${grid}${bars}</svg>`;
}

// Places cluster labels at their centroids, nudging them vertically to avoid overlaps.
function placeLabels(clusters, toX, toY) {
  const placed = [];
  const charW = 1.2; // approx. glyph width at the label font size, in viewBox units
  const lineH = 3.2;
  const sorted = [...clusters].sort((a, b) => b.size - a.size);
  const positions = new Map();
  for (const c of sorted) {
    const w = c.label.length * charW;
    const cx = Math.min(Math.max(toX(c.x), w / 2 + 1), 160 - w / 2 - 1);
    const cy = toY(c.y);
    let chosen = cy;
    for (const dy of [0, -lineH, lineH, -2 * lineH, 2 * lineH, -3 * lineH, 3 * lineH]) {
      const y = Math.min(Math.max(cy + dy, 4), 97);
      const box = { x1: cx - w / 2, x2: cx + w / 2, y1: y - lineH / 2, y2: y + lineH / 2 };
      if (!placed.some((b) => box.x1 < b.x2 && box.x2 > b.x1 && box.y1 < b.y2 && box.y2 > b.y1)) {
        chosen = y;
        placed.push(box);
        break;
      }
    }
    positions.set(c.id, { x: cx, y: chosen });
  }
  return positions;
}

function topicMap(points, clusters) {
  if (!points.length) return '<p class="kpi-sub">Noch zu wenige Einträge für eine Landkarte.</p>';
  const toX = (x) => 4 + x * 152;
  const toY = (y) => 5 + y * 90;
  const slot = (id) => (id % SERIES) + 1;
  const dots = points.map((p, i) =>
    `<circle class="fill-s${slot(p.cluster)}" data-idx="${i}" data-cluster="${p.cluster}" cx="${toX(p.x).toFixed(2)}" cy="${toY(p.y).toFixed(2)}" r="0.95"/>`,
  ).join("");
  const pos = placeLabels(clusters, toX, toY);
  const labels = clusters.map((c) => {
    const { x, y } = pos.get(c.id);
    const attrs = `x="${x.toFixed(2)}" y="${(y + 0.7).toFixed(2)}" data-cluster="${c.id}"`;
    return `<text class="cluster-halo" ${attrs}>${escapeHtml(c.label)}</text><text class="cluster-label" ${attrs}>${escapeHtml(c.label)}</text>`;
  }).join("");
  const legend = [...clusters].sort((a, b) => b.size - a.size).map((c) => `
    <button type="button" class="legend-item" data-cluster="${c.id}">
      <span class="legend-swatch bg-s${slot(c.id)}"></span>${escapeHtml(c.label)}
      <span class="legend-count">${numberFmt.format(c.size)}</span>
    </button>`).join("");
  return `
    <div class="map-wrap">
      <svg class="topic-map" viewBox="0 0 160 100" role="img" aria-label="Themen-Landkarte der Bibliothek">${dots}${labels}</svg>
    </div>
    <div class="legend">${legend}</div>`;
}

function bindTopicMap(root, points, clusters) {
  const svg = root.querySelector(".topic-map");
  if (!svg) return;
  const byId = new Map(clusters.map((c) => [c.id, c]));
  let pinned = null;

  const focus = (id) => {
    svg.classList.toggle("has-focus", id !== null);
    for (const el of svg.querySelectorAll("[data-cluster]")) {
      el.classList.toggle("is-focus", id !== null && Number(el.dataset.cluster) === id);
    }
    for (const btn of root.querySelectorAll(".legend-item")) {
      btn.classList.toggle("is-active", Number(btn.dataset.cluster) === id);
    }
  };

  svg.addEventListener("mousemove", (e) => {
    const dot = e.target.closest("circle");
    if (!dot) { hideTooltip(); return; }
    const p = points[Number(dot.dataset.idx)];
    const cluster = byId.get(p.cluster);
    showTooltip(`
      <strong>${formatTitle(p.title)}</strong>
      ${escapeHtml(shortAuthors(p.authors))}${p.year ? ` · ${p.year}` : ""} · ${escapeHtml(typeLabel(p.item_type))}
      <div class="tt-muted">${cluster ? `Thema: ${escapeHtml(cluster.label)}` : ""}${p.collection ? ` · ${escapeHtml(p.collection)}` : ""}</div>
      ${p.tags && p.tags.length ? `<div class="tt-muted">Tags: ${p.tags.map(escapeHtml).join(", ")}</div>` : ""}
      <div class="tt-muted">Klick öffnet den Eintrag in Zotero</div>`, e);
  });
  svg.addEventListener("mouseleave", hideTooltip);
  svg.addEventListener("click", (e) => {
    const dot = e.target.closest("circle");
    if (dot) window.location.href = points[Number(dot.dataset.idx)].zotero_link;
  });

  const legend = root.querySelector(".legend");
  legend.addEventListener("mouseover", (e) => {
    const btn = e.target.closest(".legend-item");
    if (btn && pinned === null) focus(Number(btn.dataset.cluster));
  });
  legend.addEventListener("mouseleave", () => focus(pinned));
  legend.addEventListener("click", (e) => {
    const btn = e.target.closest(".legend-item");
    if (!btn) return;
    const id = Number(btn.dataset.cluster);
    pinned = pinned === id ? null : id;
    focus(pinned);
  });
}

async function loadDashboard() {
  const view = els.views.dashboard;
  views.loaded.dashboard = true;
  view.innerHTML = `
    <div class="page-head"><h1>Deine Bibliothek im Überblick</h1><p>Wird berechnet…</p></div>
    <div class="kpi-grid">${'<div class="kpi"><div class="skeleton-line meta"></div><div class="skeleton-line title"></div></div>'.repeat(4)}</div>
    <div class="card"><div class="skeleton-line title"></div><div class="skeleton-line"></div><div class="skeleton-line short"></div></div>`;
  let data;
  try {
    data = await api("/api/stats");
  } catch (err) {
    views.loaded.dashboard = false;
    view.innerHTML = `<div class="notice notice-error">${escapeHtml(err.message)}</div>`;
    return;
  }
  const { stats, topic_map: map } = data;
  const points = map.points || [];
  const clusters = map.clusters || [];
  const yearsWithData = stats.years.map(([y]) => y);
  const pdfShare = stats.total_items ? Math.round((stats.with_pdf / stats.total_items) * 100) : 0;

  view.innerHTML = `
    <div class="page-head">
      <h1>Deine Bibliothek im Überblick</h1>
      <p>Themen, Schwerpunkte und Entwicklung deiner Zotero-Sammlung.</p>
    </div>
    <div class="kpi-grid">
      ${kpi("Einträge", numberFmt.format(stats.total_items))}
      ${kpi("Mit Volltext", numberFmt.format(stats.with_pdf), `${pdfShare} % der Einträge`)}
      ${kpi("Highlights & Notizen", numberFmt.format(stats.annotations), "aus dem Zotero-PDF-Reader")}
      ${kpi("Zeitraum", yearsWithData.length ? `${yearsWithData[0]}–${yearsWithData[yearsWithData.length - 1]}` : "–", "Erscheinungsjahre")}
    </div>

    <section class="card">
      <div class="card-head">
        <h2>Themen-Landkarte</h2>
        <p>Nähe = inhaltliche Ähnlichkeit · Themen per Legende hervorheben · Klick auf einen Punkt öffnet Zotero</p>
      </div>
      ${topicMap(points, clusters)}
    </section>

    <div class="card-grid">
      <section class="card">
        <div class="card-head"><h2>Einträge pro Erscheinungsjahr</h2><p>ab 1990</p></div>
        ${yearChart(stats.years)}
      </section>
      <section class="card">
        <div class="card-head"><h2>Publikationstypen</h2></div>
        ${hbarList(stats.types.slice(0, 8), { labelFn: typeLabel, dataAttr: "data-type" })}
      </section>
    </div>

    <div class="card-grid" style="margin-top:16px">
      <section class="card">
        <div class="card-head"><h2>Größte Sammlungen</h2><p>Klick filtert die Suche</p></div>
        ${hbarList(stats.top_collections.slice(0, 8), { dataAttr: "data-collection" })}
      </section>
      <section class="card">
        <div class="card-head"><h2>Häufigste Tags</h2><p>Klick filtert die Suche</p></div>
        <div class="chip-cloud">
          ${stats.top_tags.map(([t, n]) => `<button type="button" class="chip" data-tag="${escapeHtml(t)}">${escapeHtml(t)}<span class="chip-count">${n}</span></button>`).join("")}
        </div>
      </section>
    </div>`;

  bindTopicMap(view, points, clusters);

  const chart = view.querySelector(".bar-chart");
  chart?.addEventListener("mousemove", (e) => {
    const g = e.target.closest("g[data-year]");
    if (!g) { hideTooltip(); return; }
    const n = Number(g.dataset.count);
    showTooltip(`<strong>${g.dataset.year}</strong>${numberFmt.format(n)} Eintr${n === 1 ? "ag" : "äge"}`, e);
  });
  chart?.addEventListener("mouseleave", hideTooltip);

  view.addEventListener("click", (e) => {
    const tag = e.target.closest("[data-tag]");
    if (tag) return applyFilterAndSearch("tag", tag.dataset.tag, `Tag „${tag.dataset.tag}"`);
    const coll = e.target.closest("[data-collection]");
    if (coll) return applyFilterAndSearch("collection", coll.dataset.collection, `Sammlung „${coll.dataset.collection}"`);
    const type = e.target.closest("[data-type]");
    if (type) return applyFilterAndSearch("item_type", type.dataset.type, `Typ „${typeLabel(type.dataset.type)}"`);
  });
}

/* ================================================================ duplicates */

async function loadDuplicates() {
  const view = els.views.duplicates;
  views.loaded.duplicates = true;
  view.innerHTML = `
    <div class="page-head"><h1>Dubletten</h1><p>Prüfe Bibliothek…</p></div>
    <div class="card"><div class="skeleton-line title"></div><div class="skeleton-line"></div></div>`;
  let data;
  try {
    data = await api("/api/duplicates");
  } catch (err) {
    views.loaded.duplicates = false;
    view.innerHTML = `<div class="notice notice-error">${escapeHtml(err.message)}</div>`;
    return;
  }
  if (!data.count) {
    view.innerHTML = `
      <div class="page-head"><h1>Dubletten</h1></div>
      <div class="empty-state"><h2>Keine Dubletten gefunden</h2><p>Deine Bibliothek ist sauber – keine Einträge mit gleicher DOI oder gleichem Titel.</p></div>`;
    return;
  }
  view.innerHTML = `
    <div class="page-head">
      <h1>${data.count} mögliche Dubletten-Gruppe${data.count > 1 ? "n" : ""}</h1>
      <p>Zum Zusammenführen in Zotero: Einträge markieren → Rechtsklick → „Einträge zusammenführen".</p>
    </div>
    ${data.groups.map((g) => `
      <section class="card dup-group">
        <div class="dup-group-head"><span class="pill pill-warn">${escapeHtml(g.reason)}</span>${g.items.length} Einträge</div>
        ${g.items.map((i) => `
          <div class="dup-item">
            <div class="dup-item-body">
              <h3 class="rc-title">${formatTitle(i.title)}</h3>
              <div class="rc-meta">
                ${i.authors ? `<span>${escapeHtml(shortAuthors(i.authors))}</span><span class="sep">·</span>` : ""}
                ${i.year ? `<span>${i.year}</span><span class="sep">·</span>` : ""}
                <span class="pill">${escapeHtml(typeLabel(i.item_type))}</span>
                ${i.has_pdf ? `<span class="pill pill-good">PDF</span>` : `<span class="pill">kein PDF</span>`}
              </div>
            </div>
            <a class="rc-action" href="${escapeHtml(i.zotero_link)}">${icon("zotero")}In Zotero</a>
          </div>`).join("")}
      </section>`).join("")}`;
}

/* ================================================================ index status */

const serverStatus = { ready: false, running: false, polling: false };

function setPill(stateName, text, title = "") {
  els.statusPill.dataset.state = stateName;
  els.statusText.textContent = text;
  els.statusPill.title = title || text;
}

async function pollStatus() {
  serverStatus.polling = true;
  let s;
  try {
    s = await api("/api/reindex/status");
  } catch {
    setPill("error", "Server nicht erreichbar");
    els.progress.hidden = true;
    setTimeout(pollStatus, 5000);
    return;
  }
  const wasRunning = serverStatus.running;
  serverStatus.ready = s.ready;
  serverStatus.running = s.running;
  els.reindexBtn.classList.toggle("is-spinning", s.running);

  if (s.running) {
    const text = s.total ? `Indexiere ${numberFmt.format(s.done)} / ${numberFmt.format(s.total)}` : "Lese Bibliothek…";
    setPill("indexing", text, s.current || text);
    els.progress.hidden = !s.total;
    if (s.total) els.progressBar.style.width = `${((s.done / s.total) * 100).toFixed(1)}%`;
  } else {
    els.progress.hidden = true;
    if (s.status === "error") {
      setPill("error", "Indexierung fehlgeschlagen", `${s.current} – Details in data/caitation.log`);
    } else if (!s.ready) setPill("loading", "Modelle laden…", "Such- und Ranking-Modelle werden einmalig geladen");
    else setPill("ready", "Bereit", s.status === "done" ? "Index ist aktuell" : "Bereit");
    if (wasRunning && s.status === "done") {
      toast("Index aktualisiert");
      views.loaded.dashboard = false;
      views.loaded.duplicates = false;
      loadFilters();
    }
  }

  if (s.running || !s.ready) setTimeout(pollStatus, 1500);
  else serverStatus.polling = false;
}

els.reindexBtn.addEventListener("click", async () => {
  try {
    const data = await api("/api/reindex", { method: "POST" });
    toast(data.started ? "Indexierung gestartet – nur geänderte Einträge werden verarbeitet" : data.message);
    if (!serverStatus.polling) setTimeout(pollStatus, 300);
  } catch (err) {
    toast(err.message);
  }
});

/* ================================================================ keyboard */

document.addEventListener("keydown", (e) => {
  const typing = e.target.closest("input, textarea, select, [contenteditable]");
  if ((e.key === "/" && !typing) || (e.key.toLowerCase() === "k" && (e.ctrlKey || e.metaKey))) {
    e.preventDefault();
    if (views.current !== "search") location.hash = "search";
    els.query.focus();
    els.query.select();
  } else if (e.key === "Escape" && e.target === els.query) {
    els.query.blur();
  }
});

/* ================================================================ init */

function setMode(mode) {
  els.form.querySelector(`input[name="mode"][value="${mode}"]`).checked = true;
  applyMode(mode);
}

// Links from the Zotero plugin: ?q=…&mode=search|ask|evidence or ?related=KEY&title=…
function applyLaunchParams() {
  const params = new URLSearchParams(location.search);
  if (![...params.keys()].length) return false;
  history.replaceState(null, "", `${location.pathname}#search`);
  showView("search");
  if (params.get("related")) {
    showRelated(params.get("related"), params.get("title") || "");
    return true;
  }
  const mode = params.get("mode");
  if (MODES[mode]) setMode(mode);
  const query = (params.get("q") || "").trim();
  if (query) {
    els.query.value = query;
    els.form.requestSubmit();
  }
  return true;
}

(function init() {
  const savedMode = storage.get("caitation.mode");
  if (savedMode && MODES[savedMode]) setMode(savedMode);
  else applyMode(currentMode());
  if (!applyLaunchParams()) showView(location.hash.slice(1) || "search");
  pollStatus();
  loadFilters();
})();
