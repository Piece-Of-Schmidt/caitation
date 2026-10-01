# Roadmap: von der persönlichen App zum Werkzeug für Kolleg:innen

Caitation bleibt **kostenlos und Open Source**. Ziel ist, dass Kolleg:innen es mit ihrer
eigenen Zotero-Bibliothek nutzen können: ohne Anpassungen am Code, auf Windows und macOS,
und mit verlässlichen Belegen.

Stand: 2026-10-01. Erledigtes wird abgehakt, nicht gelöscht.

## 1. Technische Grundlagen

- [x] Versionsverwaltung (Git)
- [x] `requirements.txt` mit festen Versionen; alle direkt importierten Pakete aufgeführt
      (vorher fehlten `scikit-learn` und `numpy`, und statt `rapidocr-onnxruntime` stand
      das falsche Paket `rapidocr` drin, sodass eine frische Installation kein OCR hatte)
- [x] Schutz des lokalen Servers gegen fremde Websites (Host-Prüfung gegen DNS-Rebinding,
      Herkunftsprüfung gegen Cross-Site-Anfragen)
- [x] Automatische Tests für die Kernlogik (`pytest`)
- [x] Automatische Testläufe (GitHub Actions auf Windows, macOS, Linux), grün seit 2026-10-01
- [x] Startskripte `start.bat` / `start.command` (richten beim ersten Start alles ein)
- [x] **Kein vorinstalliertes Python mehr nötig** (2026-10-01): Die Startskripte holen
      `uv` (feste Version, Prüfsumme) und richten damit Python 3.11 und alle Pakete im
      App-Ordner ein (frische Einrichtung unter Windows: 88 s). Die CI prüft genau diesen
      Weg auf Windows, macOS und Linux.
- [x] **Windows-Installer** (Inno Setup, 2026-10-01, v0.1.1): pro Benutzer ohne Adminrechte,
      Startmenü-Einträge, saubere Deinstallation; gebaut von der CI. Noch nicht signiert
      (SmartScreen-Hinweis); für macOS gibt es weiterhin nur `start.command`.
- [x] Fehlerprotokoll `data/caitation.log`; fehlgeschlagener Reindex wird in der Oberfläche angezeigt

## 2. Entscheidungen

- [x] **Lizenz: MIT** (2026-10-01). Dafür wurde PyMuPDF (AGPL) durch `pypdfium2`
      (BSD-3-Clause/Apache-2.0) ersetzt. Vergleich an 41 PDFs: 97,8 % identische Wörter,
      Ligaturen und Akzente werden sogar sauberer ausgelesen.
- [x] **Architektur: Zotero-Plugin + lokale Begleit-App** (2026-10-01). Das Plugin
      (`plugin/`, Zotero 8/9) ist die Oberfläche in Zotero; die Python-App rechnet lokal.
- [x] **Plugin in echtem Zotero getestet** (Zotero 9.0.6, 2026-10-01).
- [x] **Veröffentlicht** (2026-10-01): github.com/Piece-Of-Schmidt/caitation, Release v0.1.0
      mit Plugin-Datei; automatische Plugin-Updates über `plugin/updates.json`.
      Neue Plugin-Version: Version in `plugin/src/manifest.json` erhöhen, `plugin/build.py`,
      Release mit der `.xpi` anlegen und den Eintrag in `plugin/updates.json` ergänzen.
- [x] **Warnung bei unbekanntem Datenbankformat** (2026-10-01, v0.1.1): Ist Zoteros
      `userdata`-Version neuer als 125 (Zotero 9.0.6), warnt die Statusanzeige; scheitert das
      Lesen, nennt die Fehlermeldung die Ursache.
- [x] **Zugriff auf Zotero über die offizielle lokale API** (2026-10-01, v0.2.0) statt einer
      Kopie der Datenbankdatei (Entscheidung Tobias: nur API, keine Rückfalloption). Caitation
      fragt jede Minute die Bibliotheksversion ab und übernimmt Änderungen automatisch; der
      zuletzt gelesene Stand liegt in `data/library.json`, damit die Suche ohne Zotero läuft. Das
      Plugin fragt einmalig nach der Freigabe der Schnittstelle. Einmalige Migration ohne
      Neuindexierung (an der echten Bibliothek: 1.228 von 1.228 Einträgen übernommen).

## 3. Lücken bei fremden Bibliotheken

