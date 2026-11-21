#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A digest of every reply hub.call gives for every ground-truth case of every shipped cell version, to compare two trees.
  python scripts/gt_replies.py <tree> > digests.json
Each reply (answers, refusals and asked-back replies alike) is hashed as sorted JSON."""
import glob, hashlib, json, os, sys, tempfile
sys.path.insert(0, os.path.abspath(sys.argv[1])); os.environ["STEMSEAL_HOME"] = tempfile.mkdtemp()
from stemseal import hub
out = {}
for p in sorted(glob.glob(os.path.join(hub.CELLS, "*", "*", "gt_cases.json"))):
    d = os.path.dirname(p); name, v = os.path.basename(os.path.dirname(d)), os.path.basename(d)
    with open(p, encoding="utf-8") as f: cases = json.load(f)
    for i, c in enumerate(cases):
        r = hub.call(name, c["input"], caller="digest", version=v, log=False)
        out["%s/%s/%d" % (name, v, i)] = hashlib.sha256(json.dumps(r, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
print(json.dumps(out, indent=0, sort_keys=True))
