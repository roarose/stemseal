"""The Korean reader (amounts, counts, the 'is it really in the question' check) is one block of code shared by the cells that
read a customer's own words. Cells cannot import each other, so each carries a copy; this test keeps the copies identical."""
import os, re, unittest
ROOT = os.path.join(os.path.dirname(__file__), "..", "stemseal", "cells")
USERS = [("korean_amount", "3.0"), ("order_total", "9.0"), ("store_hours", "7.0"), ("menu_order_total", "8.0"), ("store_faq", "2.0"), ("party_set", "4.0")]
BLOCK = re.compile(r"# --- korean reader (\d+) begin.*?# --- korean reader \1 end ---", re.S)
class ReaderBlock(unittest.TestCase):
    def test_copies_are_identical(self):
        blocks = {}
        for name, ver in USERS:
            src = open(os.path.join(ROOT, name, ver, "cell.py"), encoding="utf-8").read()
            m = BLOCK.search(src)
            self.assertIsNotNone(m, "%s %s has no reader block" % (name, ver))
            blocks[name] = m.group(0)
        self.assertEqual(len(set(blocks.values())), 1, "reader copies differ: %s" % sorted(blocks))
if __name__ == "__main__":
    unittest.main()
