# -*- coding: utf-8 -*-
"""stemseal update from signed cell releases (stemseal/update.py), against a local server in place of GitHub.
Keys are made here for each run and never written to the repository. Run: python -m unittest discover -s tests"""
import functools, hashlib, http.server, io, json, os, shutil, sys, tempfile, threading, unittest
from unittest import mock
from contextlib import redirect_stderr, redirect_stdout
os.environ.setdefault("STEMSEAL_HOME", tempfile.mkdtemp(prefix="stemseal_test_"))
for k in ("NO_PROXY", "no_proxy"): os.environ[k] = ",".join(x for x in (os.environ.get(k), "127.0.0.1", "localhost") if x)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stemseal import ed25519, hub, policy, seal, state, update

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

    def test_record_of_installed_cells_and_release_together(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}})
        hub.mark_sealed("own_cell", "1.0", "0" * 64)
        self.assertTrue(update.update()["ok"])
        s = update.read_state()
        self.assertEqual(s["last_release"], 1); self.assertEqual(set(s["sealed"]), {"own_cell/1.0", "double_cell/1.0"})

    def test_unreadable_record_takes_nothing(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}})
        with open(hub.STATE, "w") as f: f.write("{")
        r = update.update()
        self.assertFalse(r["ok"]); self.assertIn("could not be read", r["reason"]); self.assertEqual(self.installed(), [])
        with open(hub.STATE, "rb") as f: self.assertEqual(f.read(), b"{")

    def test_no_record_no_cell(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}})
        with mock.patch.object(hub, "mark_sealed", side_effect=state.Unavailable("held")):
            r = update.update()
        self.assertEqual(self.installed(), []); self.assertIn("cannot record", r["refused"][0]["reason"])

    def test_folders_that_are_not_cells_are_never_looked_at(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}}); update.update()
        junk = {".replaced/double_cell-1.0-t": cell_files("double_cell"), ".incoming_x": cell_files("double_cell"),
                "Bad-Name/1.0": cell_files("double_cell"), "odd_cell/not_a_version": cell_files("odd_cell"), "x/1.0": cell_files("x")}
        for rel, files in junk.items():
            d = os.path.join(self.user, *rel.split("/")); os.makedirs(d)
            for f, data in files.items():
                with open(os.path.join(d, f), "wb") as fh: fh.write(data)
        self.assertEqual([c["cell"] for c in hub.list_cells() if c["cell"] in ("double_cell", "odd_cell")], ["double_cell"])
        hub.find("double x", caller="t"); hub.verify_all(); hub.unsealed()
        from stemseal import savings; savings._all_baselines()
        for name in (".replaced", ".incoming_x", "Bad-Name", "x", "odd_cell"):
            self.assertEqual(hub.call(name, {"x": 1}, caller="t")["status"], "not_available")
        self.assertEqual(hub.call("double_cell", {"x": 1}, caller="t")["result"], {"v": 2})

    def test_a_0_2_3_machine_takes_its_first_release(self):
        """As on the store laptop: cells that 0.2.3's update installed (format 1 lock), one made there, then cells-1."""
        for name in ("double_cell", "triple_cell"):
            old = cell_files(name, fmt=1); d = os.path.join(self.user, name, "1.0"); os.makedirs(d)
            for f, data in old.items():
                with open(os.path.join(d, f), "wb") as fh: fh.write(data)
            hub._log({"type": "update", "cell": name, "version": "1.0", "sha256": seal.sha(old["cell.py"])})
        own = cell_files("own_cell", fmt=1); d = os.path.join(self.user, "own_cell", "1.0"); os.makedirs(d)
        for f, data in own.items():
            with open(os.path.join(d, f), "wb") as fh: fh.write(data)
        self.assertEqual(hub.call("double_cell", {"x": 1}, caller="t")["reason"], "old lock format; run stemseal update")
        self.first({"double_cell": {"1.0": cell_files("double_cell")}, "triple_cell": {"1.0": cell_files("triple_cell")}})
        r = update.update(); self.assertEqual(sorted(c["cell"] for c in r["installed"]), ["double_cell", "triple_cell"])
        self.assertEqual(sorted(os.listdir(self.user)), ["double_cell", "own_cell", "triple_cell"])
        self.assertEqual(len(os.listdir(update.replaced_dir())), 2)
        self.assertEqual(sorted(c["cell"] for c in hub.list_cells() if c["cell"].endswith("_cell")), ["double_cell", "triple_cell"])
        self.assertTrue(hub.find("double x", caller="t") is not None); hub.verify_all()
        self.assertEqual(hub.call("double_cell", {"x": 2}, caller="t")["result"], {"v": 4})
        self.assertEqual(hub.call("own_cell", {"x": 2}, caller="t")["reason"], "cell needs re-sealing on this machine")
        self.assertEqual(update.update()["installed"], [])

    def test_withdrawals_hold_without_state_and_when_a_release_leaves_them_out(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}, "triple_cell": {"1.0": cell_files("triple_cell")}}); update.update()
        self.site.release(2, {"triple_cell": {"1.0": cell_files("triple_cell")}}, revoked=[{"cell": "double_cell", "version": "1.0", "reason": "wrong"}])
        update.update()
        gone = lambda: hub.call("double_cell", {"x": 1}, caller="t")["reason"]
        self.assertEqual(gone(), "this cell was withdrawn")
        self.site.release(3, {"triple_cell": {"1.0": cell_files("triple_cell")}})                 # leaves the withdrawal out
        self.assertEqual(update.update()["release"], 3); self.assertEqual(gone(), "this cell was withdrawn")
        self.assertIn({"cell": "double_cell", "version": "1.0", "reason": "wrong"}, update.read_state()["revoked"])
        with open(hub.STATE, "w") as f: f.write("{")                                             # broken: the kept copy holds
        self.assertEqual(gone(), "this cell was withdrawn"); self.assertNotIn("double_cell", [c["cell"] for c in hub.list_cells()])
        os.remove(hub.STATE)                                                                       # gone: the kept copy holds
        self.assertEqual(gone(), "this cell was withdrawn")
        self.assertEqual(hub.call("triple_cell", {"x": 1}, caller="t")["result"], {"v": 2})

    def test_without_state_or_copy_update_cells_wait_for_update(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}}); update.update()
        self.site.release(2, {"triple_cell": {"1.0": cell_files("triple_cell")}}, revoked=[{"cell": "double_cell", "version": "1.0", "reason": "wrong"}])
        update.update()
        rp, sp = update._copy_paths(); os.remove(rp); os.remove(hub.STATE)
        self.assertEqual(hub.call("triple_cell", {"x": 1}, caller="t")["reason"], hub.RELEASE_UNKNOWN)
        self.assertEqual(hub.call("double_cell", {"x": 1}, caller="t")["status"], "not_available")
        self.assertNotIn("triple_cell", [c["cell"] for c in hub.list_cells()])
        self.assertIn("vat_supply_price", [c["cell"] for c in hub.list_cells()])                   # shipped cells go on
        self.assertIn("run: stemseal update", {u["cell"]: u["why"] for u in hub.unsealed()}["triple_cell"])
        self.assertTrue(update.update()["ok"])
        self.assertEqual(hub.call("triple_cell", {"x": 1}, caller="t")["result"], {"v": 2})
        self.assertEqual(hub.call("double_cell", {"x": 1}, caller="t")["reason"], "this cell was withdrawn")

    def test_broken_state_and_no_copy_takes_nothing(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}}); update.update()
        rp, _ = update._copy_paths(); os.remove(rp)
        with open(hub.STATE, "w") as f: f.write("{")
        r = update.update(); self.assertFalse(r["ok"]); self.assertIn("could not be read", r["reason"])

    def test_broken_state_with_copy_keeps_the_release_order(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}}); update.update()
        self.site.release(2, {"double_cell": {"1.0": cell_files("double_cell")}}); update.update()
        with open(hub.STATE, "w") as f: f.write("{")
        self.site.tags = [1]; self.site.tag(1); self.site.tags = [1]
        r = update.update(); self.assertFalse(r["ok"]); self.assertIn("older than the one this machine took (cells-2)", r["reason"])

    def test_same_number_other_content_is_refused(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}})
        self.site.release(2, {"double_cell": {"1.0": cell_files("double_cell")}}); self.assertEqual(update.update()["release"], 2)
        self.site.tags.remove(2)
        self.site.release(2, {"triple_cell": {"1.0": cell_files("triple_cell")}})
        r = update.update(); self.assertFalse(r["ok"]); self.assertIn("not the release this machine took under that number", r["reason"])
        self.assertNotIn("triple_cell", self.installed())

    def test_empty_or_odd_tag_list_after_a_release(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}}); update.update()
        self.site.put("refs", b"[]")
        r = update.update(); self.assertFalse(r["ok"]); self.assertIn("this machine took cells-1", r["reason"])
        self.site.put("refs", j({"message": "API rate limit exceeded"}))
        r = update.update(); self.assertFalse(r["ok"]); self.assertIn("not a list", r["reason"])

    def test_an_unsigned_newer_tag_is_skipped(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}})
        self.site.release(99, {"triple_cell": {"1.0": cell_files("triple_cell")}}, sign=False)
        r = update.update(); self.assertTrue(r["ok"], r); self.assertEqual(r["release"], 1)
        self.assertEqual(r["skipped"], [{"release": 99, "reason": "cells-99 has no signature"}])
        self.assertEqual(self.installed(), [os.path.join("double_cell", "1.0")])
        self.assertEqual(update.warnings(r), ["cells-99 was not taken (cells-99 has no signature); took cells-1"])
        from stemseal import cli
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()): cli.main(["update"])
        self.assertIn("warning: cells-99 was not taken", err.getvalue())

    @unittest.skipIf(os.name == "nt" or not hasattr(os, "geteuid") or os.geteuid() == 0, "file modes are not enforced here")
    def test_state_without_read_permission_does_not_slow_calls(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}}); update.update()
        os.chmod(hub.STATE, 0)
        try:
            import time
            t = time.time(); [hub.call("vat_supply_price", {"price": 1100}, caller="t") for _ in range(3)]
            self.assertLess(time.time() - t, 2.0)
        finally: os.chmod(hub.STATE, 0o600)

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
        r = update.update(); self.assertTrue(r["ok"], r); self.assertEqual(r["release"], 3)       # the newest that checks
        self.assertIn("does not hold", r["skipped"][0]["reason"])
        self.site.release(5, {"double_cell": {"1.0": cell_files("double_cell")}}, previous=False)
        r = update.update(); self.assertEqual(r["release"], 3); self.assertEqual([x["release"] for x in r["skipped"]], [5, 4])
        self.assertIn("do not link", r["skipped"][0]["reason"])

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
        self.assertEqual(len(os.listdir(update.replaced_dir())), 1)
        self.assertEqual(sorted(os.listdir(self.user)), ["double_cell"])                 # nothing else in the cells folder

    def test_test_server_is_announced(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}})
        self.assertIn("STEMSEAL_TEST_RELEASE_BASE", update.update()["warning"])