- [x] **Verlinkte Dateien** (absolut und relativ zum Zotero-Basisverzeichnis), **EPUBs,
      gespeicherte Webseiten und Textdateien** werden indexiert (2026-10-01).
- [x] **Gruppenbibliotheken:** eigene Schlüssel, korrekte Zotero-Links, Filter
      „Bibliothek" (2026-10-01). Noch ungetestet mit einer echten Gruppe.
- [x] **macOS und Linux:** Zotero-Profil wird an allen drei Orten gesucht (2026-10-01).
      Noch ungetestet auf einem echten Mac.
- [x] **Erste Indexierung zweiphasig** (2026-10-01): erst Titel, Abstracts, Notizen und
      Highlights aller Einträge (Minuten), dann die Volltexte; die Stichwortsuche wird
      alle 25 Einträge aktualisiert.
- [x] **Restzeit-Anzeige** beim Indexieren (2026-10-01), gewichtet nach Dateigröße und
      hochgerechnet aus dem bisherigen Tempo des Rechners.
- [x] **GPU bzw. Apple Silicon** werden automatisch genutzt (2026-10-01); `start.bat`
      installiert bei NVIDIA-Karten die GPU-Version von PyTorch. Ungetestet mangels Hardware.
- [x] **Abgebrochene Indexierung wird beim nächsten Start fortgesetzt** (2026-10-01; vorher
      erst, wenn sich in Zotero etwas änderte).
- [x] **Systemanforderungen dokumentiert** (README, 2026-10-01; gemessen: 2,9 GB RAM
      Spitze, 1,3 GB Pakete, 1,5–2,1 GB Modelle, ca. 2 GB Index pro 1.000 Paper).
- [ ] An weiteren Bibliotheken testen (andere Fächer, Sprachen, Größen).

## 4. Verlässlichkeit der Belege

- [x] **Saubere Volltexte** (2026-10-01, v0.1.1): Trenn- und Steuerzeichen aus PDFs werden
      entfernt (betraf 18 % der Abschnitte); PDFs mit unlesbarer Textebene werden erkannt und
      per OCR gelesen; bestehende Indexe werden einmalig in place repariert.

- [x] **Automatische Zitatprüfung im Beleg- und Frage-Modus** (2026-10-01): jedes
      wörtliche Zitat wird als „wörtlich belegt", „abweichend" oder „nicht gefunden"
      markiert, mit Quelle und Seite (`backend/verification.py`).
- [x] Zitatprüfung gleicht die zitierte Seitenzahl (z.B. „S. 4") mit der Fundstelle ab
      (Fundseite oder Folgeseite gilt als passend, da Auszüge über Seitengrenzen reichen).
- [x] **Werkzeug zur Messung der Suchqualität** (`eval/evaluate.py`, 2026-10-01). Erste 6
      Fälle: mit Reranker 6/6 in den Top 8 (MRR 0,81), ohne 5/6 (MRR 0,67).
- [ ] Testsammlung auf ~50 Fälle erweitern (Fragen und erwartete Paper aus der eigenen
      Arbeit; das kann nur jemand festlegen, der die Literatur kennt).

- [ ] Dubletten-Erkennung: Artikel und gespeicherte Webseite desselben Papers werden nicht
      zusammengefasst, wenn der Webseitentitel Zusätze trägt („… | Publications | CESifo“).

## 5. Rechtliches und Datenschutz (auch für ein freies Projekt)

- [x] **Reranker-Modell** (in der README dokumentiert): `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` ist mit dem
      MS-MARCO-Datensatz trainiert, dessen Bedingungen nur nicht-kommerzielle Nutzung
      erlauben. Für Forschung an der Uni passt das; in der Doku erwähnen und ggf. eine
      Alternative anbieten.
- [x] **Name** („Caitation for Zotero", Markenhinweis in der README): „Zotero" ist eine geschützte Marke; die Namensrichtlinien von Zotero
      beachten (z.B. „Caitation für Zotero" statt „Zotero-…").
- [x] **Datenschutzhinweis** (README): Frage- und Beleg-Modus schicken Ausschnitte aus den PDFs an
      die Claude-API (Anthropic). Das muss vorher klar erkennbar sein; jede Person nutzt
      ihren eigenen API-Key. Die reine Suche bleibt komplett lokal.

## 6. Pilotphase

- [ ] 5–10 Kolleg:innen testen lassen, bewusst aus anderen Fächern und mit macOS.
