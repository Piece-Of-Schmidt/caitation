# Caitation

Durchsucht deine lokale Zotero-Bibliothek (Metadaten + PDF-Volltext) semantisch über eine
kleine, lokal laufende Weboberfläche.

- Embeddings + Vektorsuche laufen komplett lokal (kostenlos, `sentence-transformers` +
  ChromaDB).
- Nur die optionale Antwort-Synthese ("Frage beantworten"-Modus) nutzt die Claude-API
  (Modell Haiku, sehr geringe Kosten pro Abfrage).

## Einmaliges Setup

Voraussetzung: Python 3.11 und Zotero 7. Rechne mit ~3 GB Arbeitsspeicher und mehreren GB
Download (PyTorch und die Modelle) sowie ~2 GB Index pro 1000 Paper.

**Einfachster Weg:** `start.bat` (Windows) bzw. `start.command` (macOS/Linux)
doppelklicken. Beim ersten Start richtet das Skript alles ein (dauert einige Minuten),
danach startet es Caitation und öffnet den Browser. Den API-Key (Schritt 2) trägst du in
die dann angelegte Datei `.env` ein.

Von Hand:

1. Virtuelle Umgebung anlegen und Pakete installieren (PowerShell):
   ```
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
2. `.env` anlegen (Kopie von `.env.example`) und deinen Anthropic-API-Key eintragen:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
   Einen Key bekommst du unter https://console.anthropic.com/ (nur nötig für den
   "Frage beantworten"-Modus; reine Suche funktioniert auch ohne Key).

   **Datenschutz:** Die Suche läuft komplett lokal. Im Frage- und im Beleg-Modus werden
   Ausschnitte aus den passenden PDFs an die Claude-API (Anthropic) geschickt.

Das Zotero-Datenverzeichnis wird automatisch aus den Zotero-Einstellungen gelesen (auch nach
einem Umzug, z.B. auf ein anderes Laufwerk); ohne eigene Einstellung gilt
`%USERPROFILE%\Zotero`. Mit `ZOTERO_DATA_DIR` in `.env` lässt es sich fest vorgeben.

Das Embedding-Modell wird über `EMBEDDING_MODEL` in `.env` gewählt (aktuell
`intfloat/multilingual-e5-base`). Jedes Modell bekommt ein eigenes Index-Verzeichnis unter
`data/` — nach einem Modellwechsel einmal den Indexer laufen lassen, alte
`chroma*`-Verzeichnisse nicht mehr genutzter Modelle können gelöscht werden.

## Bibliothek indexieren

Einmalig (und danach jederzeit erneut, wenn neue Paper hinzukommen — unveränderte Einträge
werden übersprungen und nicht neu verarbeitet):

```
.venv\Scripts\python.exe -m backend.indexer
```

Bei ~1000 Einträgen mit PDF-Anhang dauert der erste vollständige Lauf auf einer normalen
CPU einige Zeit (PDF-Textextraktion + Embedding). Folgeläufe sind deutlich schneller, da nur
neue/geänderte Einträge verarbeitet werden (auch der Volltextindex wird dann nur für diese
Einträge aktualisiert). Alternativ über den ↻-Button oben rechts in der Weboberfläche
anstoßen.

## Server starten

```
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

Danach im Browser öffnen: http://127.0.0.1:8000

Beim Start lädt der Server die Modelle im Hintergrund vor (Statusanzeige oben rechts:
„Modelle laden…" → „Bereit"), damit schon die erste Suche schnell ist.
Tastenkürzel: `/` oder `Strg+K` springt ins Suchfeld.

Der Server ist nur vom eigenen Rechner aus erreichbar und weist Anfragen anderer Websites
ab (Schutz gegen Cross-Site-Anfragen und DNS-Rebinding, siehe `backend/security.py`).
Öffne die Oberfläche deshalb über `127.0.0.1` oder `localhost`.

## Zotero-Plugin

Das Plugin „Caitation for Zotero" (Zotero 8 und 9) holt Caitation direkt in Zotero:

- **Seitenleiste am Eintrag:** Abschnitt „Ähnliche Paper (Caitation)"; ein Klick springt
  zum Eintrag.
- **PDF-Reader:** Text markieren → „In Caitation suchen" oder „Beleg prüfen".
- **Menüs:** „Caitation öffnen" unter *Werkzeuge*, „Ähnliche Paper in Caitation" im
  Rechtsklick-Menü eines Eintrags.

Das Plugin rechnet nicht selbst, es braucht die laufende Caitation-App (siehe oben).

Installation:

1. Paket bauen: `.venv\Scripts\python.exe plugin\build.py` → `dist\caitation-zotero-<version>.xpi`
2. In Zotero: *Werkzeuge → Plugins*, Zahnrad-Symbol → *Plugin aus Datei installieren…* und
   die `.xpi`-Datei wählen.

Läuft Caitation nicht unter `http://127.0.0.1:8000`, lässt sich die Adresse im
Konfigurationseditor von Zotero (*Einstellungen → Erweitert → Konfigurationseditor*) über
`extensions.caitation.serverURL` ändern.

## Lizenz und verwendete Modelle

Caitation steht unter der [MIT-Lizenz](LICENSE). Alle Python-Abhängigkeiten sind frei
lizenziert (MIT, BSD, Apache-2.0). Beim ersten Start werden zwei Modelle von Hugging Face
geladen:

