# -*- coding: utf-8 -*-
"""stemseal update from signed cell releases (stemseal/update.py), against a local server in place of GitHub.
Keys are made here for each run and never written to the repository. Run: python -m unittest discover -s tests"""
import functools, hashlib, http.server, json, os, shutil, sys, tempfile, threading, unittest
from unittest import mock
os.environ.setdefault("STEMSEAL_HOME", tempfile.mkdtemp(prefix="stemseal_test_"))
for k in ("NO_PROXY", "no_proxy"): os.environ[k] = ",".join(x for x in (os.environ.get(k), "127.0.0.1", "localhost") if x)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stemseal import ed25519, hub, policy, seal, update

KEY, SPARE, OTHER = (hashlib.sha256(os.urandom(32)).digest() for _ in range(3))
SRC = "def cell_executor(input_data):\n    return {\"v\": input_data[\"x\"] * 2}\n"
CONTRACT = {"description": "doubles x", "input_schema": {"required": ["x"], "properties": {"x": "number"}}, "output_keys": ["v"], "output_schema": {"v": "number"}}
GT = [{"input": {"x": i}, "expected": {"v": i * 2}} for i in range(hub.MIN_GT)]
def j(o): return json.dumps(o, ensure_ascii=False).encode("utf-8")

def cell_files(name, version="1.0", src=SRC, gt=None, fmt=2):
    raw = {"cell.py": src.encode("utf-8"), "contract.json": j(CONTRACT), "gt_cases.json": j(GT if gt is None else gt)}
    lock = seal.build(name, version, raw, policy.POLICY_VERSION, 20, 20, "t", "t")
    if fmt == 1: lock = {k: v for k, v in lock.items() if k not in ("format", "kind", "files", "policy")}
    raw["lock.json"] = seal.dumps(lock)
    return raw

class Site:
    """Files the local server gives: refs, cells-N/release.json and cell files, sig/cells-N/release.json.sig."""
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="stemseal_site_"); self.tags = []; self.raw = {}
        handler = functools.partial(Quiet, directory=self.root)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]
    def put(self, rel, data):
        p = os.path.join(self.root, *rel.split("/")); os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f: f.write(data)
    def tag(self, n):
        self.tags.append(n); self.put("refs", j([{"ref": "refs/tags/cells-%d" % t} for t in self.tags]))
    def release(self, n, cells, key=KEY, previous=True, revoked=(), tier="sealed", extra=None, sign=True, release_no=None, min_client="0.2.3"):
        """cells: {name: {version: {file: bytes}}}. Returns the release.json bytes."""
        entries = {}
        for name, vers in cells.items():
            for v, files in vers.items():
                for f, data in files.items(): self.put("cells-%d/%s/%s/%s" % (n, name, v, f), data)
                entries.setdefault(name, {})[v] = {"files": {f: seal.sha(d) for f, d in files.items()}, "tier": tier, "gt": 20, "locked_at": "t",
                                                   "description": "d", "description_en": "d", "answers": []}
        rel = {"format": 2, "release": n if release_no is None else release_no, "min_client": min_client, "created_at": "t",
               "previous_index_sha256": seal.sha(self.raw[n - 1]) if previous and n - 1 in self.raw else None, "cells": entries, "revoked": list(revoked)}
        if extra: rel.update(extra)
        raw = j(rel); self.raw[n] = raw
        self.put("cells-%d/release.json" % n, raw)
        if sign: self.put("sig/cells-%d/release.json.sig" % n, (ed25519.sign(key, raw).hex() + "\n").encode())
        self.tag(n)
        return raw
    def close(self): self.server.shutdown(); self.server.server_close(); shutil.rmtree(self.root, ignore_errors=True)

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass

def tree(d):
    out = {}
    for base, _, files in os.walk(d):
        for f in files:
            p = os.path.join(base, f)
            with open(p, "rb") as fh: out[os.path.relpath(p, d)] = fh.read()
    return out

