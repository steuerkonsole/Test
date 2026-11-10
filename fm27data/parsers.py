"""Parser für die Exportformate von Football Manager.

FM kann jede Tabellenansicht über "Drucken" (Strg+P) exportieren als
  * Webseite (.html)  – eine HTML-Tabelle
  * Textdatei (.txt / ältere Versionen .rtf) – eine Pipe-getrennte Tabelle
Zusätzlich werden CSV-Dateien (z.B. aus Tabellenkalkulationen oder anderen
Tools) unterstützt.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

SUPPORTED_EXTENSIONS = {".html", ".htm", ".txt", ".rtf", ".csv"}


@dataclass
class Table:
    headers: list[str]
    rows: list[list[str]]
    source_format: str
    title: str | None = None
    meta: dict = field(default_factory=dict)

    def as_dicts(self) -> list[list[tuple[str, str]]]:
        """Zeilen als Liste von (Header, Wert)-Paaren.

        Bewusst keine dicts, da FM doppelte Spaltennamen erzeugen kann
        (z.B. "Nat" = Nationalität UND Natürliche Fitness).
        """
        out = []
        for row in self.rows:
            padded = row + [""] * (len(self.headers) - len(row))
            out.append(list(zip(self.headers, padded)))
        return out


class ParseError(ValueError):
    pass


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------

def read_text(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _clean(cell: str) -> str:
    return re.sub(r"\s+", " ", cell.replace("\xa0", " ")).strip()


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

class _TableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[tuple[bool, list[str]]]] = []
        self._depth = 0
        self._row: list[str] | None = None
        self._row_is_header = False
        self._cell: list[str] | None = None
        self._colspan = 1
        self.title_parts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
            self.tables.append([])
        elif tag == "tr" and self._depth:
            self._row = []
            self._row_is_header = False
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
            if tag == "th":
                self._row_is_header = True
            try:
                self._colspan = max(1, int(dict(attrs).get("colspan") or 1))
            except ValueError:
                self._colspan = 1
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            text = _clean("".join(self._cell))
            self._row.extend([text] + [""] * (self._colspan - 1))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row and self.tables:
                self.tables[-1].append((self._row_is_header, self._row))
            self._row = None
        elif tag == "table" and self._depth:
            self._depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
        elif self._in_title:
            self.title_parts.append(data)


def parse_html(text: str) -> Table:
    p = _TableHTMLParser()
    p.feed(text)
    p.close()
    candidates = [t for t in p.tables if len(t) >= 1]
    if not candidates:
        raise ParseError("Keine HTML-Tabelle gefunden")
    # größte Tabelle verwenden
    table = max(candidates, key=len)
    header_idx = next((i for i, (is_h, _) in enumerate(table) if is_h), 0)
    headers = table[header_idx][1]
    rows = [r for _, r in table[header_idx + 1:] if any(c for c in r)]
    title = _clean("".join(p.title_parts)) or None
    return Table(headers=headers, rows=rows, source_format="html", title=title)


# --------------------------------------------------------------------------
# Pipe-Text (FM "Textdatei") & RTF
# --------------------------------------------------------------------------

_SEP_LINE = re.compile(r"^\|?[\s\-=|+]+\|?$")


def parse_pipe_text(text: str) -> Table:
    lines = [ln.rstrip() for ln in text.splitlines()]
    table_lines = [ln for ln in lines if ln.strip().startswith("|")]
    if not table_lines:
        raise ParseError("Keine Pipe-Tabelle gefunden")
    rows: list[list[str]] = []
    for ln in table_lines:
        s = ln.strip()
        if _SEP_LINE.match(s):
            continue
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|"):
            s = s[:-1]
        rows.append([_clean(c) for c in s.split("|")])
    if not rows:
        raise ParseError("Pipe-Tabelle ist leer")
    headers, data = rows[0], rows[1:]
    data = [r for r in data if any(r)]
    return Table(headers=headers, rows=data, source_format="text")


def strip_rtf(text: str) -> str:
    """Sehr einfacher RTF→Text-Konverter (ausreichend für FM-Exporte)."""
    text = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("cp1252"), text)
    text = re.sub(r"\\u(-?\d+)\??", lambda m: chr(int(m.group(1)) % 65536), text)
    text = re.sub(r"\\(par|line)\b ?", "\n", text)
    text = re.sub(r"\\tab\b ?", "\t", text)
    # Kopfgruppen ({\fonttbl ...}, {\colortbl ...} usw.) entfernen
    text = re.sub(r"\{\\\*?\\(fonttbl|colortbl|stylesheet|info|generator)[^{}]*(\{[^{}]*\}[^{}]*)*\}", "", text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", text)
    text = text.replace("{", "").replace("}", "")
    return text


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------

def parse_csv(text: str) -> Table:
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = [[_clean(c) for c in r] for r in reader if any(c.strip() for c in r)]
    if not rows:
        raise ParseError("CSV ist leer")
    return Table(headers=rows[0], rows=rows[1:], source_format="csv")


# --------------------------------------------------------------------------
# Einstieg
# --------------------------------------------------------------------------

def parse_text(text: str, suffix: str = "") -> Table:
    suffix = suffix.lower()
    stripped = text.lstrip()
    if suffix in (".html", ".htm") or stripped[:200].lower().startswith(("<!doctype html", "<html")) or "<table" in text[:5000].lower():
        return parse_html(text)
    if suffix == ".rtf" or stripped.startswith("{\\rtf"):
        return parse_pipe_text(strip_rtf(text))
    if suffix == ".csv":
        return parse_csv(text)
    if any(ln.lstrip().startswith("|") for ln in text.splitlines()[:50]):
        return parse_pipe_text(text)
    return parse_csv(text)


def parse_file(path: str | Path) -> Table:
    path = Path(path)
    table = parse_text(read_text(path), path.suffix)
    table.meta["file"] = path.name
    if not table.headers:
        raise ParseError(f"{path.name}: keine Spaltenüberschriften gefunden")
    return table
