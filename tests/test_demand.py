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
        m = mcp.handle("find_cell", {"need": "대출 원리금 균등상환 월 납입액 계산"})["no_cell"]
        self.assertEqual(set(m), {"message"}); self.assertIn("2번째", m["message"])
        self.assertNotIn("share", nc)                                           # the issue link is for people (stemseal demand), not the model
        self.assertLess(len(json.dumps(nc, ensure_ascii=False)), 400)

    def test_hit_records_nothing(self):
        r = guides.find("부가세 포함 금액에서 공급가액 계산", caller="t")
        self.assertTrue(r["cells"]); self.assertEqual(demand_rows(), [])

    def test_request_cell_tool(self):
        out = mcp.handle("request_cell", {"need": "대출 원리금 균등상환 월 납입액", "example": "1000000원, 연 5%, 12개월 -> 85607"})
        self.assertEqual(set(out) - {"closest_cell"}, {"message"}); self.assertIn("1번", out["message"])
        row = demand_rows()[-1]; self.assertTrue(row["explicit"]); self.assertIn("85607", row["example"])
        self.assertFalse(mcp.handle("request_cell", {}).get("recorded", True))           # empty need: told what to say, nothing logged
        self.assertEqual(len(demand_rows()), 1)

    def test_alike_requests_are_one_group(self):
        hub.request_cell("대출 원리금 균등상환 월 납입액", caller="a")
        hub.request_cell("대출 원리금 균등상환 월 납입액 3000000", caller="b")   # numbers are data, not a new need
        hub.request_cell("대출 원리금 균등상환 월납입액 계산", caller="c")       # spacing and filler words
        hub.request_cell("대출 월 납입액 원리금 균등상환", caller="d")          # word order
        hub.request_cell("Loan monthly payment amortization", caller="e")
        hub.request_cell("체지방률 계산", caller="f")
        g = hub.demand_summary()
        self.assertEqual(g[0]["count"], 4); self.assertEqual(len(g), 3)
        self.assertIn("5번째", hub.request_cell("대출 원리금 균등상환 월 납입액", caller="g")["message"])

    def test_different_calculations_stay_apart(self):
        # merging two calculations hides one of them; these all scored 0.5+ on letter overlap
        pairs = [("월급에서 4대보험 공제액", "월급에서 소득세 공제액"), ("복리 이자 계산", "단리 이자 계산"),
                 ("섭씨를 화씨로", "화씨를 섭씨로"), ("평균 계산", "가중 평균 계산"), ("평균", "가중 평균")]
        for a, b in pairs:
            if os.path.exists(hub.LEDGER): os.remove(hub.LEDGER)
            hub.request_cell(a, caller="x"); hub.request_cell(b, caller="y")
            self.assertEqual(len(hub.demand_summary()), 2, (a, b))
        if os.path.exists(hub.LEDGER): os.remove(hub.LEDGER)
        hub.request_cell("loan monthly payment", caller="x"); hub.request_cell("monthly loan payment amount", caller="y")
        self.assertEqual(len(hub.demand_summary()), 1)

    def test_new_request_not_swallowed_by_ready_group(self):
        t = hub.request_cell("부가세 포함 금액에서 공급가액 계산", caller="a")["ticket"]
        hub.fulfill(t, "vat_supply_price")
        hub.request_cell("부가세 포함 금액에서 봉사료 별도 계산", caller="b")
        open_ = hub.demand_summary(); self.assertEqual(len(open_), 1); self.assertIn("봉사료", open_[0]["need"])

    def test_broken_line_is_skipped(self):
        hub.request_cell("대출 원리금 균등상환 월 납입액", caller="a")
        with open(hub.LEDGER, "a", encoding="utf-8") as f: f.write('{"type": "demand", "need": "반쯤 써진\n')
        hub.request_cell("체지방률", caller="b")
        self.assertEqual(len(hub.demand_summary()), 2)

    def test_big_ledger_stays_fast(self):
        import time
        with open(hub.LEDGER, "a", encoding="utf-8") as f:
            for i in range(3000):
                f.write(json.dumps({"ts": "2026-11-19T00:00:00+00:00", "type": "demand", "need": "요청 %s 계산" % "".join(chr(97 + i // 26 ** j % 26) for j in range(3)), "ticket": "D-%08x" % i, "auto": True}, ensure_ascii=False) + "\n")
                f.write(json.dumps({"ts": "2026-11-19T00:00:00+00:00", "type": "call", "cell": "x", "status": "ok"}) + "\n")
        t0 = time.time(); guides.find("대출 원리금 균등상환 월 납입액", caller="t"); self.assertLess(time.time() - t0, 1.0)
        t0 = time.time(); self.assertGreaterEqual(len(hub.demand_summary()), 2900); self.assertLess(time.time() - t0, 2.0)

    def test_issue_text_hides_contact_data(self):
        hub.request_cell("손님 홍길동 010-1234-5678 hong@example.com 대출 월 납입액 3,000,000원", caller="a", example="계좌 110-123-456789 -> ?")
        title, body = hub.issue_text(hub.demand_summary()[0])
        for leak in ("010-1234-5678", "hong@example.com", "110-123-456789"): self.assertNotIn(leak, title + body)
        self.assertIn("3,000,000", title + body)                                 # amounts stay: they are the example

    def test_misspelt_existing_cell_is_not_demand(self):
        mcp.handle("call_cell", {"cell": "vat_calc", "input": {"amount": 11000}})
        self.assertEqual(demand_rows(), [])

    def test_weak_nearest_not_recorded(self):
        hub.request_cell("loan calc", caller="a")
        self.assertIsNone(demand_rows()[-1]["nearest"])

    def test_non_text_need(self):
        self.assertIn("cells", mcp.handle("find_cell", {"need": None}))
        self.assertIn("cells", mcp.handle("find_cell", {"need": {"x": 1}}))

    def test_fulfilled_group_leaves_open_list(self):
        t = hub.request_cell("부가세 더하기 공급가액에 부가세 붙인 합계", caller="a")["ticket"]
        hub.request_cell("공급가액에 부가세 붙인 합계", caller="b")             # filler word dropped: different words, kept apart
        self.assertEqual(len(hub.demand_summary()), 2)
        hub.fulfill(hub.demand_summary()[1]["ticket"], "vat_supply_price")
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
        self.assertIn("vat_supply_price", nc.get("closest_cell", "")); self.assertIn("때만", nc["closest_cell"])

    def test_english_reply(self):
        nc = hub.request_cell("loan amortization monthly payment", caller="a")
        self.assertTrue(nc["message"].startswith("No verified cell"))
        self.assertLess(len(json.dumps(mcp._for_model(nc))), 400)

    def test_cli_demand(self):
        hub.request_cell("대출 원리금 균등상환 월 납입액", caller="a", example="1000000, 5%, 12 -> 85607")
        self.assertEqual(cli.main(["demand"]), 0); self.assertEqual(cli.main(["demand", "--share"]), 0)
        self.assertEqual(cli.main(["demand", "--open", "x"]), 2)
        self.assertEqual(cli.main(["demand", "--open", "1"]), 0)                  # not a terminal: shows the text, opens nothing
        self.assertEqual(cli.main(["request", "체지방률", "--example", "허리 80 -> 20%"]), 0)
        self.assertIn("허리 80", demand_rows()[-1]["example"])

if __name__ == "__main__": unittest.main()
