"""Shared blocks of code: cells cannot import each other, so each cell that needs a block carries a copy; this test keeps the
copies identical. The Korean reader (amounts, counts, the 'is it really in the question' check) is in every cell that reads a
customer's own words; the count finder and the store-list reader are in the part cells that need them."""
import os, re, unittest
ROOT = os.path.join(os.path.dirname(__file__), "..", "stemseal", "cells")
PARTS_READING = [("catalog_match", "1.0"), ("ko_count_spans", "1.0"), ("unread_guard", "1.0"), ("catalog_lines", "1.0"),
                 ("price_items", "1.0"), ("ko_discount", "1.0"), ("ko_time", "1.0"), ("ko_people", "1.0")]
USERS = [("korean_amount", "3.0"), ("order_total", "9.0"), ("store_hours", "7.0"), ("menu_order_total", "8.0"), ("store_faq", "2.0"), ("party_set", "4.0")] + PARTS_READING
BLOCKS = {   # block name: the cells that carry a copy
    "korean reader": USERS,
    "korean counts": [("catalog_match", "1.0"), ("ko_count_spans", "1.0")],
    "catalog reader": [("catalog_match", "1.0"), ("catalog_lines", "1.0")],
}
def _block(name): return re.compile(r"# --- %s (\d+) begin.*?# --- %s \1 end ---" % (name, name), re.S)
class ReaderBlock(unittest.TestCase):
    def test_copies_are_identical(self):
        for block, users in BLOCKS.items():
            with self.subTest(block=block):
                found = {}
                for name, ver in users:
                    src = open(os.path.join(ROOT, name, ver, "cell.py"), encoding="utf-8").read()
                    m = _block(block).search(src)
                    self.assertIsNotNone(m, "%s %s has no %s block" % (name, ver, block))
                    found[name] = m.group(0)
                self.assertEqual(len(set(found.values())), 1, "%s copies differ: %s" % (block, sorted(found)))
if __name__ == "__main__":
    unittest.main()
