# -*- coding: utf-8 -*-
"""The ledger modes (STEMSEAL_LOG), its tidying, the error text a model and the ledger get, and which files input_file reads.
Run: python -m unittest discover -s tests"""
import json, os, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
os.environ.setdefault("STEMSEAL_HOME", tempfile.mkdtemp(prefix="stemseal_test_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stemseal import hub, guides, mcp

NEED = "대출 원리금 균등상환 월 납입액 계산 홍길동 010-1234-5678"
def raw():
    if not os.path.exists(hub.LEDGER): return ""
    with open(hub.LEDGER, encoding="utf-8") as f: return f.read()

class Modes(unittest.TestCase):
    def setUp(self):
        for p in (hub.LEDGER, os.path.join(os.path.dirname(hub.LEDGER), "ledger.1.jsonl")):
            if os.path.exists(p): os.remove(p)
    def tearDown(self): os.environ.pop("STEMSEAL_LOG", None)

    def test_full_is_the_default(self):
        self.assertEqual(hub.log_mode(), "full")
        hub.request_cell(NEED, caller="t", example="1,000,000 -> 85,607")
        self.assertIn("홍길동", raw()); self.assertIn("85,607", raw())

    def test_unknown_value_means_full(self):
        os.environ["STEMSEAL_LOG"] = "verbose"; self.assertEqual(hub.log_mode(), "full")

    def test_minimal_keeps_hash_and_words_only(self):
        os.environ["STEMSEAL_LOG"] = "minimal"
        guides.find(NEED, caller="t")
        hub.request_cell(NEED, caller="t", example="1,000,000 -> 85,607")
        text = raw()
        for s in ("010-1234-5678", "85,607", "균등상환 월"):
            self.assertNotIn(s, text)
        rows = [json.loads(l) for l in text.splitlines()]
        withneed = [r for r in rows if "need_sha" in r]
        self.assertTrue(withneed)
        for r in rows:
            self.assertNotIn("need", r); self.assertNotIn("example", r)
        for r in withneed:
            self.assertEqual(len(r["need_sha"]), 16); self.assertLessEqual(len(r["need_words"]), 8)

    def test_minimal_still_counts_alike_requests_together(self):
        os.environ["STEMSEAL_LOG"] = "minimal"
        hub.request_cell("월 납입액 계산 대출 원리금", caller="t")
        hub.request_cell("대출 원리금 월 납입액", caller="u")
        groups = hub.demand_summary()
        self.assertEqual(len(groups), 1); self.assertEqual(groups[0]["count"], 2)

    def test_off_writes_nothing(self):
        os.environ["STEMSEAL_LOG"] = "off"
        guides.find(NEED, caller="t"); hub.request_cell(NEED, caller="t")
        hub.call("vat_supply_price", {"total": 11000}, caller="t")
        self.assertFalse(os.path.exists(hub.LEDGER))

    def test_stats_reads_damaged_and_minimal_rows(self):
        os.environ["STEMSEAL_LOG"] = "minimal"
        hub.request_cell(NEED, caller="t")
        with open(hub.LEDGER, "a", encoding="utf-8") as f: f.write('{"type": "call", "cell"\n{}\n')
        s = hub.stats()
        self.assertEqual(s["calls"], 0); self.assertEqual(len(s["unmet_demand"]), 1)

class Tidy(unittest.TestCase):
    OLD = os.path.join(os.path.dirname(hub.LEDGER), "ledger.1.jsonl")
    def setUp(self):
        os.makedirs(os.path.dirname(hub.LEDGER), exist_ok=True)
        for p in (hub.LEDGER, self.OLD):
            if os.path.exists(p): os.remove(p)
    def write(self, rows):
        with open(hub.LEDGER, "w", encoding="utf-8") as f:
            for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    def read(self, p):
        with open(p, encoding="utf-8") as f: return [json.loads(l) for l in f if l.strip()]
    def ts(self, days): return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")

    def test_nothing_old_leaves_the_file_alone(self):
        self.write([{"ts": self.ts(1), "type": "find", "need": "a"}])
        before = os.stat(hub.LEDGER).st_mtime_ns
        self.assertEqual(hub.tidy_ledger(), 0)
        self.assertEqual(os.stat(hub.LEDGER).st_mtime_ns, before); self.assertFalse(os.path.exists(self.OLD))

    def test_rows_past_90_days_move_and_records_stay(self):
        self.write([{"ts": self.ts(200), "type": "find", "need": "old"},
                    {"ts": self.ts(200), "type": "update", "cell": "x"},
                    {"ts": self.ts(100), "type": "demand", "need": "older"},
                    {"ts": self.ts(10), "type": "find", "need": "new"}])
        with open(self.OLD, "w", encoding="utf-8") as f: f.write('{"type": "previous"}\n')
        self.assertEqual(hub.tidy_ledger(), 2)
        self.assertEqual([r.get("need") or r["type"] for r in self.read(hub.LEDGER)], ["update", "new"])
        self.assertEqual([r["need"] for r in self.read(self.OLD)], ["old", "older"])

    def test_large_file_moves_oldest_rows(self):
        big = "x" * 1000
        self.write([{"ts": self.ts(5), "type": "find", "need": big, "n": i} for i in range(300)])
        with mock.patch.object(hub, "MAX_LEDGER", 100 * 1024):
            moved = hub.tidy_ledger()
        self.assertGreater(moved, 0)
        self.assertLessEqual(os.path.getsize(hub.LEDGER), 50 * 1024)
        kept = self.read(hub.LEDGER); gone = self.read(self.OLD)
        self.assertEqual(kept[-1]["n"], 299); self.assertEqual(gone[0]["n"], 0)
        self.assertEqual(len(kept) + len(gone), 300)

    def test_never_raises(self):
        with open(hub.LEDGER, "w", encoding="utf-8") as f: f.write("not json\n\n{}\n")
        self.assertEqual(hub.tidy_ledger(), 0)

class ErrorText(unittest.TestCase):
    def tearDown(self): os.environ.pop("STEMSEAL_LOG", None)
    def test_cell_error_is_one_short_line(self):
        if os.path.exists(hub.LEDGER): os.remove(hub.LEDGER)
        err = "ValueError: " + "가나다\n라마 " * 100
        with mock.patch.object(hub, "run_isolated", lambda *a, **k: [{"ok": False, "err": err}]):
            r = hub.call("vat_supply_price", {"total": 11000}, caller="t")
        self.assertEqual(r["status"], "invalid_input")
        detail = r["reason"].split("cell rejected the input: ", 1)[1]
        self.assertNotIn("\n", r["reason"]); self.assertLessEqual(len(detail), hub.ERR_TO_MODEL)
        row = [x for x in hub._rows("call")][-1]
        logged = row["reason"].split("cell rejected the input: ", 1)[1]
        self.assertTrue(logged.startswith("ValueError: ")); self.assertLessEqual(len(logged), len("ValueError: ") + hub.ERR_TO_LEDGER)

class InputFile(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="stemseal_inputs_"))
        self.out = os.path.realpath(tempfile.mkdtemp(prefix="stemseal_elsewhere_"))
        self.p = mock.patch.object(mcp, "INPUT_ROOTS", [self.root]); self.p.start()
    def tearDown(self): self.p.stop()
    def put(self, d, name, text):
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8") as f: f.write(text)
        return path
    def call(self, path): return mcp._handle("call_cell", {"cell": "vat_supply_price", "input_file": path})

    def test_json_under_the_folder_is_read(self):
        r = self.call(self.put(self.root, "in.json", json.dumps({"total": 11000})))
        self.assertEqual(r["status"], "ok"); self.assertEqual(r["result"]["vat"], 1000)

    def test_other_files_get_one_fixed_reply(self):
        os.makedirs(os.path.join(self.root, "sub"))
        cases = {"outside": self.put(self.out, "in.json", '{"total": 11000}'),
                 "dotdot": os.path.join(self.root, "sub", "..", "..", os.path.basename(self.out), "in.json"),
                 "not json name": self.put(self.root, "in.txt", '{"total": 11000}'),
                 "missing": os.path.join(self.root, "nope.json"),
                 "folder": os.path.join(self.root, "sub"),
                 "too large": self.put(self.root, "big.json", '{"total": 11000, "pad": "%s"}' % ("x" * (mcp.MAX_INPUT_FILE + 1))),
                 "bad json": self.put(self.root, "bad.json", "{")}
        if hasattr(os, "symlink"):
            try:
                link = os.path.join(self.root, "link.json"); os.symlink(cases["outside"], link); cases["link out"] = link
            except OSError: pass
        want = "input_file must be a .json file under %s" % self.root
        for k, path in cases.items():
            with self.subTest(case=k):
                r = self.call(path)
                self.assertEqual(r, {"status": "invalid_input", "reason": want})

if __name__ == "__main__":
    unittest.main()
