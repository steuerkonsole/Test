"""Export der zusammengeführten Daten als CSV oder JSON."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .db import Database


def flatten(data: dict) -> dict:
    """Verschachtelte Werte (Geld/Gehalt) in flache Spalten umwandeln."""
    out = {}
    for k, v in data.items():
        if isinstance(v, dict):
            if "per_week" in v:
                out[k] = v["per_week"]
                out[f"{k}_per_year"] = v.get("per_year")
            elif "value" in v:
                out[k] = v["value"]
                if v.get("min") != v.get("max"):
                    out[f"{k}_min"], out[f"{k}_max"] = v.get("min"), v.get("max")
            else:
                out[k] = v.get("text")
            if v.get("currency"):
                out[f"{k}_currency"] = v["currency"]
        else:
            out[k] = v
    return out


def export(db: Database, kind: str, out: str | Path, fmt: str | None = None) -> int:
    out = Path(out)
    fmt = (fmt or out.suffix.lstrip(".") or "csv").lower()
    rows = db.all_latest(kind)
    if fmt == "json":
        payload = [{"entity_key": r["entity_key"], **r["data"]} for r in rows]
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(rows)
    flat = [flatten(r["data"]) for r in rows]
    columns: list[str] = []
    for f in flat:
        for k in f:
            if k not in columns:
                columns.append(k)
    # utf-8-sig, damit Excel Umlaute korrekt anzeigt
    with out.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, delimiter=";" if fmt == "csv-de" else ",")
        w.writeheader()
        w.writerows(flat)
    return len(rows)
