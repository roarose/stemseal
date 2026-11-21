# -*- coding: utf-8 -*-
"""Part cells: one step of a job (read a time, find names in a list, add up lines...), to be put together into organs.
They are sealed like any cell and declare their output shape. Until the organ runner exists they are hidden from models
(find_cell, list_cells), so every reply a model gets is the reply of the recorded main tree (tests/data/find_replies_main.json,
from scripts/find_replies.py). A part that reads the customer's words never gives a quiet wrong value on its own: with words
that change the value's meaning it asks (the sentences that broke the PR 17 review are kept here)."""
import json, os, subprocess, sys, tempfile, unittest
os.environ.setdefault("STEMSEAL_HOME", tempfile.mkdtemp(prefix="stemseal_test_"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from stemseal import hub, mcp
PARTS = ["catalog_match", "ko_count_spans", "unread_guard", "catalog_lines", "line_total", "price_items", "ko_discount",
         "apply_discount", "ko_time", "ampm_ask", "hours_caveat", "time_window", "ko_people", "set_for_people"]
READERS = ["catalog_match", "ko_count_spans", "price_items", "ko_discount", "ko_time", "hours_caveat", "ko_people"]
MENU = [{"name": "계란말이", "price": 7000}, {"name": "콜라", "price": 2000}]
def call(name, inp):
    r = hub.call(name, inp, caller="t", log=False)
    assert r["status"] == "ok", r
    return r["result"]
class Parts(unittest.TestCase):
    def test_sealed_with_part_flag_and_output_schema(self):
        for n in PARTS:
            with self.subTest(cell=n):
                c = hub.load(n, "1.0"); self.assertIsNotNone(c)
                self.assertIs(c["contract"].get("part"), True)
                self.assertEqual(set(c["contract"]["output_schema"]), set(c["contract"]["output_keys"]))
                self.assertEqual(c["lock"]["format"], 2)
    def test_readers_return_spans_and_the_ask_shape(self):
        for n in READERS:
            with self.subTest(cell=n):
                keys = set(hub.load(n, "1.0")["contract"]["output_keys"])
                self.assertTrue({"spans", "answer_ready", "asks"} <= keys, keys)
    def test_hidden_from_models(self):
        listed = {c["cell"] for c in hub.list_cells()}
        self.assertFalse(listed & set(PARTS))
        self.assertTrue(set(PARTS) <= {c["cell"] for c in hub.list_cells(parts=True)})
        for need in ("몇 시까지 해요?", "세 명이서 먹을 세트", "4500원짜리 두 개 10% 할인", "시각 읽기", "합계 계산"):
            self.assertFalse({h["cell"] for h in hub.find(need, caller="t", record=False)} & set(PARTS), need)
        self.assertEqual(call("line_total", {"lines": [{"unit_price": 1000, "qty": 2}]})["total"], 2000)   # still callable by name
    def test_model_replies_are_main_replies(self):
        out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "find_replies.py"), ROOT], capture_output=True, text=True,
                             encoding="utf-8", env=dict(os.environ, STEMSEAL_HOME=tempfile.mkdtemp()))
        self.assertEqual(out.returncode, 0, out.stderr)
        with open(os.path.join(ROOT, "tests", "data", "find_replies_main.json"), encoding="utf-8") as f: want = json.load(f)
        got = json.loads(out.stdout)
        self.assertEqual(sorted(k for k in want if got.get(k) != want[k]), [])
    def test_people_words_that_change_the_number_ask(self):
        for q in ("2~3명", "두 명 추가", "한 명 추가요", "한 명 빠졌어요", "세 명이서 둘만", "넷이서 왔는데 하나는 안 먹어요", "둘에 둘", "두 명 아이 둘"):
            with self.subTest(q=q):
                r = call("ko_people", {"question": q}); self.assertFalse(r["answer_ready"]); self.assertIsNone(r["people"])
        r = call("ko_people", {"question": "넷이서 왔는데 어떤 세트가 좋아요"}); self.assertEqual((r["people"], r["spans"]), (4, [[0, 3]]))
    def test_time_words_that_change_the_time_ask(self):
        for q, w, role in (("지금 오후 2시 10분 전인데 열었어요?", "오후 2시 10분", "now"), ("밤 10시 마감 아니고 9시 마감이에요", "밤 10시", "close"),
                           ("오전 11시나 12시 오픈이에요", "오전 11시", "open"), ("10시쯤 마감해요", "10시", "close")):
            with self.subTest(q=q):
                r = call("ko_time", {"question": q, "words": w, "role": role}); self.assertFalse(r["answer_ready"]); self.assertIsNone(r["minutes"])
        for q in ("오늘은 9시에 닫아요", "오늘은 30분 일찍 닫아요", "한 시간 연장해요", "주말은 9시 마감", "오늘 휴무예요?", "4시~5시 휴식",
                  "4시 반에 문 닫았다가 6시에 다시 열어요"):
            with self.subTest(q=q):
                self.assertFalse(call("hours_caveat", {"question": q})["answer_ready"])
    def test_order_words_that_change_a_count_ask(self):
        for q, items in (("라면 4500원 두 그릇 빼 주세요", [{"name": "라면", "price": "4500원"}]), ("만원짜리 너이", [{"price": "만원"}]),
                         ("만원짜리 두 개 반", [{"price": "만원"}]), ("만원짜리 사람 수대로", [{"price": "만원"}])):
            with self.subTest(q=q):
                r = call("price_items", {"question": q, "items": items}); self.assertFalse(r["answer_ready"]); self.assertEqual(r["items_read"], [])
        for q in ("계란말이 두 개 빼 주세요", "계란말이 너이", "계란말이 두 개 반"):
            with self.subTest(q=q):
                m = call("catalog_match", {"question": q, "catalog": MENU, "said": [{"name": "계란말이"}]})
                r = call("ko_count_spans", {"question": q, "owners": m["matches"]})
                self.assertFalse(r["answer_ready"]); self.assertIsNone(r["counts"][0]["value"])
    def test_menu_order_words_are_menu_order_total_words(self):
        for q, used in (("공기밥 하나 있어요?", [[0, 3], [3, 5]]), ("계란말이 하나 있고", [[0, 4], [4, 6]]), ("콜라 하나 해서", [[0, 2], [2, 4]])):
            with self.subTest(q=q):
                self.assertFalse(call("unread_guard", {"question": q, "used": used, "list": "order"})["answer_ready"])
                self.assertTrue(call("unread_guard", {"question": q, "used": used, "list": "order_refuse"})["answer_ready"])
if __name__ == "__main__":
    unittest.main()
