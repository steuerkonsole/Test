"""SQLite-Speicher mit Verlauf.

* ``imports``  – ein Eintrag pro importierter Datei
* ``records``  – jede Zeile jedes Imports (Schnappschuss, unverändert)
* ``entities`` – zusammengeführter aktueller Stand je Spieler/Verein/...:
  Felder aus verschiedenen Exporten (z.B. Attribut-Ansicht + Statistik-Ansicht)
  werden kombiniert, neuere Importe überschreiben ältere Werte.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS imports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file        TEXT NOT NULL,
    sha256      TEXT NOT NULL UNIQUE,
    kind        TEXT NOT NULL,
    title       TEXT,
    source_format TEXT,
    game_date   TEXT,
    imported_at TEXT NOT NULL,
    row_count   INTEGER NOT NULL,
    headers     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id   INTEGER NOT NULL REFERENCES imports(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    entity_key  TEXT NOT NULL,
    name        TEXT,
    club        TEXT,
    data        TEXT NOT NULL,
    raw         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_entity ON records(kind, entity_key, import_id);
CREATE INDEX IF NOT EXISTS idx_records_import ON records(import_id);
CREATE TABLE IF NOT EXISTS entities (
    kind        TEXT NOT NULL,
    entity_key  TEXT NOT NULL,
    name        TEXT,
    club        TEXT,
    data        TEXT NOT NULL,
    import_id   INTEGER NOT NULL,
    PRIMARY KEY (kind, entity_key)
);
"""

_SAFE_KEY = re.compile(r"^[a-z0-9_]+$")


def _value_expr(key: str) -> str:
    """SQL-Ausdruck für den vergleichbaren Wert eines Feldes.

    Gehalt → pro Woche, Geldbetrag → Mittelwert, sonstige Objekte (z.B. "Unverkäuflich") → NULL.
    """
    return (f"COALESCE(json_extract(e.data, '$.{key}.per_week'), json_extract(e.data, '$.{key}.value'),"
            f" CASE WHEN json_type(e.data, '$.{key}') IN ('integer', 'real', 'text')"
            f" THEN json_extract(e.data, '$.{key}') END)")


