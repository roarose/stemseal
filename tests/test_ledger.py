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
        for s in ("010-1234-5678", "85,607", "균등상환 월", "홍길동"):
            self.assertNotIn(s, text)
        rows = [json.loads(l) for l in text.splitlines()]
        withneed = [r for r in rows if "need_sha" in r]
        self.assertTrue(withneed)
        for r in rows:
            self.assertNotIn("need", r); self.assertNotIn("example", r)
        for r in withneed:
            self.assertEqual(len(r["need_sha"]), 16); self.assertLessEqual(len(r["need_words"]), hub.MIN_WORDS)

    def test_minimal_keeps_no_short_sentence(self):
        """A short sentence with a name and a phone number: neither is kept, and what is kept is not the sentence."""
        os.environ["STEMSEAL_LOG"] = "minimal"
        said = "김민수예요 010-9876-5432 으로 연락 주시고 떡볶이 두 개 주세요"
        guides.find(said, caller="t", words=["김민수", "떡볶이 가격"]); hub.request_cell(said, caller="t")
        mcp._handle("call_cell", {"cell": "order_total", "input": {"question": said, "items": [{"price": "김민수 4천원"}]}})
        text = raw()
        for s in ("김민수", "9876", "5432", "연락"): self.assertNotIn(s, text)
        rows = [json.loads(l) for l in text.splitlines()]
        words = [w for r in rows for w in r.get("need_words", []) + r.get("words", [])]
        said_words = said.split()
        self.assertLess(len(set(words)), len(said_words) / 2)
        for r in rows:
            if r.get("type") == "call": self.assertEqual(r["reason"], "cell rejected the input: ValueError")

    def test_switching_to_minimal_leaves_old_rows_until_the_user_minimizes(self):
        hub.request_cell(NEED, caller="t", example="1,000,000 -> 85,607")
        os.environ["STEMSEAL_LOG"] = "minimal"
        self.assertIn("홍길동", raw()); self.assertTrue(hub.ledger_has_text())
        self.assertGreater(hub.minimize_ledger(), 0)
        self.assertNotIn("홍길동", raw()); self.assertNotIn("85,607", raw()); self.assertFalse(hub.ledger_has_text())
        self.assertEqual(len(hub.demand_summary()), 1)

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
    def test_cell_error_is_one_line_cut_at_a_word(self):
        if os.path.exists(hub.LEDGER): os.remove(hub.LEDGER)
        err = "ValueError: " + "가나다\n라마 " * 100
        with mock.patch.object(hub, "run_isolated", lambda *a, **k: [{"ok": False, "err": err}]):
            r = hub.call("vat_supply_price", {"total": 11000}, caller="t")
        self.assertEqual(r["status"], "invalid_input")
        detail = r["reason"].split("cell rejected the input: ValueError: ", 1)[1]
        self.assertNotIn("\n", r["reason"]); self.assertLessEqual(len(detail), hub.ERR_TO_MODEL + 1)
        self.assertTrue(detail.endswith("…")); self.assertTrue(hub._one_line(err).startswith("ValueError: " + detail[:-1] + " "))
        row = [x for x in hub._rows("call")][-1]
        logged = row["reason"].split("cell rejected the input: ", 1)[1]
        self.assertTrue(logged.startswith("ValueError: ")); self.assertLessEqual(len(logged), len("ValueError: ") + hub.ERR_TO_LEDGER)

    def test_cell_error_within_the_limit_is_passed_as_sent(self):
        err = "ValueError: " + "give each item its qty in the customer's words,  or ask the customer if it is unclear " * 2
        err = err[:len("ValueError: ") + hub.ERR_TO_MODEL]
        with mock.patch.object(hub, "run_isolated", lambda *a, **k: [{"ok": False, "err": err}]):
            r = hub.call("vat_supply_price", {"total": 11000}, caller="t", log=False)
        self.assertEqual(r["reason"], "cell rejected the input: " + err)

