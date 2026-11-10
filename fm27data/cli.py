"""Kommandozeile: fm27data <befehl> ..."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .classify import KINDS
from .db import Database
from .export import export, flatten
from .importer import import_path
from .watcher import FolderWatcher, default_fm_dirs, find_fm_dir, wait_forever


def _resolve_folder(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser()
    found = find_fm_dir()
    if found:
        return found
    print("FM27-Ordner nicht gefunden. Gesucht wurde in:", file=sys.stderr)
    for d in default_fm_dirs():
        print("  ", d, file=sys.stderr)
    print("Bitte den Ordner mit --folder angeben.", file=sys.stderr)
    raise SystemExit(2)


def cmd_import(args, db):
    ok = True
    for p in args.paths:
        for res in import_path(db, p, kind=args.kind, game_date=args.game_date, force=args.force):
            print(res)
            ok &= res.status != "error"
    return 0 if ok else 1


def cmd_watch(args, db):
    folder = _resolve_folder(args.folder)
    FolderWatcher(db, folder, interval=args.interval, recursive=args.recursive).run()
    return 0


def cmd_serve(args, db):
    from .web import serve
    serve(db, args.host, args.port)
    return 0


def cmd_run(args, db):
    """Watcher + Weboberfläche zusammen – der Komplettmodus."""
    from .web import serve
    folder = _resolve_folder(args.folder)
    FolderWatcher(db, folder, interval=args.interval, recursive=args.recursive).start_background()
    if args.open:
        import webbrowser
        webbrowser.open(f"http://{args.host}:{args.port}")
    serve(db, args.host, args.port)
    return 0


def cmd_list(args, db):
    if not args.kind:
        for k, n in db.kinds().items():
            print(f"{k:14} {KINDS.get(k, k):12} {n:>7} Einträge")
        return 0
    filters = {}
    for f in args.filter or []:
        for op in (">=", "<=", "="):
            if op in f:
                k, v = f.split(op, 1)
                try:
                    filters[k.strip()] = (op, float(v))
                except ValueError:
                    filters[k.strip()] = (op, v.strip())
                break
    total, rows = db.latest(args.kind, search=args.search or "", filters=filters, sort=args.sort,
                            desc=not args.asc, limit=args.limit)
    cols = args.columns.split(",") if args.columns else db.columns(args.kind)[:10]
    flat = [flatten(r["data"]) for r in rows]
    if args.json:
        print(json.dumps(flat, ensure_ascii=False, indent=2))
        return 0
    widths = {c: max([len(c)] + [len(_fmt(f.get(c))) for f in flat]) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    print("  ".join("-" * widths[c] for c in cols))
    for f in flat:
        print("  ".join(_fmt(f.get(c)).ljust(widths[c]) for c in cols))
    print(f"\n{len(rows)} von {total} Einträgen")
    return 0


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:g}"
    return str(v)


def cmd_export(args, db):
    n = export(db, args.kind, args.output, args.format)
    print(f"{n} Einträge nach {args.output} exportiert")
    return 0


def cmd_imports(args, db):
    for i in db.imports():
        print(f"#{i['id']:<4} {i['imported_at']}  {i['kind']:12} {i['row_count']:>6} Zeilen  "
              f"{i['game_date'] or '':10}  {i['file']}")
    return 0


def cmd_delete(args, db):
    db.delete_import(args.import_id)
    print(f"Import #{args.import_id} gelöscht")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fm27data", description="Daten aus Football Manager 27 automatisch auslesen.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--db", default="fm27data.sqlite3", help="SQLite-Datenbank (Standard: fm27data.sqlite3)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("import", help="Exportdatei(en) oder Ordner importieren")
    s.add_argument("paths", nargs="+")
    s.add_argument("--kind", choices=list(KINDS), help="Art erzwingen statt automatisch erkennen")
    s.add_argument("--game-date", help="Spieldatum (JJJJ-MM-TT) für den Verlauf")
    s.add_argument("--force", action="store_true", help="auch bereits importierte Dateien erneut importieren")
    s.set_defaults(func=cmd_import)

    def watch_opts(s):
        s.add_argument("--folder", help="zu überwachender Ordner (Standard: FM27-Benutzerordner)")
        s.add_argument("--interval", type=float, default=2.0, help="Prüfintervall in Sekunden")
        s.add_argument("--recursive", action="store_true", help="auch Unterordner überwachen")

    def web_opts(s):
        s.add_argument("--host", default="127.0.0.1")
        s.add_argument("--port", type=int, default=8027)

    s = sub.add_parser("watch", help="Ordner überwachen und neue Exporte automatisch importieren")
    watch_opts(s)
    s.set_defaults(func=cmd_watch)

    s = sub.add_parser("serve", help="Weboberfläche starten")
    web_opts(s)
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("run", help="Überwachung + Weboberfläche (empfohlen)")
    watch_opts(s)
    web_opts(s)
    s.add_argument("--open", action="store_true", help="Browser automatisch öffnen")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("list", help="Daten anzeigen")
    s.add_argument("kind", nargs="?", choices=list(KINDS))
    s.add_argument("-s", "--search")
    s.add_argument("-f", "--filter", action="append", help="z.B. -f 'age<=21' -f 'pa>=150'")
    s.add_argument("--sort")
    s.add_argument("--asc", action="store_true")
    s.add_argument("-n", "--limit", type=int, default=30)
    s.add_argument("-c", "--columns", help="kommagetrennte Spalten")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("export", help="Daten als CSV/JSON exportieren")
    s.add_argument("kind", choices=list(KINDS))
    s.add_argument("output")
    s.add_argument("--format", choices=["csv", "csv-de", "json"])
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("imports", help="Importverlauf anzeigen")
    s.set_defaults(func=cmd_imports)

    s = sub.add_parser("delete", help="Import löschen")
    s.add_argument("import_id", type=int)
    s.set_defaults(func=cmd_delete)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = Database(args.db)
    try:
        return args.func(args, db) or 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
