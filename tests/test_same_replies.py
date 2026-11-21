# -*- coding: utf-8 -*-
"""Every reply hub.call gives for every ground-truth case of every shipped cell version (answers, refusals and asked-back
replies) is byte for byte the reply of the recorded tree (tests/data/gt_replies_main.json, from scripts/gt_replies.py).
A change to a cell or a reply is a new recording, made on purpose. Run: python -m unittest discover -s tests"""
import glob, hashlib, json, os, sys, tempfile, unittest
from concurrent.futures import ThreadPoolExecutor
os.environ.setdefault("STEMSEAL_HOME", tempfile.mkdtemp(prefix="stemseal_test_"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from stemseal import hub

class SameReplies(unittest.TestCase):
    def test_every_ground_truth_reply_is_unchanged(self):
        with open(os.path.join(ROOT, "tests", "data", "gt_replies_main.json"), encoding="utf-8") as f: want = json.load(f)
        jobs = []
        for p in sorted(glob.glob(os.path.join(hub.CELLS, "*", "*", "gt_cases.json"))):
            d = os.path.dirname(p); name, v = os.path.basename(os.path.dirname(d)), os.path.basename(d)
            with open(p, encoding="utf-8") as f: cases = json.load(f)
            jobs += [("%s/%s/%d" % (name, v, i), name, v, c["input"]) for i, c in enumerate(cases)]
        def digest(job):
            key, name, v, inp = job
            r = hub.call(name, inp, caller="digest", version=v, log=False)
            return key, hashlib.sha256(json.dumps(r, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        with ThreadPoolExecutor(max_workers=4) as ex: got = dict(ex.map(digest, jobs))
        self.assertEqual(sorted(got), sorted(want))
        changed = sorted(k for k in want if got[k] != want[k])
        self.assertEqual(changed, [], "%d of %d replies changed" % (len(changed), len(want)))

if __name__ == "__main__":
    unittest.main()
