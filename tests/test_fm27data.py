import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from fm27data.db import Database
from fm27data.export import export
from fm27data.importer import guess_game_date, import_file, import_path
from fm27data.normalize import (normalize_row, parse_attr, parse_height, parse_int, parse_money, parse_wage,
                                parse_weight)
from fm27data.parsers import parse_file
from fm27data.watcher import FolderWatcher
from fm27data.web import make_handler

FIX = Path(__file__).parent / "fixtures"


class NormalizeTests(unittest.TestCase):
    def test_money(self):
        self.assertEqual(parse_money("€1.5M")["value"], 1_500_000)
        self.assertEqual(parse_money("£850K")["currency"], "GBP")
        m = parse_money("€10M - €15M")
        self.assertEqual((m["min"], m["max"], m["value"]), (10e6, 15e6, 12.5e6))
        self.assertEqual(parse_money("12,5 Mio. €")["value"], 12.5e6)
        self.assertEqual(parse_money("850 Tsd. €")["value"], 850_000)
        self.assertNotIn("value", parse_money("Not for Sale"))
        self.assertIsNone(parse_money("-"))

    def test_wage(self):
        self.assertEqual(parse_wage("€45K p/w")["per_week"], 45_000)
        self.assertEqual(parse_wage("35.000 € p.W.")["per_week"], 35_000)
        self.assertAlmostEqual(parse_wage("€1.2M p/a")["per_week"], 23076.92, places=2)
        self.assertEqual(parse_wage("£40,000 p/m")["period"], "month")

    def test_units(self):
        self.assertEqual(parse_height("1.83 m"), 183)
        self.assertEqual(parse_height("192 cm"), 192)
        self.assertEqual(parse_height("6'2\""), 188)
        self.assertEqual(parse_weight("185 lbs"), 84)
        self.assertEqual(parse_int("81.365"), 81365)

    def test_attr(self):
        self.assertEqual(parse_attr("15"), 15)
        self.assertEqual(parse_attr("10-13"), 11.5)
        self.assertIsNone(parse_attr("42"))

    def test_ambiguous_nat(self):
        row = normalize_row([("Nat", "GER"), ("Nat", "14"), ("Pos", "12"), ("Position", "ST (C)")])
        self.assertEqual(row["nationality"], "GER")
        self.assertEqual(row["natural_fitness"], 14)
        self.assertEqual(row["positioning"], 12)
        self.assertEqual(row["position"], "ST (C)")

    def test_unknown_columns_kept(self):
        row = normalize_row([("Name", "X"), ("Brandneue Spalte", "17"), ("Notiz", "toll")])
        self.assertEqual(row["brandneue_spalte"], 17)
        self.assertEqual(row["notiz"], "toll")

    def test_game_date(self):
        self.assertEqual(guess_game_date("squad_2027-08-15.html"), "2027-08-15")
        self.assertEqual(guess_game_date("kader 15.8.2027.txt"), "2027-08-15")
        self.assertIsNone(guess_game_date("kader.txt"))