class InputFile(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="stemseal_inputs_"))
        self.out = os.path.realpath(tempfile.mkdtemp(prefix="stemseal_elsewhere_"))
        self.p = [mock.patch.object(mcp, "INPUT_ROOTS", [self.root]), mock.patch.object(mcp, "INPUT_DIR", self.root)]
        for p in self.p: p.start()
    def tearDown(self):
        for p in self.p: p.stop()
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
        for k, path in cases.items():
            with self.subTest(case=k):
                r = self.call(path)
                self.assertEqual(r, {"status": "invalid_input", "reason": mcp.input_file_error(path)})
                self.assertNotIn(self.root, r["reason"]); self.assertNotIn(self.out, r["reason"])

    def test_relative_path_is_taken_from_the_inputs_folder(self):
        self.put(self.root, "rel.json", json.dumps({"total": 11000}))
        self.assertEqual(self.call("rel.json")["status"], "ok")

    def test_reply_names_the_file_and_not_where_it_is(self):
        home = os.path.realpath(os.path.expanduser("~"))
        with mock.patch.object(mcp, "INPUT_DIR", os.path.join(home, ".stemseal", "inputs")):
            msg = mcp.input_file_error(os.path.join(self.out, "secret.json"))
        self.assertIn("'secret.json'", msg); self.assertIn("~", msg); self.assertNotIn(home, msg)

    def test_start_folder_counts_only_when_it_is_narrow(self):
        home = os.path.realpath(os.path.expanduser("~"))
        top = os.path.abspath(os.sep)
        for broad in (top, home, os.path.dirname(home)):
            with self.subTest(folder=broad): self.assertEqual(mcp.input_roots(broad), [mcp.INPUT_DIR])
        self.assertEqual(mcp.input_roots(self.out), [mcp.INPUT_DIR, self.out])

    def test_reserved_device_names(self):
        for name in ("con.json", "NUL.json", "com1.json", "LPT9.json", "aux.json", "prn.json", "conin$.json"):
            with self.subTest(name=name):
                self.assertIsNone(mcp.read_input_file(os.path.join(self.root, name)))

@unittest.skipUnless(os.name == "nt", "Windows path forms")
class WindowsPaths(unittest.TestCase):
    """The forms a Windows path can take: drive letters, letter case, both slashes, UNC, short (8.3) names, device names."""
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="stemseal_inputs_long_name_"))
        self.out = os.path.realpath(tempfile.mkdtemp(prefix="stemseal_elsewhere_long_name_"))
        self.p = [mock.patch.object(mcp, "INPUT_ROOTS", [self.root]), mock.patch.object(mcp, "INPUT_DIR", self.root)]
        for p in self.p: p.start()
        self.inside = os.path.join(self.root, "in.json"); self.outside = os.path.join(self.out, "in.json")
        for path, total in ((self.inside, 11000), (self.outside, 22000)):
            with open(path, "w", encoding="utf-8") as f: f.write('{"total": %d}' % total)
    def tearDown(self):
        for p in self.p: p.stop()
    def short(self, path):
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetShortPathNameW(path, buf, 1024)
        return buf.value if n else path

    def test_inside_in_any_spelling_is_read(self):
        drive, rest = os.path.splitdrive(self.inside)
        for path in (drive.lower() + rest, self.inside.upper(), self.inside.replace("\\", "/"), self.short(self.inside)):
            with self.subTest(path=path): self.assertEqual(mcp.read_input_file(path), {"total": 11000})

    def test_outside_in_any_spelling_is_refused(self):
        drive, rest = os.path.splitdrive(self.outside)
        other = "Z:" if drive.upper() != "Z:" else "Y:"
        sub = os.path.join(self.root, "sub"); os.makedirs(sub)
        up = os.path.relpath(self.outside, sub)
        forms = [self.outside, drive.lower() + rest, self.outside.upper(), self.outside.replace("\\", "/"), self.short(self.outside),
                 sub + "\\" + up, sub.replace("\\", "/") + "/" + up.replace("\\", "/"),
                 "\\\\localhost\\" + drive[0] + "$" + rest, "\\\\?\\" + self.outside, "\\\\.\\" + self.outside,
                 other + rest, other + "in.json"]
        for path in forms:
            with self.subTest(path=path): self.assertIsNone(mcp.read_input_file(path))

    def test_drive_relative_name_stays_in_the_inputs_folder(self):
        drive = os.path.splitdrive(self.outside)[0]
        for path in (drive + "in.json", drive.lower() + "in.json"):
            with self.subTest(path=path): self.assertIn(mcp.read_input_file(path), (None, {"total": 11000}))

    def test_device_names_are_refused_without_waiting(self):
        for path in ("CON", "con.json", "NUL.json", "\\\\.\\CON", os.path.join(self.root, "COM1.json"), os.path.join(self.root, "aux .json"),
                     os.path.join(self.root, "in.json:stream"), os.path.join(self.root, "CONIN$.json")):
            with self.subTest(path=path): self.assertIsNone(mcp.read_input_file(path))

if __name__ == "__main__":
    unittest.main()