PUB, SPUB = (ed25519.public_key(k).hex() for k in (KEY, SPARE))

class KeysWithdrawn(unittest.TestCase):
    """A signed release may withdraw release keys (revoked_keys). Withdrawals only add up; a key that withdraws the other and
    is withdrawn by it leaves no key, and updates stop until a new stemseal version brings new keys."""
    setUp, tearDown, first, installed = Update.setUp, Update.tearDown, Update.first, Update.installed

    def test_a_release_by_the_spare_key_withdraws_the_main_key(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}}); update.update()
        self.site.release(2, {"triple_cell": {"1.0": cell_files("triple_cell")}}, key=SPARE, extra={"revoked_keys": [PUB]})
        r = update.update()
        self.assertTrue(r["ok"], r); self.assertEqual(r["keys_withdrawn"], [PUB]); self.assertEqual(r["release"], 2)
        self.assertEqual(hub.call("triple_cell", {"x": 1}, caller="t")["result"], {"v": 2})
        self.assertEqual(hub.call("double_cell", {"x": 1}, caller="t")["reason"], "this cell was withdrawn")  # signed by the main key
        self.assertNotIn("double_cell", [c["cell"] for c in hub.list_cells()])
        self.site.release(3, {"quad_cell": {"1.0": cell_files("quad_cell")}}, key=KEY)                     # the main key again
        r = update.update()
        self.assertEqual(r["release"], 2); self.assertEqual(r["skipped"][0]["release"], 3)
        self.assertIn("withdrawn release key", r["skipped"][0]["reason"]); self.assertNotIn("quad_cell", self.installed())
        self.assertEqual(update.read_state()["revoked_keys"], [PUB])
        self.assertIn("release key %s was withdrawn by a signed release" % PUB[:16], update.warnings({"keys_withdrawn": [PUB]}))

    def test_keys_that_withdraw_each_other_leave_no_key(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}}); update.update()
        self.site.release(2, {"triple_cell": {"1.0": cell_files("triple_cell")}}, key=KEY, extra={"revoked_keys": [SPUB]})
        self.assertTrue(update.update()["ok"])                       # this machine took the first one out
        self.assertEqual(hub.call("triple_cell", {"x": 1}, caller="t")["result"], {"v": 2})
        self.site.release(3, {}, key=SPARE, extra={"revoked_keys": [PUB]})
        r = update.update()
        self.assertFalse(r["ok"]); self.assertEqual(r["reason"], update.ALL_KEYS_OUT)
        for name in ("double_cell", "triple_cell"): self.assertEqual(hub.call(name, {"x": 1}, caller="t")["reason"], "this cell was withdrawn")
        self.assertIn("vat_supply_price", [c["cell"] for c in hub.list_cells()])                       # shipped cells go on
        self.site.release(4, {"quad_cell": {"1.0": cell_files("quad_cell")}}, key=KEY)
        self.assertEqual(update.update()["reason"], update.ALL_KEYS_OUT)

    def test_both_withdrawals_arriving_together_leave_no_key(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}})
        self.site.release(2, {"triple_cell": {"1.0": cell_files("triple_cell")}}, key=SPARE, extra={"revoked_keys": [PUB]})
        self.site.release(3, {"quad_cell": {"1.0": cell_files("quad_cell")}}, key=KEY, extra={"revoked_keys": [SPUB]})
        r = update.update()
        self.assertFalse(r["ok"]); self.assertEqual(r["reason"], update.ALL_KEYS_OUT); self.assertEqual(self.installed(), [])
        self.assertEqual(sorted(update.read_state()["revoked_keys"]), sorted([PUB, SPUB]))

    def test_a_release_that_withdraws_its_own_key_is_not_taken(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}}); update.update()
        self.site.release(2, {"triple_cell": {"1.0": cell_files("triple_cell")}}, key=KEY, extra={"revoked_keys": [PUB]})
        r = update.update()                                            # the key is out, and so is what it signed
        self.assertFalse(r["ok"]); self.assertNotIn("triple_cell", self.installed())
        self.assertTrue(all("withdrawn release key" in x["reason"] for x in r["skipped"]))
        self.assertEqual(hub.call("double_cell", {"x": 1}, caller="t")["reason"], "this cell was withdrawn")

    def test_withdrawn_keys_hold_without_state(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}}); update.update()
        self.site.release(2, {"triple_cell": {"1.0": cell_files("triple_cell")}}, key=SPARE, extra={"revoked_keys": [PUB]})
        update.update(); os.remove(hub.STATE)
        self.assertEqual(hub.call("double_cell", {"x": 1}, caller="t")["reason"], "this cell was withdrawn")
        os.remove(update._copy_paths()[0])                             # the kept list alone still holds
        self.assertEqual(hub.call("double_cell", {"x": 1}, caller="t")["reason"], "this cell was withdrawn")

    def test_check_only_records_nothing(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}}); update.update()
        self.site.release(2, {"triple_cell": {"1.0": cell_files("triple_cell")}}, key=SPARE, extra={"revoked_keys": [PUB]})
        r = update.update(check_only=True)
        self.assertEqual(r["keys_withdrawn"], [PUB]); self.assertNotIn("revoked_keys", update.read_state())
        self.assertEqual(hub.call("double_cell", {"x": 1}, caller="t")["result"], {"v": 2})

    def test_odd_key_entries_are_left_out(self):
        self.first({"double_cell": {"1.0": cell_files("double_cell")}}, extra={"revoked_keys": ["xyz", PUB.upper(), 5]})
        r = update.update()
        self.assertTrue(r["ok"], r); self.assertNotIn("keys_withdrawn", r)
        self.assertEqual(hub.call("double_cell", {"x": 1}, caller="t")["result"], {"v": 2})

