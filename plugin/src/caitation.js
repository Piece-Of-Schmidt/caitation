/* global Services, Zotero */

// Caitation for Zotero: a thin client for the local Caitation app (the Python server
// does the indexing, search and ranking; this plugin brings it into Zotero).
// Top-level "var", not "const": the script may be loaded again into the same scope
// when the plugin is disabled and re-enabled.

var XHTML = "http://www.w3.org/1999/xhtml";
var DEFAULT_SERVER = "http://127.0.0.1:8000";
var MAX_QUERY_CHARS = 1000;
// Zotero's switch for its local API ("Allow other applications on this computer to
// communicate with Zotero"), through which the Caitation app reads the library
var LOCAL_API_PREF = "httpServer.localAPI.enabled";
var ASKED_PREF = "extensions.caitation.localAPIAsked";

var STRINGS = {
  de: {
    loading: "Suche ähnliche Paper…",
    none: "Keine ähnlichen Paper gefunden. Ist der Eintrag schon indexiert?",
    offline: "Caitation ist nicht erreichbar.",
    offlineHint: "Starte die Caitation-App (siehe README) und versuche es erneut.",
    forbidden: "Caitation hat die Anfrage abgelehnt. Ist die Server-Adresse korrekt?",
    retry: "Erneut versuchen",
    openAll: "In Caitation öffnen",
    summary: (n) => `${n} ähnliche`,
    readerSearch: "In Caitation suchen",
    readerEvidence: "Beleg prüfen",
    accessTitle: "Caitation: Zugriff auf deine Bibliothek",
    accessText:
      "Die Caitation-App liest deine Bibliothek über Zoteros offizielle lokale Schnittstelle: " +
      "nur lesend und nur von diesem Computer aus. Dafür muss Zotero anderen Anwendungen auf " +
      "diesem Computer die Kommunikation erlauben (Einstellungen → Erweitert).\n\n" +
      "Jetzt erlauben? Du kannst das jederzeit in den Zotero-Einstellungen wieder abschalten.",
    accessAllow: "Erlauben",
    accessNotNow: "Später",
    accessLater: "Später möglich über Werkzeuge → Caitation: Zugriff auf die Bibliothek erlauben.",
  },
  en: {
    loading: "Looking for similar papers…",
    none: "No similar papers found. Has this item been indexed yet?",
    offline: "Caitation is not reachable.",
    offlineHint: "Start the Caitation app (see README) and try again.",
    forbidden: "Caitation refused the request. Is the server address correct?",
    retry: "Try again",
    openAll: "Open in Caitation",
    summary: (n) => `${n} similar`,
    readerSearch: "Search in Caitation",
    readerEvidence: "Check evidence",
    accessTitle: "Caitation: access to your library",
    accessText:
      "The Caitation app reads your library through Zotero's official local API: read-only " +
      "and only from this computer. This requires Zotero to allow other applications on this " +
      "computer to communicate with it (Settings → Advanced).\n\n" +
      "Allow it now? You can switch it off again in Zotero's settings at any time.",
    accessAllow: "Allow",
    accessNotNow: "Later",
    accessLater: "You can do this later via Tools → Caitation: allow access to the library.",
  },
};