- `intfloat/multilingual-e5-base` bzw. `-small` (Embeddings, MIT-Lizenz)
- `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (Ranking). Das Modell selbst steht unter
  Apache-2.0, wurde aber mit dem MS-MARCO-Datensatz trainiert, dessen Bedingungen nur
  nicht-kommerzielle Nutzung erlauben. Für Forschung und Lehre passt das; wer Caitation
  kommerziell einsetzen will, schaltet den Reranker mit `RERANKER_MODEL=` in `.env` ab
  oder wählt ein anderes Modell.

„Zotero" ist eine Marke der Corporation for Digital Scholarship; Caitation ist ein
unabhängiges Projekt.

## Wenn etwas nicht klappt

Fehler und Laufzeiten werden in `data/caitation.log` protokolliert. Schick diese Datei
mit, wenn du ein Problem meldest. Sie enthält keine PDF-Inhalte, aber den Anfang deiner
Suchanfragen; sieh sie vor dem Verschicken kurz durch.

## Entwicklung

```
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest
```

Offene Punkte und geplante Schritte stehen in [docs/ROADMAP.md](docs/ROADMAP.md).

## Funktionen

- **Hybrid-Suche**: semantische Vektorsuche + klassische Stichwortsuche (BM25 über SQLite
  FTS5), zusammengeführt per Reciprocal Rank Fusion. Findet sowohl inhaltlich Ähnliches als
  auch exakte Begriffe/Autorennamen ("FOMC", "Malmendier"). Vorläufige Treffer erscheinen
  sofort, das präzise Ranking ersetzt sie wenige Sekunden später; Suchbegriffe werden in
  den Fundstellen hervorgehoben.
- **Filter**: Treffer nach Jahr, Item-Typ, Tag oder Zotero-Sammlung einschränken
  (aufklappbares "Filter"-Panel unter dem Suchfeld).
- **Direktlinks**: jeder Treffer verlinkt auf den Eintrag in Zotero (`zotero://select`) und
  auf das PDF mit Sprung zur Fundstellen-Seite.
- **Frage-Modus mit Chat**: Claude beantwortet Fragen anhand der Treffer mit APA-Zitaten
  inkl. Seitenzahlen und Literaturverzeichnis; Folgefragen behalten den Gesprächskontext
  ("Neues Gespräch" setzt zurück). Benötigt ANTHROPIC_API_KEY.
- **Mehrere Fundstellen**: pro Paper sind bis zu 3 Fundstellen aufklappbar.
- **Ähnliche Paper**: jeder Treffer verlinkt auf die semantisch ähnlichsten Einträge der
  eigenen Bibliothek (praktisch für Literature Reviews).
- **Auto-Reindex**: beim Serverstart wird geprüft, ob sich die Zotero-Bibliothek geändert
  hat; wenn ja, läuft im Hintergrund ein inkrementeller Reindex.
- **Dubletten**: der Bereich "Dubletten" listet Einträge mit gleicher DOI oder
  gleichem Titel gruppiert auf (zum Zusammenführen in Zotero). In Suchergebnissen werden
  Dubletten automatisch zusammengefasst und mit einem Badge markiert.
- **Deine Highlights**: PDF-Annotationen aus dem Zotero-Reader werden mitindexiert und in
  der Suche bevorzugt (grüner Badge); Checkbox "nur meine Highlights" schränkt die Suche
  auf markierte Stellen ein. Im Frage-Modus zitiert Claude deine Highlights bevorzugt.
- **Zitatprüfung**: Im Frage- und Beleg-Modus wird jedes wörtliche Zitat gegen die
  Quelltexte geprüft und markiert: ✓ wörtlich belegt, ≈ abweichend, ✗ nicht gefunden
  (mit Quelle und Seite). Nicht gefundene Zitate vor dem Übernehmen im PDF prüfen.
- **Nicht nur PDFs**: Auch gespeicherte Webseiten, EPUBs, Textdateien, verlinkte Dateien
  und Gruppenbibliotheken werden durchsucht.
- **Beleg finden**: dritter Modus — Behauptung einfügen, das Tool prüft pro Quelle, ob sie
  die Behauptung stützt oder ihr widerspricht (mit wörtlichem Zitat und APA-Beleg).
- **Streaming & Markdown**: Antworten erscheinen live beim Generieren und formatiert; mit
  „Stopp" lässt sich eine laufende Antwort abbrechen.
- **Export**: BibTeX-Download der Trefferliste oder einzelner Treffer, Kopieren-Button an
  jeder Antwort.
- **Reranker**: ein Cross-Encoder sortiert die Top-50-Kandidaten präzise um (kostet auf
  dieser CPU 7–10 s, läuft aber hinter der Sofort-Vorschau; wiederholte Anfragen kommen aus
  dem Cache; abschaltbar mit `RERANKER_MODEL=` in `.env`, größeres Modell dort wählbar).
- **OCR**: gescannte PDFs ohne Textebene werden beim Indexieren automatisch per OCR
  erfasst (rapidocr, lokal).
- **Dashboard**: Kennzahlen, Einträge pro Jahr, Publikationstypen, Sammlungen, Top-Tags und
  eine Themen-Landkarte der ganzen Bibliothek (Nähe = inhaltliche Ähnlichkeit, Farbe = von
  Claude benanntes Themencluster; Legende hebt ein Thema hervor). Klick auf Tag, Sammlung
  oder Typ setzt den passenden Suchfilter.
- **Hell/Dunkel**: die Oberfläche folgt dem Farbschema des Systems.
