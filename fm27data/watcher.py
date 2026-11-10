"""Überwacht den FM-Exportordner und importiert neue Dateien automatisch."""

from __future__ import annotations

import os
import platform
import threading
import time
from pathlib import Path
from typing import Callable

from .db import Database
from .importer import ImportResult, import_file
from .parsers import SUPPORTED_EXTENSIONS

FM_FOLDER_NAMES = ["Football Manager 27", "Football Manager 2027"]


def default_fm_dirs() -> list[Path]:
    """Mögliche Benutzerordner von FM27 auf diesem System."""
    home = Path.home()
    bases: list[Path] = []
    system = platform.system()
    if system == "Windows":
        docs = Path(os.environ.get("USERPROFILE", home)) / "Documents"
        bases += [docs / "Sports Interactive", home / "OneDrive" / "Documents" / "Sports Interactive",
                  home / "OneDrive" / "Dokumente" / "Sports Interactive"]
    elif system == "Darwin":
        bases += [home / "Library" / "Application Support" / "Sports Interactive", home / "Documents" / "Sports Interactive"]
    else:
        bases += [home / ".local" / "share" / "Sports Interactive", home / "Documents" / "Sports Interactive",
                  home / "Dokumente" / "Sports Interactive"]
    return [b / n for b in bases for n in FM_FOLDER_NAMES]


def find_fm_dir() -> Path | None:
    for d in default_fm_dirs():
        if d.is_dir():
            return d
    return None


class FolderWatcher:
    """Polling-basierter Watcher (keine Abhängigkeiten, funktioniert überall).

    Eine Datei wird erst importiert, wenn Größe und Änderungszeit über zwei
    Durchläufe stabil sind – so werden halb geschriebene Exporte ignoriert.
    """

    def __init__(self, db: Database, folder: str | Path, *, interval: float = 2.0, recursive: bool = False,
                 on_result: Callable[[ImportResult], None] | None = None):
        self.db = db
        self.folder = Path(folder)
        self.interval = interval
        self.recursive = recursive
        self.on_result = on_result or (lambda r: print(r, flush=True))
        self._pending: dict[Path, tuple[float, int]] = {}
        self._done: dict[Path, tuple[float, int]] = {}
        self._stop = threading.Event()

    def _scan(self) -> list[Path]:
        it = self.folder.rglob("*") if self.recursive else self.folder.glob("*")
        return [p for p in it if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS]

    def poll_once(self) -> list[ImportResult]:
        results = []
        if not self.folder.is_dir():
            return results
        for path in self._scan():
            try:
                st = path.stat()
            except OSError:
                continue
            sig = (st.st_mtime, st.st_size)
            if self._done.get(path) == sig:
                continue
            if self._pending.get(path) == sig:
                res = import_file(self.db, path)
                self._done[path] = sig
                self._pending.pop(path, None)
                if res.status != "skipped" or res.message != "bereits importiert":
                    self.on_result(res)
                results.append(res)
            else:
                self._pending[path] = sig
        return results

    def run(self) -> None:
        print(f"Überwache {self.folder} (alle {self.interval:g}s) – Strg+C zum Beenden", flush=True)
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self.interval)

    def start_background(self) -> threading.Thread:
        t = threading.Thread(target=self.run, name="fm27data-watcher", daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()


def wait_forever() -> None:
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