class Update(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="stemseal_upd_"); self.home = os.path.join(self.tmp, "home")
        self.user = os.path.join(self.home, "cells"); os.makedirs(self.user)
        self.outside = os.path.join(self.tmp, "outside"); os.makedirs(self.outside)
        with open(os.path.join(self.outside, "keep.txt"), "w") as f: f.write("x")
        self.site = Site(); self.trusted = {}
        self.patches = [mock.patch.object(hub, "USER_CELLS", self.user), mock.patch.object(hub, "LEDGER", os.path.join(self.home, "ledger.jsonl")),
                        mock.patch.object(hub, "STATE", os.path.join(self.home, "state.json")), mock.patch.object(update, "TEST_BASE", self.site.base),
                        mock.patch.object(update, "release_keys", lambda: [ed25519.public_key(KEY), ed25519.public_key(SPARE)]),
                        mock.patch.object(update, "trusted_releases", lambda: dict(self.trusted))]
        for p in self.patches: p.start()
    def tearDown(self):
        for p in self.patches: p.stop()
        self.site.close(); shutil.rmtree(self.tmp, ignore_errors=True)
    def first(self, cells, **k):
        raw = self.site.release(1, cells, **k); self.trusted[1] = seal.sha(raw); return raw
    def installed(self): return sorted(os.path.relpath(os.path.dirname(p), self.user) for p in
                                       (os.path.join(b, "lock.json") for b, _, fs in os.walk(self.user) if "lock.json" in fs and ".replaced" not in b))

    def test_install_then_nothing_new(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}})
        r = update.update()
        self.assertTrue(r["ok"], r); self.assertEqual([c["cell"] for c in r["installed"]], ["double_cell"]); self.assertEqual(r["refused"], [])
        self.assertEqual(hub.call("double_cell", {"x": 3}, caller="t")["result"], {"v": 6})
        self.assertEqual(update.read_state()["last_release"], 1)
        self.assertEqual(update.update()["installed"], [])
        self.assertEqual(update.update(check_only=True)["new"], [])

    def test_names_that_are_not_allowed(self):
        before = tree(self.outside)
        names = ["..", "a/b", "a\\b", "/abs_cell", "C:cell", "Upper_cell", "", "ab", "../outside"]
        self.first({n: {"1.0": cell_files("double_cell")} for n in names if n not in ("", "..", "../outside", "a/b", "/abs_cell")})
        rel = json.loads(self.site.raw[1]); good = rel["cells"]["Upper_cell"]
        for n in names: rel["cells"][n] = good
        raw = j(rel); self.site.raw[1] = raw; self.site.put("cells-1/release.json", raw)
        self.site.put("sig/cells-1/release.json.sig", ed25519.sign(KEY, raw).hex().encode()); self.trusted[1] = seal.sha(raw)
        r = update.update()
        self.assertTrue(r["ok"], r); self.assertEqual(r["installed"], [])
        self.assertEqual(sorted(x["cell"] for x in r["refused"]), sorted(n[:64] for n in names))
        self.assertEqual(tree(self.outside), before); self.assertEqual(self.installed(), [])

    def test_versions_that_are_not_allowed(self):
        f = cell_files("double_cell")
        self.first({"double_cell": {"1.0": f, "../1": f, "1": f, "1.0.0": f, "x.y": f, "12345.0": f}})
        r = update.update()
        self.assertEqual([c["version"] for c in r["installed"]], ["1.0"])
        self.assertEqual(sorted(x["version"] for x in r["refused"]), sorted(["../1", "1", "1.0.0", "x.y", "12345.0"]))

    def test_files_that_do_not_hold(self):
        good = cell_files("good_cell")
        cells = {"good_cell": {"1.0": good}, "hash_cell": {"1.0": cell_files("hash_cell")}, "lock_cell": {"1.0": cell_files("lock_cell")},
                 "name_cell": {"1.0": dict(cell_files("name_cell"), **{"run.sh": b"x"})}, "big_cell": {"1.0": cell_files("big_cell", gt=GT + [{"input": {"x": 1}, "expected": {"v": 2}, "pad": "x" * update.MAX_FILE}])},
                 "other_lock": {"1.0": dict(cell_files("other_lock"), **{"lock.json": cell_files("lock_cell")["lock.json"]})}}
        self.first(cells)
        self.site.put("cells-1/hash_cell/1.0/cell.py", b"# changed\n" + SRC.encode())
        lk = json.loads(cells["lock_cell"]["1.0"]["lock.json"]); lk["files"]["gt_cases.json"] = "0" * 64
        rel = json.loads(self.site.raw[1]); rel["cells"]["lock_cell"]["1.0"]["files"]["lock.json"] = seal.sha(j(lk))
        self.site.put("cells-1/lock_cell/1.0/lock.json", j(lk))
        raw = j(rel); self.site.put("cells-1/release.json", raw); self.site.put("sig/cells-1/release.json.sig", ed25519.sign(KEY, raw).hex().encode()); self.trusted[1] = seal.sha(raw)
        r = update.update()
        self.assertEqual([c["cell"] for c in r["installed"]], ["good_cell"])
        why = {x["cell"]: x["reason"] for x in r["refused"]}
        self.assertEqual(set(why), {"hash_cell", "lock_cell", "name_cell", "big_cell", "other_lock"})
        self.assertIn("does not match the release", why["hash_cell"]); self.assertIn("lock", why["lock_cell"])
        self.assertEqual(why["name_cell"], "file list is not in order"); self.assertIn("larger than allowed", why["big_cell"])
        self.assertIn("lock", why["other_lock"])
        self.assertEqual(self.installed(), [os.path.join("good_cell", "1.0")])
        self.assertEqual([n for n in os.listdir(self.user) if n.startswith(".incoming_")], [])

    def test_release_order(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}})
        self.site.release(2, {"double_cell": {"1.0": cell_files("double_cell")}})
        self.assertTrue(update.update()["ok"]); self.assertEqual(update.read_state()["last_release"], 2)
        self.site.tags = []; self.site.tag(1)                      # the newest tag the server shows is older than the one taken
        r = update.update(); self.assertFalse(r["ok"]); self.assertIn("older", r["reason"])

    def test_release_number_must_match_its_tag(self):
        self.site.release(1, {"double_cell": {"1.0": cell_files("double_cell")}}, release_no=2)
        self.trusted[1] = seal.sha(self.site.raw[1])
        r = update.update(); self.assertFalse(r["ok"]); self.assertIn("not cells-1", r["reason"])

    def test_trusted_hash_and_chain(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}})
        self.trusted[1] = "0" * 64
        r = update.update(); self.assertFalse(r["ok"]); self.assertIn("not the release this version knows", r["reason"])
        self.trusted[1] = seal.sha(self.site.raw[1])
        self.site.release(2, {"double_cell": {"1.0": cell_files("double_cell")}})
        self.site.release(3, {"triple_cell": {"1.0": cell_files("triple_cell")}})
        r = update.update(); self.assertTrue(r["ok"], r); self.assertEqual(r["release"], 3)
        self.site.release(4, {"double_cell": {"1.0": cell_files("double_cell")}}, extra={"previous_index_sha256": "1" * 64})
        r = update.update(); self.assertFalse(r["ok"]); self.assertIn("does not hold", r["reason"])
        self.site.release(5, {"double_cell": {"1.0": cell_files("double_cell")}}, previous=False)
        r = update.update(); self.assertFalse(r["ok"]); self.assertIn("do not link", r["reason"])

    def test_withdrawn_cells(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}, "triple_cell": {"1.0": cell_files("triple_cell")}})
        self.assertEqual(len(update.update()["installed"]), 2)
        self.site.release(2, {"double_cell": {"1.0": cell_files("double_cell")}, "quad_cell": {"1.0": cell_files("quad_cell")}},
                          revoked=[{"cell": "double_cell", "version": "1.0", "reason": "wrong"}, {"cell": "quad_cell", "version": "1.0", "reason": "wrong"}])
        r = update.update(); self.assertEqual(r["installed"], [])
        self.assertEqual(hub.call("double_cell", {"x": 1}, caller="t")["reason"], "this cell was withdrawn")
        self.assertNotIn("double_cell", [c["cell"] for c in hub.list_cells()])
        self.assertEqual(hub.call("triple_cell", {"x": 1}, caller="t")["status"], "ok")

    def test_only_sealed_tier(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}}, tier="community")
        r = update.update(); self.assertEqual(r["installed"], []); self.assertEqual(r["refused"][0]["reason"], "not a sealed cell")

    def test_download_cut_leaves_nothing(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}})
        os.remove(os.path.join(self.site.root, "cells-1", "double_cell", "1.0", "gt_cases.json"))
        r = update.update(); self.assertIn("download failed", r["refused"][0]["reason"])
        self.assertEqual(os.listdir(self.user), [])

    def test_checker_and_ground_truth_gates(self):
        self.first({"import_cell": {"1.0": cell_files("import_cell", src="import os\n" + SRC)},
                    "wrong_cell": {"1.0": cell_files("wrong_cell", gt=GT[:-1] + [{"input": {"x": 1}, "expected": {"v": 3}}])},
                    "few_cell": {"1.0": cell_files("few_cell", gt=GT[:5])}})
        ran = []; real = hub._run_runner
        def watch(req, timeout): ran.append(req["mode"]); return real(req, timeout)
        with mock.patch.object(hub, "_run_runner", watch): r = update.update()
        self.assertEqual(r["installed"], []); self.assertEqual(self.installed(), [])
        why = {x["cell"]: x["reason"] for x in r["refused"]}
        self.assertTrue(why["import_cell"].startswith("policy gate")); self.assertTrue(why["wrong_cell"].startswith("ground-truth gate"))
        self.assertTrue(why["few_cell"].startswith("ground-truth gate"))
        self.assertTrue(ran) # every run of a downloaded cell went through the runner (checker, watch and limits)

    def test_signatures(self):
        cells = {"double_cell": {"1.0": cell_files("double_cell")}}
        self.first(cells, sign=False)
        r = update.update(); self.assertFalse(r["ok"]); self.assertIn("no signature", r["reason"])
        self.site.put("sig/cells-1/release.json.sig", b"not a signature")
        r = update.update(); self.assertFalse(r["ok"]); self.assertIn("not signed", r["reason"])
        self.site.put("sig/cells-1/release.json.sig", ed25519.sign(OTHER, self.site.raw[1]).hex().encode())
        self.assertFalse(update.update()["ok"])
        self.site.put("sig/cells-1/release.json.sig", ed25519.sign(KEY, self.site.raw[1] + b" ").hex().encode())
        self.assertFalse(update.update()["ok"])
        self.site.put("sig/cells-1/release.json.sig", ed25519.sign(SPARE, self.site.raw[1]))      # the spare key, raw bytes
        r = update.update(); self.assertTrue(r["ok"], r); self.assertEqual(len(r["installed"]), 1)

    def test_no_release_key_takes_nothing(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}})
        with mock.patch.object(update, "release_keys", lambda: []): r = update.update()
        self.assertFalse(r["ok"]); self.assertIn("no release key", r["reason"]); self.assertEqual(os.listdir(self.user), [])

    def test_no_way_back_to_the_old_index(self):
        """Without a valid release.json nothing is installed, even with an old-format index.json beside it."""
        self.site.put("cells-1/index.json", j({"format": 1, "cells": {"double_cell": {"1.0": {"sha256": seal.sha(SRC.encode())}}}}))
        for f, d in cell_files("double_cell").items(): self.site.put("cells-1/double_cell/1.0/" + f, d)
        self.site.tag(1)
        r = update.update(); self.assertFalse(r["ok"]); self.assertIn("release.json", r["reason"]); self.assertEqual(os.listdir(self.user), [])
        self.assertFalse(hasattr(update, "RAW") and "main" in update.RAW)

    def test_newer_client_needed(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}}, min_client="99.0")
        r = update.update(); self.assertFalse(r["ok"]); self.assertIn("update stemseal", r["reason"])

    def test_old_lock_installed_by_update_is_replaced_not_deleted(self):
        old = cell_files("double_cell", fmt=1); d = os.path.join(self.user, "double_cell", "1.0"); os.makedirs(d)
        for f, data in old.items():
            with open(os.path.join(d, f), "wb") as fh: fh.write(data)
        hub._log({"type": "update", "cell": "double_cell", "version": "1.0", "sha256": seal.sha(old["cell.py"])})
        self.first({"double_cell": {"1.0": cell_files("double_cell")}})
        r = update.update(); self.assertEqual(len(r["installed"]), 1)
        self.assertEqual(hub.call("double_cell", {"x": 2}, caller="t")["result"], {"v": 4})
        self.assertEqual(len(os.listdir(os.path.join(self.user, ".replaced"))), 1)

    def test_test_server_is_announced(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}})
        self.assertIn("STEMSEAL_TEST_RELEASE_BASE", update.update()["warning"])

