"""Lokale Weboberfläche + JSON-API (nur Standardbibliothek)."""

from __future__ import annotations

import json
import re
import tempfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .classify import KINDS
from .db import Database
from .export import export
from .importer import import_file
from .parsers import SUPPORTED_EXTENSIONS


def make_handler(db: Database):
    class Handler(BaseHTTPRequestHandler):
        server_version = "fm27data"

        def log_message(self, fmt, *args):  # ruhiger Log
            pass

        # -------------------------------------------------------- helpers
        def _send(self, body: bytes, ctype: str, status: int = 200, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, status: int = 200):
            self._send(json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", status)

        def _error(self, msg: str, status: int = 400):
            self._json({"error": msg}, status)

        # ------------------------------------------------------------ GET
        def do_GET(self):
            url = urlparse(self.path)
            q = {k: v[-1] for k, v in parse_qs(url.query).items()}
            path = url.path
            if path in ("/", "/index.html"):
                html = resources.files("fm27data").joinpath("static/index.html").read_bytes()
                return self._send(html, "text/html; charset=utf-8")
            if path == "/api/kinds":
                counts = db.kinds()
                return self._json([{"kind": k, "label": KINDS.get(k, k), "count": n} for k, n in counts.items()])
            if path == "/api/imports":
                return self._json(db.imports())
            if path == "/api/columns":
                return self._json(db.columns(q.get("kind", "players")))
            if path == "/api/records":
                filters = {}
                for k, v in q.items():
                    m = re.fullmatch(r"(min|max|eq|like)\.([a-z0-9_]+)", k)
                    if m and v != "":
                        op = {"min": ">=", "max": "<=", "eq": "=", "like": "LIKE"}[m.group(1)]
                        try:
                            val = v if op == "LIKE" else float(v)
                        except ValueError:
                            val = v
                        filters[m.group(2)] = (op, val)
                try:
                    limit = min(int(q.get("limit", 100)), 5000)
                    offset = int(q.get("offset", 0))
                except ValueError:
                    return self._error("limit/offset ungültig")
                total, rows = db.latest(q.get("kind", "players"), search=q.get("q", ""), filters=filters,
                                        sort=q.get("sort") or None, desc=q.get("desc", "1") == "1",
                                        limit=limit, offset=offset)
                return self._json({"total": total, "rows": rows})
            if path == "/api/history":
                return self._json(db.history(q.get("kind", "players"), q.get("key", "")))
            if path == "/api/export":
                kind = q.get("kind", "players")
                fmt = q.get("format", "csv")
                if fmt not in ("csv", "csv-de", "json"):
                    return self._error("format muss csv, csv-de oder json sein")
                with tempfile.TemporaryDirectory() as tmp:
                    out = Path(tmp) / f"{kind}.{'json' if fmt == 'json' else 'csv'}"
                    export(db, kind, out, fmt)
                    body = out.read_bytes()
                ctype = "application/json" if fmt == "json" else "text/csv; charset=utf-8"
                return self._send(body, ctype, extra={"Content-Disposition": f'attachment; filename="{out.name}"'})
            self._error("Nicht gefunden", HTTPStatus.NOT_FOUND)

        # ----------------------------------------------------------- POST
        def do_POST(self):
            url = urlparse(self.path)
            if url.path != "/api/upload":
                return self._error("Nicht gefunden", HTTPStatus.NOT_FOUND)
            q = {k: v[-1] for k, v in parse_qs(url.query).items()}
            name = Path(q.get("filename", "upload.html")).name
            if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
                return self._error(f"Dateityp nicht unterstützt: {name}")
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 200 * 1024 * 1024:
                return self._error("Leere oder zu große Datei")
            data = self.rfile.read(length)
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / name
                p.write_bytes(data)
                res = import_file(db, p, kind=q.get("kind") or None, game_date=q.get("game_date") or None)
            self._json({"status": res.status, "kind": res.kind, "rows": res.rows,
                        "import_id": res.import_id, "message": res.message, "text": str(res)},
                       200 if res.status != "error" else 422)

        # --------------------------------------------------------- DELETE
        def do_DELETE(self):
            m = re.fullmatch(r"/api/imports/(\d+)", urlparse(self.path).path)
            if not m:
                return self._error("Nicht gefunden", HTTPStatus.NOT_FOUND)
            db.delete_import(int(m.group(1)))
            self._json({"ok": True})

    return Handler


def serve(db: Database, host: str = "127.0.0.1", port: int = 8027) -> None:
    httpd = ThreadingHTTPServer((host, port), make_handler(db))
    print(f"Weboberfläche: http://{host}:{port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