class Database:
    def __init__(self, path: str | Path = "fm27data.sqlite3"):
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------ write

    def has_import(self, sha256: str) -> bool:
        with self._lock:
            return self.conn.execute("SELECT 1 FROM imports WHERE sha256=?", (sha256,)).fetchone() is not None

    def add_import(self, *, file: str, sha256: str, kind: str, title: str | None, source_format: str,
                   game_date: str | None, headers: list[str], records: list[dict]) -> int:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock, self.conn:
            cur = self.conn.execute(
                "INSERT INTO imports(file, sha256, kind, title, source_format, game_date, imported_at, row_count, headers)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (file, sha256, kind, title, source_format, game_date, now, len(records), json.dumps(headers, ensure_ascii=False)),
            )
            import_id = cur.lastrowid
            self.conn.executemany(
                "INSERT INTO records(import_id, kind, entity_key, name, club, data, raw) VALUES (?,?,?,?,?,?,?)",
                [
                    (import_id, kind, r["entity_key"], r["data"].get("name"), r["data"].get("club"),
                     json.dumps(r["data"], ensure_ascii=False), json.dumps(r["raw"], ensure_ascii=False))
                    for r in records
                ],
            )
            for r in records:
                row = self.conn.execute("SELECT data FROM entities WHERE kind=? AND entity_key=?",
                                        (kind, r["entity_key"])).fetchone()
                merged = json.loads(row["data"]) if row else {}
                merged.update(r["data"])  # Spalten des neuen Exports gewinnen, fehlende bleiben erhalten
                self._upsert_entity(kind, r["entity_key"], merged, import_id)
        return import_id

    def _upsert_entity(self, kind: str, key: str, data: dict, import_id: int) -> None:
        self.conn.execute(
            "INSERT INTO entities(kind, entity_key, name, club, data, import_id) VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(kind, entity_key) DO UPDATE SET name=excluded.name, club=excluded.club,"
            " data=excluded.data, import_id=excluded.import_id",
            (kind, key, data.get("name"), data.get("club"), json.dumps(data, ensure_ascii=False), import_id),
        )

    def delete_import(self, import_id: int) -> None:
        with self._lock, self.conn:
            affected = self.conn.execute(
                "SELECT DISTINCT kind, entity_key FROM records WHERE import_id=?", (import_id,)
            ).fetchall()
            self.conn.execute("DELETE FROM records WHERE import_id=?", (import_id,))
            self.conn.execute("DELETE FROM imports WHERE id=?", (import_id,))
            for a in affected:  # zusammengeführten Stand aus den verbleibenden Importen neu aufbauen
                rows = self.conn.execute(
                    "SELECT data, import_id FROM records WHERE kind=? AND entity_key=? ORDER BY import_id",
                    (a["kind"], a["entity_key"]),
                ).fetchall()
                if not rows:
                    self.conn.execute("DELETE FROM entities WHERE kind=? AND entity_key=?", (a["kind"], a["entity_key"]))
                    continue
                merged: dict = {}
                for r in rows:
                    merged.update(json.loads(r["data"]))
                self._upsert_entity(a["kind"], a["entity_key"], merged, rows[-1]["import_id"])

    # ------------------------------------------------------------------- read

    def imports(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute("SELECT * FROM imports ORDER BY id DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["headers"] = json.loads(d["headers"])
            out.append(d)
        return out

    def kinds(self) -> dict[str, int]:
        with self._lock:
            rows = self.conn.execute("SELECT kind, COUNT(*) AS n FROM entities GROUP BY kind ORDER BY kind").fetchall()
        return {r["kind"]: r["n"] for r in rows}

    def latest(self, kind: str, *, search: str = "", filters: dict | None = None, sort: str | None = None,
               desc: bool = True, limit: int = 100, offset: int = 0) -> tuple[int, list[dict]]:
        """Aktueller (zusammengeführter) Stand aller Entitäten einer Art."""
        where, params = "WHERE e.kind = ?", [kind]
        if search:
            where += " AND (e.name LIKE ? OR e.club LIKE ? OR e.data LIKE ?)"
            like = f"%{search}%"
            params += [like, like, like]
        for key, (op, val) in (filters or {}).items():
            if not _SAFE_KEY.match(key) or op not in (">=", "<=", "=", "LIKE"):
                continue
            where += f" AND {_value_expr(key)} {op} ?"
            params.append(f"%{val}%" if op == "LIKE" else val)
        order = "e.name COLLATE NOCASE ASC"
        if sort and _SAFE_KEY.match(sort):
            expr = _value_expr(sort)
            order = f"{expr} IS NULL, {expr} {'DESC' if desc else 'ASC'}, e.name COLLATE NOCASE"
        with self._lock:
            total = self.conn.execute(f"SELECT COUNT(*) FROM entities e {where}", params).fetchone()[0]
            rows = self.conn.execute(
                f"SELECT e.entity_key, e.import_id, e.data FROM entities e {where} ORDER BY {order} LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
        return total, [self._row(r) for r in rows]

    def all_latest(self, kind: str) -> list[dict]:
        _, rows = self.latest(kind, limit=-1)
        return rows

    def history(self, kind: str, entity_key: str) -> list[dict]:
        """Alle Schnappschüsse einer Entität (z.B. Entwicklung von Fähigkeit/Marktwert)."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT r.entity_key, r.import_id, r.data, i.game_date, i.imported_at, i.file"
                " FROM records r JOIN imports i ON i.id = r.import_id"
                " WHERE r.kind=? AND r.entity_key=? ORDER BY r.import_id",
                (kind, entity_key),
            ).fetchall()
        out = []
        for r in rows:
            d = self._row(r)
            d.update(game_date=r["game_date"], imported_at=r["imported_at"], file=r["file"])
            out.append(d)
        return out

    def columns(self, kind: str) -> list[str]:
        """Alle Datenfelder, die für eine Art vorkommen (in sinnvoller Reihenfolge)."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT DISTINCT j.key FROM entities e, json_each(e.data) j WHERE e.kind=?", (kind,)
            ).fetchall()
        keys = [r[0] for r in rows]
        front = ["name", "position", "age", "club", "nationality", "ca", "pa", "value", "wage", "expires"]
        return [k for k in front if k in keys] + sorted(k for k in keys if k not in front)

    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        return {"entity_key": r["entity_key"], "import_id": r["import_id"], "data": json.loads(r["data"])}