class ParserTests(unittest.TestCase):
    def test_html(self):
        t = parse_file(FIX / "squad_2027-08-15.html")
        self.assertEqual(t.source_format, "html")
        self.assertEqual(len(t.rows), 3)
        self.assertEqual(t.headers[2], "Name")
        self.assertEqual(t.title, "Squad - FC Example")

    def test_pipe_text(self):
        t = parse_file(FIX / "kader_de.txt")
        self.assertEqual(t.source_format, "text")
        self.assertEqual(len(t.rows), 2)
        self.assertEqual(t.rows[0][0], "Max Mustermann")

    def test_cp1252(self):
        t = parse_file(FIX / "kader_de_cp1252.txt")
        self.assertEqual(t.rows[1][4], "Österreich")

    def test_rtf(self):
        t = parse_file(FIX / "squad.rtf")
        self.assertEqual(t.rows[0][0], "Jörg Müller")
        self.assertEqual(t.rows[0][3], "€2.1M")

    def test_csv(self):
        t = parse_file(FIX / "staff.csv")
        self.assertEqual(t.headers[0], "Name")
        self.assertEqual(len(t.rows), 2)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "t.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_import_and_classify(self):
        results = {r.file: r for r in import_path(self.db, FIX)}
        self.assertTrue(all(r.status == "imported" for r in results.values()), [str(r) for r in results.values()])
        self.assertEqual(results["squad_2027-08-15.html"].kind, "players")
        self.assertEqual(results["kader_de.txt"].kind, "players")
        self.assertEqual(results["staff.csv"].kind, "staff")
        self.assertEqual(results["table.html"].kind, "league_table")

    def test_dedup(self):
        self.assertEqual(import_file(self.db, FIX / "staff.csv").status, "imported")
        r = import_file(self.db, FIX / "staff.csv")
        self.assertEqual((r.status, r.message), ("skipped", "bereits importiert"))

    def test_latest_merges_snapshots_and_history(self):
        import_file(self.db, FIX / "squad_2027-08-15.html")
        import_file(self.db, FIX / "squad_2028-01-10.html")
        total, rows = self.db.latest("players", search="Jonas")
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["data"]["value"]["value"], 38e6)
        hist = self.db.history("players", "uid:2000123456")
        self.assertEqual([h["game_date"] for h in hist], ["2027-08-15", "2028-01-10"])
        self.assertEqual(hist[0]["data"]["value"]["min"], 25e6)

    def test_merges_fields_from_different_views(self):
        import_file(self.db, FIX / "squad_2027-08-15.html")   # mit Größe/Attributen
        import_file(self.db, FIX / "squad_2028-01-10.html")   # nur wenige Spalten
        _, rows = self.db.latest("players", search="Jonas")
        d = rows[0]["data"]
        self.assertEqual(d["height"], 183)          # aus dem älteren Export erhalten
        self.assertEqual(d["finishing"], 16)        # vom neueren Export aktualisiert
        self.assertEqual(d["dribbling"], 16)

    def test_delete_import_rebuilds_state(self):
        import_file(self.db, FIX / "squad_2027-08-15.html")
        second = import_file(self.db, FIX / "squad_2028-01-10.html")
        self.db.delete_import(second.import_id)
        _, rows = self.db.latest("players", search="Jonas")
        self.assertEqual(rows[0]["data"]["finishing"], 15)
        self.db.delete_import(1)
        self.assertEqual(self.db.kinds(), {})

    def test_text_values_sort_last(self):
        import_file(self.db, FIX / "squad_2027-08-15.html")
        _, rows = self.db.latest("players", sort="value", desc=True)
        self.assertEqual([r["data"]["name"] for r in rows], ["Jonas Beispiel", "Luca Muster", "Erik Torwart"])

    def test_sort_and_filter(self):
        import_file(self.db, FIX / "squad_2027-08-15.html")
        import_file(self.db, FIX / "kader_de.txt")
        _, rows = self.db.latest("players", sort="wage", desc=True)
        self.assertEqual(rows[0]["data"]["name"], "Jonas Beispiel")
        total, rows = self.db.latest("players", filters={"age": ("<=", 22)})
        self.assertEqual({r["data"]["name"] for r in rows}, {"Jonas Beispiel", "Luca Muster"})
        _, rows = self.db.latest("players", filters={"pa": (">=", 150)})
        self.assertEqual([r["data"]["name"] for r in rows], ["Max Mustermann"])

    def test_export(self):
        import_file(self.db, FIX / "squad_2027-08-15.html")
        out = Path(self.tmp.name) / "p.csv"
        self.assertEqual(export(self.db, "players", out), 3)
        text = out.read_text(encoding="utf-8-sig")
        self.assertIn("value_min", text.splitlines()[0])
        out_json = Path(self.tmp.name) / "p.json"
        export(self.db, "players", out_json)
        self.assertEqual(len(json.loads(out_json.read_text(encoding="utf-8"))), 3)

    def test_watcher_waits_for_stable_file(self):
        folder = Path(self.tmp.name) / "watch"
        folder.mkdir()
        w = FolderWatcher(self.db, folder, on_result=lambda r: None)
        (folder / "staff.csv").write_bytes((FIX / "staff.csv").read_bytes())
        self.assertEqual(w.poll_once(), [])          # erster Blick: noch nicht stabil
        res = w.poll_once()                           # zweiter Blick: importieren
        self.assertEqual([r.status for r in res], ["imported"])
        self.assertEqual(w.poll_once(), [])           # nicht doppelt


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = Database(Path(cls.tmp.name) / "w.sqlite3")
        import_file(cls.db, FIX / "squad_2027-08-15.html")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.db))
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.db.close()
        cls.tmp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return r.read()

    def test_index(self):
        self.assertIn(b"FM27 Datenzentrale", self.get("/"))

    def test_records_api(self):
        data = json.loads(self.get("/api/records?kind=players&sort=age&desc=0&max.age=25"))
        self.assertEqual([r["data"]["name"] for r in data["rows"]], ["Luca Muster", "Jonas Beispiel"])

    def test_upload(self):
        body = (FIX / "table.html").read_bytes()
        req = urllib.request.Request(self.base + "/api/upload?filename=table.html", data=body, method="POST")
        with urllib.request.urlopen(req) as r:
            res = json.loads(r.read())
        self.assertEqual((res["status"], res["kind"]), ("imported", "league_table"))
        kinds = {k["kind"] for k in json.loads(self.get("/api/kinds"))}
        self.assertEqual(kinds, {"players", "league_table"})

    def test_export_api(self):
        self.assertTrue(self.get("/api/export?kind=players&format=csv").decode("utf-8-sig").startswith("uid,"))


if __name__ == "__main__":
    unittest.main()
