# -*- coding: utf-8 -*-
"""party_set 5.0 and store_hours 8.0: words that change what a number or a time means are asked about, never computed
(the sentences that broke the PR 17 review). The earlier versions stay as they were (they are being measured)."""
import os, sys, tempfile, unittest
os.environ.setdefault("STEMSEAL_HOME", tempfile.mkdtemp(prefix="stemseal_test_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stemseal import hub
SETS = [{"name": "한상 2인", "people": 2, "price": 30000}, {"name": "한상 3인", "people": 3, "price": 42000}, {"name": "큰상 4인", "people": 4, "price": 55000}]
def res(name, version, inp):
    r = hub.call(name, inp, caller="t", version=version, log=False)
    assert r["status"] == "ok", r
    return r["result"]
class StoreMeaning(unittest.TestCase):
    def test_people(self):
        for q in ("2~3명이요", "두 명 추가요", "한 명 추가요", "한 명 빠졌어요", "세 명이서 둘만 먹어요", "넷이서 왔는데 하나는 안 먹어요", "둘에 둘", "두 명 아이 둘"):
            with self.subTest(q=q):
                r = res("party_set", "5.0", {"question": q, "sets": SETS})
                self.assertFalse(r["answer_ready"]); self.assertIsNone(r["people"])
        self.assertEqual(res("party_set", "5.0", {"question": "넷이서 왔는데 어떤 세트가 좋아요", "sets": SETS})["people"], 4)
        self.assertEqual(res("party_set", "4.0", {"question": "2~3명이요", "sets": SETS})["people"], 3)   # 4.0 unchanged
    def test_hours(self):
        base = "오전 11시에 열고 밤 10시까지"
        for q, now, close in ((base + "인데 지금 오후 2시 10분 전이에요", "오후 2시 10분", "밤 10시"),
                              ("오전 11시에 열고 밤 10시 마감 아니고 9시 마감이에요 지금 저녁 8시 반", "저녁 8시 반", "밤 10시"),
                              (base + "인데 오늘은 9시에 닫아요 지금 저녁 8시 55분", "저녁 8시 55분", "밤 10시"),
                              (base + "인데 한 시간 연장해요 지금 밤 10시 반", "밤 10시 반", "밤 10시"),
                              (base + ", 주말은 9시 마감이에요 지금 밤 9시 반", "밤 9시 반", "밤 10시"),
                              (base + "인데 오늘 휴무예요? 지금 오후 3시", "오후 3시", "밤 10시"),
                              (base + ", 4시~5시 휴식이에요 지금 오후 4시 반", "오후 4시 반", "밤 10시")):
            with self.subTest(q=q):
                r = res("store_hours", "8.0", {"question": q, "now": now, "open": "오전 11시", "close": close})
                self.assertFalse(r["answer_ready"]); self.assertIsNone(r["is_open"])
        r = res("store_hours", "8.0", {"question": base + "인데 지금 밤 9시 반이에요", "now": "밤 9시 반", "open": "오전 11시", "close": "밤 10시"})
        self.assertEqual((r["is_open"], r["minutes_to_close"]), (True, 30))
if __name__ == "__main__":
    unittest.main()
