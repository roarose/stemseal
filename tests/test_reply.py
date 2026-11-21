# -*- coding: utf-8 -*-
"""How the hub reads the runner's answer (hub.read_reply): only a complete answer in the runner's exact form counts, and
every path (call, verify, register, update) reads it the same way. Run: python -m unittest discover -s tests"""
import json, os, sys, tempfile, unittest
from unittest import mock
os.environ.setdefault("STEMSEAL_HOME", tempfile.mkdtemp(prefix="stemseal_test_"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from stemseal import hub, seal, update

CELL = "def cell_executor(input_data):\n    return {'v': 1}\n"
def j(o): return json.dumps(o).encode()
GOOD_CHECK = (0, j({"results": [], "blocked": None, "problems": []}))
GOOD_RUN = (0, j({"results": [{"ok": True, "out": {"v": 1}}], "blocked": None, "problems": []}))

# answers that must never count as passed (check mode, then run mode with one input)
NOT_COMPLETE_CHECK = {
    "timeout": ("timeout", b""),
    "exit 1": (1, GOOD_CHECK[1]),
    "killed": (-9, b""),
    "no output": (0, b""),
    "broken output": (0, b'{"results": [], "blo'),
    "not an object": (0, b"[]"),
    "missing key": (0, j({"results": [], "blocked": None})),
    "extra key": (0, j({"results": [], "blocked": None, "problems": [], "x": 1})),
    "problems not a list": (0, j({"results": [], "blocked": None, "problems": "none"})),
    "problem not text": (0, j({"results": [], "blocked": None, "problems": [1]})),
    "results in check": (0, j({"results": [{"ok": True, "out": {}}], "blocked": None, "problems": []})),
    "exit 0 but blocked": (0, j({"results": [], "blocked": "policy", "problems": []})),
    "exit 3 not blocked": (3, GOOD_CHECK[1]),
    "blocked empty": (3, j({"results": [], "blocked": "", "problems": []})),
}
NOT_COMPLETE_RUN = {
    "timeout": ("timeout", b""),
    "exit 1": (1, GOOD_RUN[1]),
    "no output": (0, b""),
    "broken output": (0, b"{"),
    "wrong count": (0, j({"results": [], "blocked": None, "problems": []})),
    "ok without out": (0, j({"results": [{"ok": True}], "blocked": None, "problems": []})),
    "out not an object": (0, j({"results": [{"ok": True, "out": 1}], "blocked": None, "problems": []})),
    "ok not bool": (0, j({"results": [{"ok": 1, "out": {}}], "blocked": None, "problems": []})),
    "err not text": (0, j({"results": [{"ok": False, "err": None}], "blocked": None, "problems": []})),
    "extra result key": (0, j({"results": [{"ok": True, "out": {}, "x": 1}], "blocked": None, "problems": []})),
    "problems with results": (0, j({"results": [{"ok": True, "out": {}}], "blocked": None, "problems": ["p"]})),
}

class ReadReply(unittest.TestCase):
    def test_complete_answers(self):
        self.assertEqual(hub.read_reply(GOOD_CHECK, "check")["problems"], [])
        self.assertTrue(hub.read_reply(GOOD_RUN, "run", 1)["complete"])
        r = hub.read_reply((3, j({"results": [{"ok": False, "err": "x"}], "blocked": "policy", "problems": ["p"]})), "run", 1)
        self.assertEqual((r["complete"], r["blocked"]), (True, "policy"))

    def test_each_incomplete_form(self):
        for mode, cases, n in (("check", NOT_COMPLETE_CHECK, 0), ("run", NOT_COMPLETE_RUN, 1)):
            for k, proc in cases.items():
                with self.subTest(mode=mode, case=k):
                    self.assertFalse(hub.read_reply(proc, mode, n)["complete"])

class EveryPath(unittest.TestCase):
    def test_policy_check(self):
        for k, proc in NOT_COMPLETE_CHECK.items():
            with self.subTest(case=k), mock.patch.object(hub, "_run_runner", return_value=proc):
                self.assertTrue(hub.purity_check(CELL))
        with mock.patch.object(hub, "_run_runner", return_value=(3, j({"results": [{"ok": False, "err": "x"}], "blocked": "hash", "problems": []}))):
            self.assertTrue(hub.purity_check(CELL))

    def test_call(self):
        for k, proc in NOT_COMPLETE_RUN.items():
            with self.subTest(case=k), mock.patch.object(hub, "_run_runner", return_value=proc):
                r = hub.call("vat_supply_price", {"total": 11000}, caller="t", log=False)
                self.assertNotEqual(r["status"], "ok"); self.assertIsNone(r["result"])

    def test_verify(self):
        with mock.patch.object(hub, "_run_runner", return_value=("timeout", b"")):
            r = hub.verify_all()
        self.assertTrue(r)
        for name, v in r.items():
            with self.subTest(cell=name): self.assertFalse(v["policy_ok"]); self.assertFalse(v["gt_ok"])

    def test_register(self):
        d = tempfile.mkdtemp()
        with mock.patch.object(hub, "_run_runner", return_value=(0, b"")):
            r = hub.register("reply_test_cell", CELL, {"description": "x", "input_schema": {}, "output_keys": ["v"]},
                             [{"input": {}, "expected": {"v": 1}}] * hub.MIN_GT, base=d)
        self.assertFalse(r["locked"]); self.assertEqual(r["reason"], "purity gate")

    def test_update(self):
        c = hub.load("vat_supply_price")
        files = {}
        for f in ("cell.py", "contract.json", "gt_cases.json"):
            with open(os.path.join(c["dir"], f), "rb") as fh: files[f] = fh.read()
        files["lock.json"] = seal.dumps(seal.build("reply_test_update", "1.0", files, 2, 25, 25, "x", "t"))
        meta = {"files": {f: hub.sha(b) for f, b in files.items()}}
        def get(url, limit, timeout=20):
            for f, b in files.items():
                if url.endswith("/" + f): return b
            raise OSError("not found")
        user = tempfile.mkdtemp()
        with mock.patch.object(update, "_get", get), mock.patch.object(hub, "_run_runner", return_value=("timeout", b"")), \
             mock.patch.object(hub, "USER_CELLS", user):
            why = update._install(1, "reply_test_update", "1.0", meta, "x/%d/%s")
        self.assertTrue(why.startswith("policy gate")); self.assertEqual(os.listdir(user), [])

class RefusalCases(unittest.TestCase):
    def test_only_the_cells_own_refusal_counts(self):
        case = {"input": {}, "expected_error": "ask"}
        self.assertTrue(hub._refused_as_expected(case, {"ok": False, "err": "ValueError: ask the customer"}))
        for r in ({"ok": False, "err": "ask", "blocked": "policy"}, {"ok": False, "err": "ask", "fault": True},
                  {"ok": True, "out": {}}, {"ok": False, "err": "other"}):
            with self.subTest(r=r): self.assertFalse(hub._refused_as_expected(case, r))
        for want in ("", None, 1):
            with self.subTest(want=want): self.assertFalse(hub._refused_as_expected({"expected_error": want}, {"ok": False, "err": "x"}))

if __name__ == "__main__":
    unittest.main()