class BuildReleaseKeys(unittest.TestCase):
    def test_withdrawn_keys_carry_over(self):
        base = tempfile.mkdtemp(prefix="stemseal_rel_")
        shutil.copytree(hub.CELLS, os.path.join(base, "cells")); cells = os.path.join(base, "cells")
        with open(os.path.join(cells, "trusted_releases.json"), "w") as f: f.write("{}")
        with mock.patch.object(update, "release_keys", lambda: [ed25519.public_key(KEY), ed25519.public_key(SPARE)]):
            rel, _ = update.build_release(1, base=cells)
            self.assertNotIn("revoked_keys", rel)
            with self.assertRaises(ValueError): update.build_release(2, base=cells, revoke_keys=[ed25519.public_key(OTHER).hex()])
            with self.assertRaises(ValueError): update.build_release(2, base=cells, revoke_keys=[PUB, SPUB])
            rel, _ = update.build_release(2, base=cells, revoke_keys=[PUB])
            self.assertEqual(rel["revoked_keys"], [PUB])
            with self.assertRaises(ValueError): update.build_release(3, base=cells, revoke_keys=[SPUB])  # the last key
            rel, _ = update.build_release(3, base=cells)
            self.assertEqual(rel["revoked_keys"], [PUB])
        shutil.rmtree(base, ignore_errors=True)

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
        with open(os.path.join(cells, "release.json"), "ab") as f: f.write(b" ")                  # not cells-3 as listed
        with self.assertRaises(ValueError): update.build_release(4, base=cells)
        os.remove(os.path.join(cells, "release.json"))
        with self.assertRaises(ValueError): update.build_release(4, base=cells)
        with open(os.path.join(cells, "trusted_releases.json")) as f: self.assertEqual(set(json.load(f)), {"1", "2", "3"})
        for name, vers in rel["cells"].items():
            for v, meta in vers.items():
                self.assertEqual(meta["tier"], "sealed"); self.assertTrue(set(update.NEEDED) <= set(meta["files"]))

    def test_small_order_keys_are_not_used(self):
        identity = bytes([1]) + bytes(31)
        self.assertTrue(ed25519.small_order(identity)); self.assertTrue(ed25519.small_order(b"\x00" * 31))
        self.assertFalse(ed25519.small_order(ed25519.public_key(KEY)))
        with mock.patch.object(update, "_load_pkg", lambda name, default: {"keys": [identity.hex(), ed25519.public_key(KEY).hex()]}):
            self.assertEqual(update.release_keys(), [ed25519.public_key(KEY)])

    def test_shipped_release_keys_hold_no_secret(self):
        with open(os.path.join(update.PKG, "release_keys.json"), encoding="utf-8") as f: keys = json.load(f)
        self.assertEqual(set(keys), {"keys"})
        for k in keys["keys"]: self.assertRegex(k, r"^[0-9a-f]{64}$")

if __name__ == "__main__":
    unittest.main()
