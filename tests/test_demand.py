# -*- coding: utf-8 -*-
"""Demand loop: a need nothing fits is recorded without the model doing anything, alike needs are counted together,
and the reply tells the model what happens next. Run: python -m unittest discover -s tests"""
import json, os, sys, tempfile, unittest
HOME = tempfile.mkdtemp(prefix="stemseal_test_"); os.environ["STEMSEAL_HOME"] = HOME
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stemseal import hub, guides, mcp, cli

def demand_rows(): return [r for r in hub._rows() if r.get("type") == "demand"]

class Demand(unittest.TestCase):
    def setUp(self):
        if os.path.exists(hub.LEDGER): os.remove(hub.LEDGER)

    def test_find_miss_is_recorded_automatically(self):
        r = guides.find("대출 원리금 균등상환 월 납입액 계산", model="qwen2.5:3b", caller="t")
        self.assertEqual(r["cells"], [])
        rows = demand_rows(); self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["auto"]); self.assertEqual(rows[0]["model"], "qwen2.5:3b"); self.assertTrue(rows[0]["ticket"].startswith("D-"))
        self.assertIn("nearest", rows[0]); self.assertIn("nearest_score", rows[0])
        nc = r["no_cell"]; self.assertEqual(nc["ticket"], rows[0]["ticket"]); self.assertIn("find_cell", nc["message"])
        self.assertIn("github.com/roarose/stemseal/issues/new", nc["share"]["link"])

    def test_hit_records_nothing(self):
        r = guides.find("부가세 포함 금액에서 공급가액 계산", caller="t")
        self.assertTrue(r["cells"]); self.assertEqual(demand_rows(), [])

    def test_request_cell_tool(self):
        out = mcp.handle("request_cell", {"need": "대출 원리금 균등상환 월 납입액", "example": "1000000원, 연 5%, 12개월 -> 85607"})
        self.assertTrue(out["recorded"]); self.assertEqual(out["times_requested"], 1)
        row = demand_rows()[-1]; self.assertTrue(row["explicit"]); self.assertIn("85607", row["example"])
        self.assertFalse(mcp.handle("request_cell", {})["recorded"])           # empty need: told what to say, nothing logged
        self.assertEqual(len(demand_rows()), 1)

    def test_alike_requests_are_one_group(self):
        hub.request_cell("대출 원리금 균등상환 월 납입액", caller="a")
        hub.request_cell("대출 원리금 균등상환 월 납입액 3000000", caller="b")   # numbers are data, not a new need
        hub.request_cell("대출 원리금 균등상환 월납입액 계산", caller="c")
        r = hub.request_cell("Loan monthly payment amortization", caller="d")
        hub.request_cell("체지방률 계산", caller="e")
        g = hub.demand_summary()
        self.assertEqual(g[0]["count"], 3); self.assertEqual(len(g), 3)
        self.assertEqual(r["times_requested"], 1)
        self.assertEqual(hub.request_cell("대출 원리금 균등상환 월 납입액", caller="f")["times_requested"], 4)

    def test_fulfilled_group_leaves_open_list(self):
        t = hub.request_cell("부가세 더하기 공급가액에 부가세 붙인 합계", caller="a")["ticket"]
        hub.request_cell("공급가액에 부가세 붙인 합계 금액", caller="b")
        self.assertEqual(len(hub.demand_summary()), 1)
        hub.fulfill(t, "vat_supply_price")
        self.assertEqual(hub.demand_summary(), [])
        self.assertEqual(hub.demand_summary(include_ready=True)[0]["status"], "ready")
        self.assertEqual(hub.request_status(t)["status"], "ready")

    def test_guessed_name_logged_once(self):
        mcp.handle("call_cell", {"cell": "loan_amortization", "input": {"principal": 1000000}})
        self.assertEqual(len(demand_rows()), 1)
        self.assertTrue(demand_rows()[0]["auto"])
        mcp.handle("call_cell", {"cell": "zzqx", "input": {}})                 # matches nothing: recorded once as well
        self.assertEqual(len(demand_rows()), 2)

    def test_closest_cell_offered(self):
        nc = hub.request_cell("부가세 포함 금액 공급가액 나누기 반올림 방식 다르게", caller="a")
        self.assertEqual(nc.get("closest_cell", {}).get("cell"), "vat_supply_price")
        self.assertIn("다른 계산이면", nc["closest_cell"]["note"])

    def test_english_reply(self):
        nc = hub.request_cell("loan amortization monthly payment", caller="a")
        self.assertTrue(nc["message"].startswith("No verified cell"))

    def test_cli_demand(self):
        hub.request_cell("대출 원리금 균등상환 월 납입액", caller="a", example="1000000, 5%, 12 -> 85607")
        self.assertEqual(cli.main(["demand"]), 0); self.assertEqual(cli.main(["demand", "--share"]), 0)
        self.assertEqual(cli.main(["demand", "--open", "x"]), 2)
        self.assertEqual(cli.main(["request", "체지방률", "--example", "허리 80 -> 20%"]), 0)
        self.assertIn("허리 80", demand_rows()[-1]["example"])

if __name__ == "__main__": unittest.main()
