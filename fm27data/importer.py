"""Import einer FM-Exportdatei in die Datenbank."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .classify import classify, entity_key
from .db import Database
from .normalize import normalize_row
from .parsers import SUPPORTED_EXTENSIONS, parse_file


@dataclass
class ImportResult:
    file: str
    status: str  # "imported" | "skipped" | "error"
    kind: str | None = None
    rows: int = 0
    import_id: int | None = None
    message: str = ""

    def __str__(self) -> str:
        if self.status == "imported":
            return f"✔ {self.file}: {self.rows} Zeilen als '{self.kind}' importiert (#{self.import_id})"
        if self.status == "skipped":
            return f"• {self.file}: übersprungen ({self.message})"
        return f"✘ {self.file}: Fehler – {self.message}"


_DATE_IN_NAME = re.compile(r"(\d{4})[-_.](\d{1,2})[-_.](\d{1,2})|(\d{1,2})[-_.](\d{1,2})[-_.](\d{4})")


def guess_game_date(name: str) -> str | None:
    """Spieldatum aus dem Dateinamen ableiten, z.B. 'kader_2027-08-15.html'."""
    m = _DATE_IN_NAME.search(name)
    if not m:
        return None
    if m.group(1):
        y, mo, d = m.group(1), m.group(2), m.group(3)
    else:
        d, mo, y = m.group(4), m.group(5), m.group(6)
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def import_file(db: Database, path: str | Path, *, kind: str | None = None, game_date: str | None = None,
                force: bool = False) -> ImportResult:
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return ImportResult(path.name, "skipped", message="Dateityp nicht unterstützt")
    try:
        digest = sha256_file(path)
        if not force and db.has_import(digest):
            return ImportResult(path.name, "skipped", message="bereits importiert")
        table = parse_file(path)
        normalized = [normalize_row(pairs) for pairs in table.as_dicts()]
        normalized = [n for n in normalized if any(v is not None for v in n.values())]
        if not normalized:
            return ImportResult(path.name, "skipped", message="keine Datenzeilen")
        keys: set[str] = set()
        for n in normalized:
            keys.update(k for k, v in n.items() if v is not None)
        detected = kind or classify(keys)
        records = []
        seen: dict[str, int] = {}
        for i, (data, pairs) in enumerate(zip(normalized, table.as_dicts())):
            key = entity_key(detected, data, i)
            if key in seen:  # gleiche Entität mehrfach in einer Datei → eindeutig machen
                seen[key] += 1
                key = f"{key}#{seen[key]}"
            else:
                seen[key] = 1
            records.append({"entity_key": key, "data": data, "raw": [[h, v] for h, v in pairs]})
        if force and db.has_import(digest):
            digest = f"{digest}:{len(db.imports())}"
        import_id = db.add_import(
            file=path.name, sha256=digest, kind=detected, title=table.title, source_format=table.source_format,
            game_date=game_date or guess_game_date(path.name), headers=table.headers, records=records,
        )
        return ImportResult(path.name, "imported", detected, len(records), import_id)
    except Exception as exc:  # noqa: BLE001 – Fehler pro Datei melden, nicht abbrechen
        return ImportResult(path.name, "error", message=str(exc))


def import_path(db: Database, path: str | Path, **kw) -> list[ImportResult]:
    path = Path(path)
    if path.is_dir():
        files = sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS)
        return [import_file(db, p, **kw) for p in files]
    return [import_file(db, path, **kw)]