Caitation = {
  id: null,
  version: null,
  rootURI: null,
  menuIDs: [],
  sectionID: null,
  readerListener: null,

  init({ id, version, rootURI }) {
    this.id = id;
    this.version = version;
    this.rootURI = rootURI;
  },

  // ------------------------------------------------------------ helpers

  t(key, ...args) {
    const lang = String(Zotero.locale || "en").toLowerCase().startsWith("de") ? "de" : "en";
    const value = STRINGS[lang][key] ?? STRINGS.en[key];
    return typeof value === "function" ? value(...args) : value;
  },

  get serverURL() {
    // optional override via the config editor: extensions.caitation.serverURL
    const custom = Zotero.Prefs.get("extensions.caitation.serverURL", true);
    return String(custom || DEFAULT_SERVER).replace(/\/+$/, "");
  },

  async apiGet(path) {
    const xhr = await Zotero.HTTP.request("GET", this.serverURL + path, {
      headers: { "X-Caitation-Client": `zotero-plugin/${this.version}` },
      responseType: "json",
      timeout: 30000,
    });
    return xhr.response;
  },

  openInBrowser(params = {}) {
    const query = Object.entries(params)
      .filter(([, value]) => value)
      .map(([key, value]) => `${key}=${encodeURIComponent(value)}`)
      .join("&");
    Zotero.launchURL(`${this.serverURL}/${query ? `?${query}` : ""}`);
  },

  // Caitation's key for an item: the plain Zotero key in the personal library,
  // "g<groupID>:<KEY>" in group libraries (keys are only unique per library).
  caitationKey(item) {
    if (item.libraryID === Zotero.Libraries.userLibraryID) return item.key;
    const groupID = Zotero.Groups.getGroupIDFromLibraryID(item.libraryID);
    return groupID ? `g${groupID}:${item.key}` : item.key;
  },

  findItemByKey(caitationKey) {
    const match = /^g(\d+):(.+)$/.exec(caitationKey);
    const libraryID = match
      ? Zotero.Groups.getLibraryIDFromGroupID(Number(match[1]))
      : Zotero.Libraries.userLibraryID;
    return (libraryID && Zotero.Items.getByLibraryAndKey(libraryID, match ? match[2] : caitationKey)) || null;
  },

  async selectItem(key) {
    const item = this.findItemByKey(key);
    if (!item) return;
    const window = Zotero.getMainWindow();
    window.Zotero_Tabs?.select("zotero-pane");
    await Zotero.getActiveZoteroPane().selectItem(item.id);
  },

  regularItem(item) {
    if (!item) return null;
    if (item.isRegularItem()) return item;
    return item.parentItem?.isRegularItem() ? item.parentItem : null;
  },

  // ------------------------------------------------------------ registration

  register() {
    this.sectionID = Zotero.ItemPaneManager.registerSection({
      paneID: "caitation-related",
      pluginID: this.id,
      header: { l10nID: "caitation-section-header", icon: this.rootURI + "icons/icon.svg" },
      sidenav: { l10nID: "caitation-section-sidenav", icon: this.rootURI + "icons/icon.svg" },
      onItemChange: ({ item, setEnabled }) => {
        setEnabled(Boolean(this.regularItem(item)));
        return true;
      },
      onRender: ({ body }) => {
        this.renderMessage(body, this.t("loading"));
      },
      onAsyncRender: async ({ body, item, setSectionSummary }) => {
        await this.renderRelated(body, this.regularItem(item), setSectionSummary);
      },
    });

    this.menuIDs.push(
      Zotero.MenuManager.registerMenu({
        menuID: "caitation-tools",
        pluginID: this.id,
        target: "main/menubar/tools",
        menus: [
          {
            menuType: "menuitem",
            l10nID: "caitation-menu-open",
            onCommand: () => this.openInBrowser(),
          },
          {
            menuType: "menuitem",
            l10nID: "caitation-menu-allow",
            onShowing: (event, context) => context.setVisible(!this.localAPIEnabled),
            onCommand: () => this.enableLocalAPI(),
          },
        ],
      }),
      Zotero.MenuManager.registerMenu({
        menuID: "caitation-item",
        pluginID: this.id,
        target: "main/library/item",
        menus: [
          {
            menuType: "menuitem",
            l10nID: "caitation-menu-related",
            onShowing: (event, context) => {
              const items = context.items || [];
              context.setVisible(items.length === 1 && Boolean(this.regularItem(items[0])));
            },
            onCommand: (event, context) => {
              const item = this.regularItem((context.items || [])[0]);
              if (item) {
                this.openInBrowser({ related: this.caitationKey(item), title: item.getField("title") });
              }
            },
          },
        ],
      }),
    );

    this.readerListener = (event) => this.addReaderButtons(event);
    Zotero.Reader.registerEventListener("renderTextSelectionPopup", this.readerListener, this.id);
  },

  unregister() {
    if (this.sectionID) Zotero.ItemPaneManager.unregisterSection(this.sectionID);
    for (const id of this.menuIDs) Zotero.MenuManager.unregisterMenu(id);
    if (this.readerListener) {
      Zotero.Reader.unregisterEventListener?.("renderTextSelectionPopup", this.readerListener);
    }
    this.sectionID = null;
    this.menuIDs = [];
    this.readerListener = null;
  },

  // ------------------------------------------------------------ access for the app

  get localAPIEnabled() {
    return Boolean(Zotero.Prefs.get(LOCAL_API_PREF));
  },

  enableLocalAPI() {
    Zotero.Prefs.set(LOCAL_API_PREF, true); // takes effect immediately, no restart
  },

  // Asks once (per profile) whether the app may read the library; never switches the
  // setting on without a yes.
  askForAccess(window) {
    if (this.localAPIEnabled || Zotero.Prefs.get(ASKED_PREF, true)) return;
    Zotero.Prefs.set(ASKED_PREF, true, true);
    const prompt = Services.prompt;
    const choice = prompt.confirmEx(
      window, this.t("accessTitle"), this.t("accessText"),
      prompt.BUTTON_POS_0 * prompt.BUTTON_TITLE_IS_STRING +
        prompt.BUTTON_POS_1 * prompt.BUTTON_TITLE_IS_STRING +
        prompt.BUTTON_POS_0_DEFAULT,
      this.t("accessAllow"), this.t("accessNotNow"), null, null, {},
    );
    if (choice === 0) this.enableLocalAPI();
    else Services.prompt.alert(window, this.t("accessTitle"), this.t("accessLater"));
  },

  addToWindow(window) {
    // after the window has settled, so the question does not block Zotero's start
    window.setTimeout(() => this.askForAccess(window), 2000);
    window.MozXULElement.insertFTLIfNeeded("caitation.ftl");
    const doc = window.document;
    if (doc.getElementById("caitation-stylesheet")) return;
    const link = doc.createElementNS(XHTML, "link");
    link.id = "caitation-stylesheet";
    link.rel = "stylesheet";
    link.href = this.rootURI + "caitation.css";
    doc.documentElement.appendChild(link);
  },

  removeFromWindow(window) {
    const doc = window.document;
    doc.getElementById("caitation-stylesheet")?.remove();
    doc.querySelector('[href="caitation.ftl"]')?.remove();
  },

  // ------------------------------------------------------------ item pane section

  renderMessage(body, text, { hint, retry } = {}) {
    const doc = body.ownerDocument;
    body.replaceChildren();
    const box = doc.createElementNS(XHTML, "div");
    box.className = "caitation-message";
    box.textContent = text;
    body.append(box);
    if (hint) {
      const small = doc.createElementNS(XHTML, "div");
      small.className = "caitation-hint";
      small.textContent = hint;
      body.append(small);
    }
    if (retry) {
      const button = doc.createElementNS(XHTML, "button");
      button.className = "caitation-button";
      button.textContent = this.t("retry");
      button.addEventListener("click", retry);
      body.append(button);
    }
  },

  async renderRelated(body, item, setSectionSummary) {
    if (!item) return;
    const key = this.caitationKey(item);
    body.dataset.caitationKey = key;
    let results;
    try {
      results = (await this.apiGet(`/api/related/${encodeURIComponent(key)}?top_k=6`)).results;
    } catch (error) {
      if (body.dataset.caitationKey !== key) return; // user moved on to another item
      const forbidden = error?.status === 403;
      setSectionSummary("");
      this.renderMessage(body, this.t(forbidden ? "forbidden" : "offline"), {
        hint: forbidden ? this.serverURL : this.t("offlineHint"),
        retry: () => {
          this.renderMessage(body, this.t("loading"));
          this.renderRelated(body, item, setSectionSummary);
        },
      });
      return;
    }
    if (body.dataset.caitationKey !== key) return;

    setSectionSummary(results.length ? this.t("summary", results.length) : "");
    if (!results.length) {
      this.renderMessage(body, this.t("none"));
      return;
    }

    const doc = body.ownerDocument;
    const list = doc.createElementNS(XHTML, "div");
    list.className = "caitation-list";
    for (const result of results) {
      const row = doc.createElementNS(XHTML, "div");
      row.className = "caitation-row";
      row.tabIndex = 0;
      row.setAttribute("role", "link");

      const title = doc.createElementNS(XHTML, "div");
      title.className = "caitation-title";
      title.textContent = String(result.title || "").replace(/<[^>]+>/g, "");
      const meta = doc.createElementNS(XHTML, "div");
      meta.className = "caitation-meta";
      const authors = String(result.authors || "").split(", ").filter(Boolean);
      const shortAuthors = authors.length > 2 ? `${authors[0]} et al.` : authors.join(", ");
      meta.textContent = [shortAuthors, result.year].filter(Boolean).join(" · ");
      row.append(title, meta);

      const open = () => this.selectItem(result.item_key);
      row.addEventListener("click", open);
      row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      });
      list.append(row);
    }

    const more = doc.createElementNS(XHTML, "button");
    more.className = "caitation-button";
    more.textContent = this.t("openAll");
    more.addEventListener("click", () =>
      this.openInBrowser({ related: this.caitationKey(item), title: item.getField("title") }),
    );

    body.replaceChildren(list, more);
  },

  // ------------------------------------------------------------ PDF reader

  addReaderButtons({ doc, params, append }) {
    const text = String(params?.annotation?.text || "").trim().slice(0, MAX_QUERY_CHARS);
    if (!text) return;
    const wrap = doc.createElement("div");
    wrap.style.cssText = "display:flex;gap:6px;padding:4px 6px 2px;";
    for (const [label, mode] of [[this.t("readerSearch"), "search"], [this.t("readerEvidence"), "evidence"]]) {
      const button = doc.createElement("button");
      button.textContent = label;
      button.style.cssText =
        "flex:1;padding:3px 8px;border-radius:5px;border:1px solid rgba(128,128,128,.45);" +
        "background:transparent;color:inherit;font:inherit;font-size:12px;cursor:pointer;";
      button.addEventListener("click", () => this.openInBrowser({ q: text, mode }));
      wrap.append(button);
    }
    append(wrap);
  },
};