class BuildRelease(unittest.TestCase):
    def test_release_file_and_trusted_list(self):
        base = tempfile.mkdtemp(prefix="stemseal_rel_")
        shutil.copytree(hub.CELLS, os.path.join(base, "cells")); cells = os.path.join(base, "cells")
        with open(os.path.join(cells, "trusted_releases.json"), "w") as f: f.write("{}")
        rel, digest = update.build_release(1, base=cells)
        self.assertEqual((rel["format"], rel["release"], rel["previous_index_sha256"]), (2, 1, None))
        with open(os.path.join(cells, "release.json"), "rb") as f: self.assertEqual(seal.sha(f.read()), digest)
        rel2, digest2 = update.build_release(2, base=cells, revoke=[{"cell": "x", "version": "1.0", "reason": "r"}])
        self.assertEqual(rel2["previous_index_sha256"], digest)
        rel3, _ = update.build_release(3, base=cells)
        self.assertEqual(rel3["revoked"], [{"cell": "x", "version": "1.0", "reason": "r"}])
        with open(os.path.join(cells, "trusted_releases.json")) as f: self.assertEqual(set(json.load(f)), {"1", "2", "3"})
        for name, vers in rel["cells"].items():
            for v, meta in vers.items():
                self.assertEqual(meta["tier"], "sealed"); self.assertTrue(set(update.NEEDED) <= set(meta["files"]))

    def test_shipped_release_keys_hold_no_secret(self):
        with open(os.path.join(update.PKG, "release_keys.json"), encoding="utf-8") as f: keys = json.load(f)
        self.assertEqual(set(keys), {"keys"})
        for k in keys["keys"]: self.assertRegex(k, r"^[0-9a-f]{64}$")

if __name__ == "__main__":
    unittest.main()
