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
- [ ] Automatische Testläufe bei jeder Änderung (CI, z.B. GitHub Actions auf Windows + macOS)
- [ ] Einfache Installation für Nicht-Programmierer:innen (Installer oder ein Startskript)
- [ ] Fehlerprotokoll in eine Datei, damit Kolleg:innen bei Problemen etwas schicken können

## 2. Entscheidungen

- [x] **Lizenz: MIT** (2026-10-01). Dafür wurde PyMuPDF (AGPL) durch `pypdfium2`
      (BSD-3-Clause/Apache-2.0) ersetzt. Vergleich an 41 PDFs: 97,8 % identische Wörter,
      Ligaturen und Akzente werden sogar sauberer ausgelesen.
- [x] **Architektur: Zotero-Plugin + lokale Begleit-App** (2026-10-01). Das Plugin
      (`plugin/`, Zotero 8/9) ist die Oberfläche in Zotero; die Python-App rechnet lokal.
- [ ] **Plugin in echtem Zotero testen** (bisher nur gebaut, Syntax und Paket geprüft).
- [ ] **Update-Adresse des Plugins** zeigt auf ein noch nicht existierendes
      GitHub-Repository (`Piece-Of-Schmidt/caitation`); beim Veröffentlichen anlegen und
      `plugin/updates.json` bereitstellen. Plugin-ID: `caitation@piece-of-schmidt`.
- [ ] **Zugriff auf Zotero** über offizielle Schnittstellen (Plugin-API bzw. lokale API)
      statt die Datenbankdatei zu kopieren; Zotero rät von direktem Datenbankzugriff ab,
      weil sich das Schema ändern kann.

## 3. Lücken bei fremden Bibliotheken

- [ ] **Verlinkte Dateien** (z.B. aus ZotFile-Zeiten, Pfad nicht im Zotero-Speicher)
      werden bisher ignoriert, ebenso EPUBs und gespeicherte Webseiten.
- [ ] **Gruppenbibliotheken** werden mit der eigenen Bibliothek vermischt; der Link
      „In Zotero" funktioniert für Gruppeneinträge nicht (`zotero://select/groups/…`).
- [ ] **macOS und Linux.** Die automatische Erkennung des Zotero-Ordners liest bisher nur
      das Windows-Profil (`%APPDATA%`).
- [ ] **Erste Indexierung beschleunigen.** Rund 9 Stunden für 1000 Paper auf einer
      Büro-CPU. Suche sollte nach Minuten nutzbar sein: Metadaten zuerst, PDFs im
      Hintergrund; ehrliche Zeitschätzung; GPU bzw. Apple Silicon nutzen, wenn vorhanden.
- [ ] **Systemanforderungen dokumentieren** (~3 GB RAM, mehrere GB Download für Modelle
      und Pakete, ~2 GB Index pro 1000 Paper).
- [ ] An weiteren Bibliotheken testen (andere Fächer, Sprachen, Größen).

## 4. Verlässlichkeit der Belege

- [ ] **Automatische Zitatprüfung im Beleg- und Frage-Modus.** Jedes wörtliche Zitat
      wird gegen den PDF-Text geprüft (inkl. Seitenzahl) und sichtbar als „geprüft"
      oder „nicht gefunden" markiert. Ein erfundenes Zitat in einer Arbeit wäre für
      Nutzer:innen ein ernstes Problem.
- [ ] **Testsammlung** mit ~50 Fragen und den jeweils erwarteten Papern, damit sich
      Änderungen am Ranking messen lassen statt nur stichprobenartig ansehen.

## 5. Rechtliches und Datenschutz (auch für ein freies Projekt)

- [ ] **Reranker-Modell:** `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` ist mit dem
      MS-MARCO-Datensatz trainiert, dessen Bedingungen nur nicht-kommerzielle Nutzung
      erlauben. Für Forschung an der Uni passt das; in der Doku erwähnen und ggf. eine
      Alternative anbieten.
- [ ] **Name:** „Zotero" ist eine geschützte Marke; die Namensrichtlinien von Zotero
      beachten (z.B. „Caitation für Zotero" statt „Zotero-…").
- [ ] **Datenschutzhinweis:** Frage- und Beleg-Modus schicken Ausschnitte aus den PDFs an
      die Claude-API (Anthropic). Das muss vorher klar erkennbar sein; jede Person nutzt
      ihren eigenen API-Key. Die reine Suche bleibt komplett lokal.

## 6. Pilotphase

- [ ] 5–10 Kolleg:innen testen lassen, bewusst aus anderen Fächern und mit macOS.
