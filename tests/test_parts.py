"""Part cells: one step of a job (read a time, find names in a list, add up lines...), to be put together into organs.
They are sealed like any cell, declare their output shape, and never push a whole-job cell out of find's first places."""
import os, sys, tempfile, unittest
os.environ.setdefault("STEMSEAL_HOME", tempfile.mkdtemp(prefix="stemseal_test_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stemseal import hub
PARTS = ["catalog_match", "ko_count_spans", "unread_guard", "catalog_lines", "line_total", "price_items", "ko_discount",
         "apply_discount", "ko_time", "ampm_ask", "hours_caveat", "time_window", "ko_people", "set_for_people"]
class Parts(unittest.TestCase):
    def test_sealed_with_part_flag_and_output_schema(self):
        for n in PARTS:
            with self.subTest(cell=n):
                c = hub.load(n, "1.0"); self.assertIsNotNone(c)
                self.assertIs(c["contract"].get("part"), True)
                self.assertEqual(set(c["contract"]["output_schema"]), set(c["contract"]["output_keys"]))
                self.assertEqual(c["lock"]["format"], 2)
    def test_whole_job_cells_come_first(self):
        for need, first in [("4500원짜리 두 개 10% 할인", "order_total"), ("세 명이서 먹을 세트", "party_set"),
                            ("지금 영업 중이에요?", "store_hours"), ("인원 몇 명", "party_set"), ("합계 계산", "menu_order_total")]:
            with self.subTest(need=need):
                hits = hub.find(need, caller="t", record=False)
                self.assertEqual(hits[0]["cell"], first)
                flags = [bool(hub.load(h["cell"])["contract"].get("part")) for h in hits]
                self.assertEqual(flags, sorted(flags), "a part cell came before a whole-job cell: %s" % [h["cell"] for h in hits])
    def test_parts_are_still_found(self):
        self.assertIn("ko_time", [h["cell"] for h in hub.find("몇 시까지 해요?", caller="t", record=False)])
if __name__ == "__main__":
    unittest.main()
