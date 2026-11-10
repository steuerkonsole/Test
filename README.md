# FM27 Datenzentrale (`fm27data`)

Liest Daten aus **Football Manager 27** automatisch aus: Spieler, Mitarbeiter, Vereine, Tabellen und Spiele.
Die Daten werden bereinigt, in einer lokalen SQLite-Datenbank mit Verlauf gespeichert und über eine
Weboberfläche, die Kommandozeile oder als CSV/JSON bereitgestellt.

- **Automatisch:** überwacht den FM27-Ordner und importiert jeden neuen Export sofort
- **Alle FM-Exportformate:** Webseite (`.html`), Textdatei (`.txt`/`.rtf`) und `.csv`
- **Englische und deutsche** FM-Oberfläche: Spaltennamen werden erkannt und vereinheitlicht
- **Saubere Werte:** `€25M - €32M` → Min./Max./Mittelwert, `35.000 € p.W.` → Wochengehalt,
  `6'2"` → 188 cm, verdeckte Attribute `10-13` → 11,5, und `Nat` wird als Nationalität bzw. Grundfitness erkannt
- **Zusammenführen:** Mehrere Ansichten desselben Spielers (z.B. Attribute + Statistiken) werden kombiniert
- **Verlauf:** Jeder Import ist ein Schnappschuss, also lassen sich Entwicklung von Marktwert, Fähigkeit usw. über die Saisons verfolgen
- **Keine Abhängigkeiten:** nur Python ≥ 3.10 (Standardbibliothek)

## Wie kommen die Daten aus dem Spiel?

FM kann jede Tabellenansicht (Kader, Spielersuche, Scouting, Mitarbeiter, Tabellen, Spielplan …) als Datei
ausgeben. Die App liest genau diese Dateien:

1. In FM27 die gewünschte Ansicht öffnen und die Spalten einstellen (Ansicht anpassen, z.B. alle Attribute einblenden).
2. Bei Listen erst alle Zeilen markieren (**Strg+A**), dann **Strg+P** (Drucken).
3. **„Webseite“** (empfohlen) oder **„Textdatei“** wählen und im FM27-Benutzerordner speichern.
4. Die App erkennt die Datei innerhalb von Sekunden und importiert sie.

**Tipps**
- Nimm die Spalte **UID** (Eindeutige ID) in deine Ansichten auf. Damit wird jeder Spieler über alle
  Exporte und Saisons sicher wiedererkannt. Ohne UID wird über Name + Geburtsdatum/Nationalität/Verein zugeordnet.
- Wenn der Dateiname ein Datum enthält (z.B. `kader_2027-08-15.html`), wird es als Spieldatum für den Verlauf genutzt.
- Bei verdeckten Attributen (nicht voll gescoutet) zeigt FM Bereiche wie `10-13`. Gespeichert wird der Mittelwert.

> **Hinweis:** Spielstände (`.fm`) sind komprimiert und proprietär, und Live-Speicherauslesen erfordert
> versionsspezifische Speicheradressen. Beides wird bewusst **nicht** genutzt. Der Exportweg ist stabil und
> funktioniert unabhängig von Spielupdates. Sollte FM27 die Druck-/Exportfunktion ändern, lassen sich
> beliebige HTML-, CSV- oder Pipe-Tabellen weiterhin importieren.

## Installation & Start

```bash
pip install .            # optional – alternativ direkt mit "python -m fm27data" starten
fm27data run --open      # Ordner überwachen + Weboberfläche öffnen (http://127.0.0.1:8027)
```

Unter Windows genügt ein Doppelklick auf **`start_windows.bat`**.

Der FM27-Ordner wird automatisch gesucht (z.B. `Dokumente\Sports Interactive\Football Manager 27`).
Ein anderer Ordner lässt sich mit `--folder` angeben:

```bash
fm27data run --folder "D:\FM27 Exporte" --recursive
```

## Weboberfläche

- Reiter je Datenart (Spieler, Mitarbeiter, Vereine, Tabelle, Spiele …)
- Suche, Min./Max.-Filter auf jedes Feld, Sortierung per Klick auf die Spalte
- Farbige Attribute (1–20), Klick auf eine Zeile zeigt alle Daten und den Verlauf
- Dateien per Drag & Drop hochladen, CSV/JSON-Download, Importe verwalten bzw. löschen
- Aktualisiert sich automatisch, sobald neue Exporte importiert wurden

## Kommandozeile

```bash
fm27data import exporte/                  # Datei(en) oder ganze Ordner importieren
fm27data watch                            # nur Ordner überwachen
fm27data serve                            # nur Weboberfläche
fm27data list                             # Übersicht der Datenarten
fm27data list players -f "age<=21" -f "pa>=150" --sort value -c name,age,club,value,ca,pa
fm27data list players -s "Müller" --json
fm27data export players spieler.csv       # CSV (Excel: --format csv-de für Semikolon)
fm27data export players spieler.json
fm27data imports                          # Importverlauf
fm27data delete 3                         # Import #3 entfernen (Daten werden neu zusammengeführt)
```

Globale Option: `--db pfad.sqlite3` (Standard: `fm27data.sqlite3` im aktuellen Ordner).

## JSON-API

| Endpunkt | Beschreibung |
|---|---|
| `GET /api/kinds` | Datenarten mit Anzahl |
| `GET /api/records?kind=players&q=&sort=value&desc=1&min.age=18&max.age=21&limit=100&offset=0` | Datensätze |
| `GET /api/columns?kind=players` | verfügbare Felder |
| `GET /api/history?kind=players&key=uid:2000123456` | Verlauf einer Entität |
| `GET /api/export?kind=players&format=csv\|csv-de\|json` | Download |
| `GET /api/imports` · `DELETE /api/imports/<id>` | Importe |
| `POST /api/upload?filename=x.html` (Rohdaten im Body) | Datei importieren |

## Aufbau

```
fm27data/
  parsers.py    HTML-, Pipe-Text-, RTF- und CSV-Parser (inkl. Zeichensatzerkennung)
  normalize.py  Spaltennamen (EN/DE) → einheitliche Schlüssel, Wert-Parser (Geld, Gehalt, Größe, Attribute …)
  classify.py   Erkennung der Datenart + stabiler Schlüssel je Spieler/Verein
  importer.py   Import einer Datei (Duplikatschutz per SHA-256)
  db.py         SQLite: imports / records (Schnappschüsse) / entities (zusammengeführter Stand)
  watcher.py    Ordnerüberwachung (wartet, bis eine Datei fertig geschrieben ist)
  web.py        Weboberfläche + JSON-API
  export.py     CSV/JSON-Export
  cli.py        Kommandozeile
```

Unbekannte Spalten gehen nicht verloren: Sie werden unter einem vereinfachten Namen gespeichert
(Zahlen werden erkannt), und die Originalzeile liegt zusätzlich unverändert in `records.raw`.

## Tests

```bash
python -m unittest discover -s tests -t .
```
