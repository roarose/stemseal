# -*- coding: utf-8 -*-
"""Token meter tests. Run: python -m unittest discover -s tests"""
import json, os, shutil, sys, tempfile, unittest

HOME = tempfile.mkdtemp(prefix="stemseal_test_")
os.environ["STEMSEAL_HOME"] = HOME
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stemseal import hub, guides, savings, mcp, cli  # noqa: E402

CELL = "annual_leave_days"   # ships no baseline, so each test controls its own

def rows(): return savings.read_ledger()
def calls(): return [r for r in rows() if r.get("type") == "call"]

class Meter(unittest.TestCase):
    def setUp(self):
        if os.path.exists(hub.LEDGER): os.remove(hub.LEDGER)
        shutil.rmtree(os.path.join(HOME, "baselines"), ignore_errors=True)

    def _baseline(self, model, tokens, version="1.0"):
        p = savings.user_baseline_path(CELL, version); os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump({"format": savings.BASELINE, "cell": CELL, "version": version, "models": {model: {"kind": "measured", "tokens": tokens}}}, open(p, "w"))

    def test_estimator_is_stable(self):
        self.assertEqual(savings.est_tokens("abcd"), 1)
        self.assertEqual(savings.est_tokens("부가세"), 3)
        self.assertEqual(savings.est_tokens("ab부"), 2)

    def test_every_call_is_metered_without_baseline(self):
        r = hub.call(CELL, {"years": 3}, caller="t")
        self.assertEqual(r["status"], "ok")
        t = calls()[-1]["tokens"]
        self.assertEqual(t["meter"], "meter/1"); self.assertEqual(t["kind"], "none")
        self.assertIsNone(t["baseline"]); self.assertIsNone(t["saved"]); self.assertGreater(t["cost"], 0)

    def test_measured_baseline_for_same_model(self):
        self._baseline("m1", 500)
        guides.call(CELL, {"years": 3}, model="m1", caller="t")
        row = calls()[-1]; t = row["tokens"]
        self.assertEqual(row["model"], "m1"); self.assertEqual(t["kind"], "measured")
        self.assertEqual(t["saved"], 500 - t["cost"])
        self.assertEqual(t["cost"], -(-t["cost_text_est"] * t["cost_ratio"] // 1))

    def test_cost_counts_the_reply_the_model_reads(self):
        guides.call(CELL, {"years": 3}, model="m1", caller="t")
        plain = hub.call(CELL, {"years": 3}, caller="t", log=False)
        self.assertGreater(calls()[-1]["tokens"]["cost"], savings.est_tokens(json.dumps(plain, ensure_ascii=False, sort_keys=True)))

    def test_other_model_is_estimate_and_takes_the_smallest(self):
        self._baseline("m1", 500); self._baseline("m2", 300, version="0.9")
        hub.call(CELL, {"years": 3}, caller="t", model="m3")
        t = calls()[-1]["tokens"]; self.assertEqual(t["kind"], "estimate"); self.assertEqual(t["baseline"], 300)

    def test_refused_call_saves_negative(self):
        self._baseline("m1", 500)
        hub.call(CELL, {"months": 1}, caller="t", model="m1")
        t = calls()[-1]["tokens"]; self.assertEqual(t["kind"], "refused"); self.assertEqual(t["saved"], -t["cost"])
        hub.call("no_such_cell", {}, caller="t", model="m1")
        self.assertEqual(calls()[-1]["tokens"]["kind"], "refused")

    def test_summary_keeps_kinds_apart_and_subtracts_find(self):
        self._baseline("m1", 500)
        hub.call(CELL, {"years": 3}, caller="t", model="m1")      # measured
        hub.call(CELL, {"years": 5}, caller="t", model="m9")      # estimate
        hub.call(CELL, {"months": 1}, caller="t", model="m1")          # refused
        hub._log({"type": "call", "cell": CELL, "status": "ok"})       # an old, unmetered row
        mcp.MODEL = "m1"; mcp.handle("find_cell", {"need": "근속 연수 연차 일수"})
        s = savings.summarize(rows())
        self.assertEqual(s["measured"]["calls"], 1); self.assertEqual(s["estimate"]["calls"], 1); self.assertEqual(s["refused"]["calls"], 1)
        self.assertEqual(s["unmetered_calls"], 1); self.assertEqual(s["tool_overhead"]["by_tool"]["find_cell"]["rows"], 1)
        self.assertEqual(s["net_measured"], round(s["measured"]["saved"] + s["refused"]["saved"] - s["tool_overhead"]["cost"], 1))
        self.assertIn("m1", s["by_model"]); self.assertIn(CELL, s["by_cell"])

    def test_cost_ratio_never_below_measured(self):
        r, how = savings.cost_ratio("exaone3.5:7.8b")       # shipped baselines measured 2.46-2.58
        self.assertEqual(how, "measured"); self.assertGreaterEqual(r, 2.5)
        r2, how2 = savings.cost_ratio("someone:1b")
        self.assertEqual(how2, "other_model"); self.assertGreaterEqual(r2, r)

    def test_shipped_baselines_load(self):
        b = savings.baseline_for("vat_supply_price", "1.0", "exaone3.5:7.8b")
        self.assertEqual(b[1], "measured"); self.assertGreater(b[0], 0)

    def test_mcp_extra_reply_is_counted(self):
        mcp.MODEL = "m1"
        out = mcp.handle("call_cell", {"cell": "vat_calc", "input": {"zzz": 1}})   # wrong name: server adds did_you_mean / no_cell
        extra = [r for r in rows() if r.get("type") == "meter" and r.get("tool") == "call_cell"]
        self.assertTrue(any(k not in mcp.CORE for k in out)); self.assertEqual(len(extra), 1); self.assertGreater(extra[0]["tokens"]["cost"], 0)
        mcp.handle("list_cells", {})
        self.assertTrue(any(r.get("tool") == "list_cells" for r in rows() if r.get("type") == "meter"))

    def test_raw_counts_kept(self):
        hub.call(CELL, {"years": 3}, caller="t")
        t = calls()[-1]["tokens"]
        self.assertEqual(t["cost_text_est"], -(-t["chars_ascii"] // 4) + t["chars_other"])

    def test_cli_bad_days(self):
        self.assertEqual(cli.main(["savings", "--days", "x"]), 2)

    def test_damaged_line_does_not_blank_report(self):
        hub.call(CELL, {"years": 3}, caller="t")
        open(hub.LEDGER, "a").write("{broken\n")
        self.assertEqual(savings.summarize(rows())["no_baseline"]["calls"], 1)

    def test_measure_writes_baseline_with_fake_model(self):
        def fake(url, model, messages, **k):
            alone = len(messages) == 1
            return {"text": "풀이... {\"supply_price\": 0, \"vat\": 0}", "in": 100 if alone else 260, "out": 400 if alone else 40, "sec": 0}
        r = savings.measure(CELL, "fake:1b", n=3, chat=fake)
        self.assertTrue(r["ok"]); b = r["baseline"]
        self.assertEqual(b["tokens"], 360); self.assertEqual(b["n"], 3); self.assertFalse(b["retry_included"])
        self.assertEqual(b["cost_real_mean"], 160); self.assertGreater(b["cost_ratio"], 1)
        hub.call(CELL, {"years": 3}, caller="t", model="fake:1b")
        self.assertEqual(calls()[-1]["tokens"]["kind"], "measured")
        self.assertEqual(calls()[-1]["tokens"]["baseline"], 360)

    def test_cli_savings_runs(self):
        hub.call(CELL, {"years": 3}, caller="t")
        self.assertEqual(cli.main(["savings", "--days", "7"]), 0)

if __name__ == "__main__":
    unittest.main()
