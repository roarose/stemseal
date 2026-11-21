# -*- coding: utf-8 -*-
"""Lock format 2 (stemseal/seal.py), re-sealing (stemseal/reseal.py) and the result shape (stemseal/shape.py).
Run: python -m unittest discover -s tests"""
import glob, json, os, shutil, subprocess, sys, tempfile, time, unittest
from unittest import mock
os.environ.setdefault("STEMSEAL_HOME", tempfile.mkdtemp(prefix="stemseal_test_"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from stemseal import hub, policy, reseal, seal, shape, state, update

SHIPPED = os.path.join(ROOT, "stemseal", "cells")
OK_CELL = "def cell_executor(input_data):\n    return {\"v\": input_data[\"x\"] * 2}\n"
CONTRACT = {"description": "doubles x", "input_schema": {"required": ["x"], "properties": {"x": "number"}}, "output_keys": ["v"]}
GT = [{"input": {"x": i}, "expected": {"v": i * 2}} for i in range(hub.MIN_GT)]

def b(o): return json.dumps(o, ensure_ascii=False).encode("utf-8")

def make(base, name, version="1.0", src=OK_CELL, contract=None, gt=None, fmt=2):
    """A cell folder with a format 1 or 2 lock that matches its files."""
    d = os.path.join(base, name, version); os.makedirs(d)
    raw = {"cell.py": src.encode("utf-8"), "contract.json": b(contract or CONTRACT), "gt_cases.json": b(GT if gt is None else gt)}
    for f, data in raw.items():
        with open(os.path.join(d, f), "wb") as fh: fh.write(data)
    if fmt == 2: seal.write(d, seal.build(name, version, raw, policy.POLICY_VERSION, 20, 20, "t", "t"))
    else:
        with open(os.path.join(d, "lock.json"), "wb") as fh:
            fh.write(b({"cell": name, "version": version, "sha256": seal.sha(raw["cell.py"]), "gt_total": 20, "gt_passed": 20,
                        "deterministic": True, "locked_at": "t", "locked_by": "t"}))
    return d

class Place(unittest.TestCase):
    """Each test gets its own shipped-cells folder (a copy) and its own user-cells folder and ledger."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="stemseal_lock_")
        self.cells = os.path.join(self.tmp, "shipped"); shutil.copytree(SHIPPED, self.cells)
        self.user = os.path.join(self.tmp, "user"); os.makedirs(self.user)
        self.patches = [mock.patch.object(hub, "CELLS", self.cells), mock.patch.object(hub, "USER_CELLS", self.user),
                        mock.patch.object(hub, "LEDGER", os.path.join(self.tmp, "ledger.jsonl")), mock.patch.object(hub, "_TAMPER_SEEN", set()),
                        mock.patch.object(hub, "STATE", os.path.join(self.tmp, "state.json"))]
        for p in self.patches: p.start()
    def tearDown(self):
        for p in self.patches: p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
    def tampers(self, cell): return [r for r in hub._rows("tamper") if r.get("cell") == cell]
    def edit(self, rel, change):
        p = os.path.join(self.cells, rel)
        with open(p, "rb") as f: data = f.read()
        with open(p, "wb") as f: f.write(change(data))

class ShippedLocks(unittest.TestCase):
    def test_every_shipped_lock_is_format_2_and_matches(self):
        dirs = sorted(os.path.dirname(p) for p in glob.glob(os.path.join(SHIPPED, "*", "*", "lock.json")))
        self.assertGreaterEqual(len(dirs), 15)
        for d in dirs:
            with self.subTest(cell=os.path.relpath(d, SHIPPED)):
                with open(os.path.join(d, "lock.json"), encoding="utf-8") as f: lock = json.load(f)
                self.assertEqual((lock["format"], lock["kind"], lock["policy"]), (2, "cell", policy.POLICY_VERSION))
                self.assertEqual(set(lock["files"]), set(seal.SEALED))
                for f, h in lock["files"].items(): self.assertEqual(seal.sha(seal.read_bytes(d, f)), h)
                self.assertIsNone(seal.problem_all(lock, d, os.path.basename(os.path.dirname(d)), os.path.basename(d)))

    def test_every_shipped_contract_has_an_output_schema_that_fits_its_answers(self):
        for p in sorted(glob.glob(os.path.join(SHIPPED, "*", "*", "contract.json"))):
            with self.subTest(cell=os.path.relpath(p, SHIPPED)):
                with open(p, encoding="utf-8") as f: c = json.load(f)
                self.assertIsNone(shape.schema_problem(c["output_schema"], c["output_keys"]))
                with open(os.path.join(os.path.dirname(p), "gt_cases.json"), encoding="utf-8") as f: gt = json.load(f)
                for case in gt:
                    if "expected" in case: self.assertIsNone(shape.problem(case["expected"], c["output_schema"]))

    def test_shipped_answers_are_unchanged(self):
        """Every shipped cell's newest version answers each of its ground-truth cases with the same bytes as recorded."""
        for name in sorted(os.listdir(SHIPPED)):
            if not os.path.isdir(os.path.join(SHIPPED, name)): continue
            c = hub.load(name)
            with open(os.path.join(c["dir"], "gt_cases.json"), encoding="utf-8") as f: gt = json.load(f)
            for case in gt:
                if "expected" not in case: continue
                with self.subTest(cell=name, input=case["input"]):
                    r = hub.call(name, case["input"], caller="t", log=False)
                    self.assertEqual(r["status"], "ok")
                    self.assertEqual(json.dumps(r["result"], ensure_ascii=False), json.dumps(case["expected"], ensure_ascii=False))

    def test_relock_changes_nothing_on_the_shipped_cells(self):
        r = reseal.relock(dry_run=True, base=SHIPPED)
        self.assertEqual((r["ok"], r["changed"], r["failed"]), (True, [], []))

class Tamper(Place):
    def test_contract_change(self):
        self.edit("vat_supply_price/1.0/contract.json", lambda d: d.replace(b"VAT", b"VAX", 1))
        r = hub.call("vat_supply_price", {"total": 11000}, caller="t")
        self.assertEqual((r["status"], r["reason"]), ("not_available", "cell files do not match the lock (contract.json)"))
        self.assertEqual(len(self.tampers("vat_supply_price")), 1)
        for _ in range(2): hub.find("부가세 포함 금액에서 공급가액", caller="t")
        self.assertNotIn("vat_supply_price", [c["cell"] for c in hub.list_cells()])
        self.assertEqual(len(self.tampers("vat_supply_price")), 2)        # one for the call, one for all the finds
        self.assertEqual(self.tampers("vat_supply_price")[0]["file"], "contract.json")
        self.assertIn("vat_supply_price", hub.verify_all())
        self.assertFalse(hub.verify_all()["vat_supply_price"]["seal_ok"])

    def test_gt_change_fails_verify_only(self):
        self.edit("vat_supply_price/1.0/gt_cases.json", lambda d: d + b" ")
        self.assertEqual(hub.call("vat_supply_price", {"total": 11000}, caller="t")["status"], "ok")
        v = hub.verify_all()["vat_supply_price"]
        self.assertFalse(v["seal_ok"]); self.assertIn("gt_cases.json", v["seal"])

    def test_cell_and_lock_sha_changed_together(self):
        self.edit("vat_supply_price/1.0/cell.py", lambda d: d + b"\n")
        with open(os.path.join(self.cells, "vat_supply_price/1.0/cell.py"), "rb") as f: new = seal.sha(f.read())
        self.edit("vat_supply_price/1.0/lock.json", lambda d: json.dumps(dict(json.loads(d), sha256=new)).encode())
        r = hub.call("vat_supply_price", {"total": 11000}, caller="t")
        self.assertEqual((r["status"], r["reason"]), ("not_available", "cell files do not match the lock (lock.json)"))

    def test_cell_change(self):
        self.edit("vat_supply_price/1.0/cell.py", lambda d: d + b"\n")
        r = hub.call("vat_supply_price", {"total": 11000}, caller="t")
        self.assertEqual(r["reason"], "cell files do not match the lock (cell.py)")

    def test_lock_naming_another_cell(self):
        self.edit("vat_supply_price/1.0/lock.json", lambda d: json.dumps(dict(json.loads(d), cell="other_cell")).encode())
        self.assertEqual(hub.call("vat_supply_price", {"total": 11000}, caller="t")["reason"], "cell files do not match the lock (lock.json)")

    def test_unknown_kind_and_format_are_not_used(self):
        for change in ({"kind": "organ"}, {"kind": None}, {"format": 3}, {"format": "2"}, {"policy": True}):
            with self.subTest(change=change):
                d = os.path.join(self.cells, "vat_supply_price/1.0")
                lock = json.loads(seal.read_bytes(d, "lock.json"))
                self.assertEqual(seal.problem(dict(lock, **change), {}), "lock.json")

    def test_a_cell_lock_must_list_its_files(self):
        lock = json.loads(seal.read_bytes(os.path.join(self.cells, "vat_supply_price/1.0"), "lock.json"))
        for f in seal.SEALED:
            files = {k: v for k, v in lock["files"].items() if k != f}
            self.assertEqual(seal.problem(dict(lock, files=files), {}), "lock.json")
        no_kind = {k: v for k, v in lock.items() if k != "kind"}
        self.assertIsNone(seal.problem(no_kind, {}))

    def test_every_listed_file_is_checked(self):
        d = os.path.join(self.cells, "vat_supply_price/1.0")
        with open(os.path.join(d, "words.json"), "wb") as f: f.write(b"[]")
        lock = json.loads(seal.read_bytes(d, "lock.json")); lock["files"]["words.json"] = seal.sha(b"[]")
        seal.write(d, lock)
        self.assertIsNone(seal.problem_all(lock, d))
        with open(os.path.join(d, "words.json"), "wb") as f: f.write(b"[1]")
        self.assertEqual(seal.problem_all(lock, d), "words.json")
        self.assertFalse(hub.verify_all()["vat_supply_price"]["seal_ok"])
        os.remove(os.path.join(d, "words.json"))
        self.assertEqual(seal.problem_all(lock, d), "words.json")

class OldFormat(Place):
    def test_own_cell_and_updated_cell_are_told_apart(self):
        make(self.user, "own_cell", fmt=1)
        d = make(self.user, "got_cell", fmt=1)
        hub._log({"type": "update", "cell": "got_cell", "version": "1.0", "sha256": seal.sha(seal.read_bytes(d, "cell.py"))})
        own = hub.call("own_cell", {"x": 1}, caller="t"); got = hub.call("got_cell", {"x": 1}, caller="t")
        self.assertEqual((own["status"], own["reason"]), ("not_available", "cell needs re-sealing on this machine"))
        self.assertEqual((got["status"], got["reason"]), ("not_available", "old lock format; run stemseal update"))
        notes = {u["cell"]: u["why"] for u in hub.unsealed()}
        self.assertEqual(notes["own_cell"], "old lock format. If you made this cell yourself, run: stemseal reseal own_cell")
        self.assertEqual(notes["got_cell"], "old lock format; run stemseal update")
        self.assertNotIn("own_cell", [c["cell"] for c in hub.list_cells()])
        self.assertEqual(hub.verify_all()["own_cell"]["seal"], notes["own_cell"])
        self.assertEqual(self.tampers("own_cell"), [])

    def test_update_replaces_a_cell_it_installed_with_an_old_lock(self):
        d = make(self.user, "got_cell", fmt=1); sha = seal.sha(seal.read_bytes(d, "cell.py"))
        hub._log({"type": "update", "cell": "got_cell", "version": "1.0", "sha256": sha})
        make(self.user, "own_cell", fmt=1)
        self.assertEqual((update._have("got_cell", "1.0"), update._have("own_cell", "1.0"), update._have("no_cell", "1.0")), ("replace", "yes", "no"))

class Reseal(Place):
    def lock_of(self, name): return json.loads(seal.read_bytes(os.path.join(self.user, name, "1.0"), "lock.json"))

    def test_reseal(self):
        make(self.user, "good_cell", fmt=1)
        changed = make(self.user, "changed_cell", fmt=1)
        with open(os.path.join(changed, "cell.py"), "a", encoding="utf-8", newline="\n") as f: f.write("\n")
        make(self.user, "import_cell", src="import os\n" + OK_CELL, fmt=1)
        make(self.user, "few_cases", gt=GT[:5], fmt=1)
        make(self.user, "wrong_case", gt=GT[:-1] + [{"input": {"x": 1}, "expected": {"v": 3}}], fmt=1)
        make(self.user, "new_cell", fmt=2)
        before = {p: open(p, "rb").read() for p in glob.glob(os.path.join(self.user, "*", "*", "*"))}

        dry = reseal.reseal(dry_run=True)
        self.assertEqual({p: open(p, "rb").read() for p in glob.glob(os.path.join(self.user, "*", "*", "*"))}, before)
        self.assertEqual(dry["resealed"], [])

        self.assertEqual([x["cell"] for x in dry["plan"]], ["good_cell"])
        no = reseal.reseal()                                       # nothing is written without agreement
        self.assertEqual((no["resealed"], no["confirmed"]), ([], False))
        self.assertEqual({p: open(p, "rb").read() for p in glob.glob(os.path.join(self.user, "*", "*", "*"))}, before)
        r = reseal.reseal(confirm=lambda plan: True)
        self.assertEqual([x["cell"] for x in r["resealed"]], ["good_cell"])
        why = {x["cell"]: x["why"] for x in r["failed"]}
        self.assertEqual(set(why), {"changed_cell", "import_cell", "few_cases", "wrong_case"})
        self.assertIn("changed after locking", why["changed_cell"]); self.assertTrue(why["import_cell"].startswith("checker"))
        self.assertIn("at least %d" % hub.MIN_GT, why["few_cases"]); self.assertTrue(why["wrong_case"].startswith("ground truth"))

        lock = self.lock_of("good_cell")
        self.assertEqual((lock["format"], lock["version"], lock["policy"]), (2, "1.0", policy.POLICY_VERSION))
        self.assertTrue(lock["locked_by"].startswith("reseal on "))
        self.assertTrue(os.path.exists(os.path.join(self.user, "good_cell", "1.0", "lock.v1.json")))
        self.assertEqual(hub.call("good_cell", {"x": 2}, caller="t")["result"], {"v": 4})
        for name in why: self.assertEqual(self.lock_of(name).get("format"), None)
        self.assertEqual(hub.call("changed_cell", {"x": 2}, caller="t")["status"], "not_available")

    def test_reseal_by_name(self):
        make(self.user, "one_cell", fmt=1); make(self.user, "two_cell", fmt=1)
        r = reseal.reseal(["two_cell", "not_here"], confirm=lambda plan: True)
        self.assertEqual([x["cell"] for x in r["resealed"]], ["two_cell"])
        self.assertEqual([x["cell"] for x in r["skipped"]], ["not_here"])
        self.assertIsNone(self.lock_of("one_cell").get("format"))

    def test_reseal_does_not_touch_shipped_cells(self):
        r = reseal.reseal(["vat_supply_price"], confirm=lambda plan: True)
        self.assertEqual(r["resealed"], []); self.assertEqual(len(r["skipped"]), 1)

def make_v1_as_written(base, name, contract, crlf=False, locked_by="t"):
    """A format 1 cell written the way format 1 register wrote it (json.dump, indent=1, ensure_ascii=False); crlf: as on Windows,
    where contract.json and lock.json were written in text mode. cell.py was always written with \n."""
    d = os.path.join(base, name, "1.0"); os.makedirs(d)
    nl = "\r\n" if crlf else "\n"
    def text(o, indent=1): return json.dumps(o, ensure_ascii=False, indent=indent).replace("\n", nl).encode("utf-8")
    with open(os.path.join(d, "cell.py"), "wb") as f: f.write(OK_CELL.encode("utf-8"))
    with open(os.path.join(d, "contract.json"), "wb") as f: f.write(text(contract))
    with open(os.path.join(d, "gt_cases.json"), "wb") as f: f.write(json.dumps(GT, ensure_ascii=False).encode("utf-8"))
    lock = {"cell": name, "version": "1.0", "sha256": seal.sha(OK_CELL.encode("utf-8")), "gt_total": 20, "gt_passed": 20,
            "deterministic": True, "locked_at": "2026-11-18T06:59:09+00:00", "locked_by": locked_by}
    with open(os.path.join(d, "lock.json"), "wb") as f: f.write(text(lock))
    return d

class ResealOnlyFormat1(Place):
    """reseal seals a cell that has only ever had a format 1 lock on this machine, and only after the person agrees."""
    YES = staticmethod(lambda plan: True)
    def sealed_then_changed(self, name):
        r = hub.register(name, OK_CELL, dict(CONTRACT), GT, base=self.user); self.assertTrue(r["locked"])
        d = os.path.join(self.user, name, "1.0")
        with open(os.path.join(d, "contract.json"), "rb") as f: data = f.read()
        with open(os.path.join(d, "contract.json"), "wb") as f: f.write(data.replace(b"doubles x", b"doubles x again"))
        return d, json.loads(seal.read_bytes(d, "lock.json"))
    def put_lock(self, d, lock):
        with open(os.path.join(d, "lock.json"), "wb") as f: f.write(b(lock))
    def files(self): return {p: open(p, "rb").read() for p in glob.glob(os.path.join(self.user, "*", "*", "*"))}

    def test_a_format_2_lock_is_never_taken_for_format_1(self):
        variants = {"no format": lambda L: {k: v for k, v in L.items() if k != "format"},
                    "format 1": lambda L: dict(L, format=1), "format true": lambda L: dict(L, format=True),
                    "format 1.0": lambda L: dict(L, format=1.0), "format text": lambda L: dict(L, format="1"),
                    "extra key": lambda L: dict({k: v for k, v in L.items() if k not in ("format", "kind", "files", "policy")}, note="x")}
        for label, change in variants.items():
            with self.subTest(variant=label):
                name = "v_" + label.replace(" ", "_").replace(".", "_")
                d, lock = self.sealed_then_changed(name); self.put_lock(d, change(lock))
                self.assertEqual(seal.problem(change(lock), {}), "lock.json")
                r = hub.call(name, {"x": 1}, caller="t")
                self.assertEqual(r["reason"], "cell files do not match the lock (lock.json)")
                before = self.files()
                for args in ([name], None):
                    out = reseal.reseal(args, confirm=self.YES)
                    self.assertEqual(out["resealed"], []); self.assertNotIn(name, [x["cell"] for x in out["plan"]])
                self.assertEqual(self.files(), before)
                shutil.rmtree(os.path.join(self.user, name))

    def test_a_version_held_with_format_2_stays_refused_with_a_plain_format_1_lock(self):
        d, lock = self.sealed_then_changed("held_cell")
        self.put_lock(d, {k: v for k, v in lock.items() if k in seal.V1_KEYS})
        self.assertEqual(hub.inspect("held_cell")["seal"], "lock.json")
        self.assertEqual(hub.call("held_cell", {"x": 1}, caller="t")["reason"], "cell files do not match the lock (lock.json)")
        self.assertEqual({u["cell"]: u["why"] for u in hub.unsealed()}["held_cell"], "cell files do not match the lock (lock.json); " + hub.HELD_BEFORE)
        before = self.files()
        for args in (["held_cell"], None):
            out = reseal.reseal(args, confirm=self.YES)
            self.assertEqual(out["resealed"], []); self.assertEqual(out["plan"], [])
            self.assertIn(hub.HELD_BEFORE, {x["cell"]: x["why"] for x in out["failed"]}["held_cell"])
        self.assertEqual(self.files(), before)

    def test_a_cell_update_installed_is_left_to_update(self):
        d = make(self.user, "got_cell", fmt=1)
        hub._log({"type": "update", "cell": "got_cell", "version": "1.0", "sha256": seal.sha(seal.read_bytes(d, "cell.py"))})
        before = self.files()
        for args in (["got_cell"], None):
            out = reseal.reseal(args, confirm=self.YES)
            self.assertEqual(out["resealed"], [])
            self.assertEqual({x["cell"]: x["why"] for x in out["failed"]}["got_cell"], "installed by stemseal update; run: stemseal update")
        self.assertEqual(self.files(), before)

    def test_what_is_shown_before_sealing(self):
        d = make(self.user, "shown_cell", contract=dict(CONTRACT, description="첫 줄 설명\n둘째 줄"), fmt=1)
        seen = []
        out = reseal.reseal(["shown_cell"], confirm=lambda plan: seen.append(plan) or False)
        self.assertEqual((out["resealed"], out["confirmed"]), ([], False)); self.assertIsNone(json.loads(seal.read_bytes(d, "lock.json")).get("format"))
        (x,), = seen
        self.assertEqual((x["cell"], x["version"], x["description"]), ("shown_cell", "1.0", "첫 줄 설명"))
        self.assertEqual(x["files"], {f: seal.sha(seal.read_bytes(d, f)) for f in seal.SEALED})
        out = reseal.reseal(["shown_cell"], confirm=self.YES)
        self.assertEqual(out["resealed"], [{"cell": "shown_cell", "version": "1.0"}])
        self.assertEqual(json.loads(seal.read_bytes(d, "lock.json"))["files"], x["files"])
        self.assertTrue(hub.was_sealed("shown_cell", "1.0"))

    def test_cells_in_the_format_of_the_store_laptop_and_rose_pc(self):
        store = dict(CONTRACT, description="메뉴 주문 합계. 메뉴 이름과 수량으로 합계 금액을 낸다.", when_to_use="손님이 여러 메뉴를 주문했을 때",
                     description_en="Order total from menu names and counts.")
        rose = dict(CONTRACT, description="일일 정산. 주문 목록에 할인과 부가세 규칙을 적용해 합계를 낸다. Daily settlement.")
        d1 = make_v1_as_written(self.user, "store_menu_total", store, crlf=True, locked_by="store laptop (boss 2026-11-20)")
        d2 = make_v1_as_written(self.user, "rose_settlement", rose, crlf=False, locked_by="exp11-demand (boss 2026-11-18)")
        for d in (d1, d2): self.assertEqual(seal.problem(json.loads(seal.read_bytes(d, "lock.json")), {}), seal.OLD)
        self.assertEqual(hub.call("store_menu_total", {"x": 1}, caller="t")["reason"], "cell needs re-sealing on this machine")
        out = reseal.reseal(None, confirm=self.YES)
        self.assertEqual(sorted(x["cell"] for x in out["resealed"]), ["rose_settlement", "store_menu_total"])
        for name, d in (("store_menu_total", d1), ("rose_settlement", d2)):
            self.assertIsNone(seal.problem_all(json.loads(seal.read_bytes(d, "lock.json")), d, name, "1.0"))
            self.assertEqual(hub.call(name, {"x": 3}, caller="t")["result"], {"v": 6})
        self.assertIn(b"\r\n", seal.read_bytes(d1, "lock.v1.json"))

class StateRecord(Place):
    """state.json: kept aside when it cannot be read, the safe side while it cannot, every change kept, the record before the lock."""
    def own(self, name): return make(self.user, name, fmt=1)
    def write_state(self, data):
        with open(hub.STATE, "wb") as f: f.write(data)

    def test_unreadable_record_refuses_reseal_and_is_kept_aside(self):
        for label, data in (("broken", b'{"sealed": {"a/1.0": '), ("wrong form", b'{"sealed": []}'), ("not text", b"\xff\xfe"),
                            ("wrong hash", b'{"sealed": {"a/1.0": "x"}}'), ("folder", None)):
            with self.subTest(state=label):
                shutil.rmtree(self.user); os.makedirs(self.user)
                for n in glob.glob(os.path.join(self.tmp, "state*")):
                    shutil.rmtree(n) if os.path.isdir(n) else os.remove(n)
                if data is None: os.makedirs(hub.STATE)
                else: self.write_state(data)
                d = self.own("own_cell")
                self.assertIsNotNone(hub.state_problem())
                out = reseal.reseal(["own_cell"], confirm=lambda plan: True)
                self.assertEqual(out["resealed"], []); self.assertIn("could not be read", out["failed"][0]["why"])
                self.assertIsNone(json.loads(seal.read_bytes(d, "lock.json")).get("format"))
                r = hub.register("new_cell", OK_CELL, dict(CONTRACT), GT, base=self.user)    # a change keeps the old file aside
                self.assertTrue(r["locked"], r)
                kept = glob.glob(os.path.join(self.tmp, "state.bad-*.json"))
                self.assertEqual(len(kept), 1)
                if data is not None:
                    with open(kept[0], "rb") as f: self.assertEqual(f.read(), data)
                s = json.loads(open(hub.STATE, encoding="utf-8").read())
                self.assertEqual(s["damaged"], os.path.basename(kept[0])); self.assertIn("new_cell/1.0", s["sealed"])
                self.assertIsNotNone(hub.state_problem())                          # still the safe side until the person acts
                self.assertEqual(reseal.reseal(["own_cell"], confirm=lambda plan: True)["resealed"], [])
                self.assertEqual(hub.call("new_cell", {"x": 2}, caller="t")["result"], {"v": 4})
                os.remove(hub.STATE)                                               # the person starts a new record
                self.assertIsNone(hub.state_problem())
                self.assertEqual(reseal.reseal(["own_cell"], confirm=lambda plan: True)["resealed"], [{"cell": "own_cell", "version": "1.0"}])

    def test_changes_at_the_same_time_are_all_kept(self):
        prog = ("import sys; sys.path.insert(0, sys.argv[1]); from stemseal import state\n"
                "for i in range(150): state.change(sys.argv[2], lambda s, i=i: s.setdefault('sealed', {}).__setitem__('%s_%d/1.0' % (sys.argv[3], i), '0' * 64))\n")
        procs = [subprocess.Popen([sys.executable, "-c", prog, ROOT, hub.STATE, tag]) for tag in ("a", "b")]
        self.assertEqual([p.wait(timeout=120) for p in procs], [0, 0])
        s = json.loads(open(hub.STATE, encoding="utf-8").read())
        self.assertEqual(len(s["sealed"]), 300)
        self.assertEqual(glob.glob(os.path.join(self.tmp, ".state_*")) + glob.glob(hub.STATE + ".lock"), [])

    def test_left_over_lock_and_new_files_are_cleared(self):
        old = time.time() - 2 * state.LOCK_STALE
        for p in (hub.STATE + ".lock", os.path.join(self.tmp, ".state_x.tmp")):
            with open(p, "w") as f: f.write("1")
            os.utime(p, (old, old))
        hub.mark_sealed("some_cell", "1.0", "0" * 64)
        self.assertTrue(hub.was_sealed("some_cell", "1.0"))
        self.assertEqual(glob.glob(os.path.join(self.tmp, ".state_*")) + glob.glob(hub.STATE + ".lock"), [])

    def test_a_held_lock_is_waited_for_then_given_up(self):
        with open(hub.STATE + ".lock", "w") as f: f.write("1")
        with mock.patch.object(state, "LOCK_WAIT", 0.2):
            with self.assertRaises(state.Unavailable): hub.mark_sealed("some_cell", "1.0", "0" * 64)
            d = self.own("own_cell")
            out = reseal.reseal(["own_cell"], confirm=lambda plan: True)
            self.assertEqual(out["resealed"], []); self.assertIn("cannot record", out["failed"][0]["why"])
            self.assertIsNone(json.loads(seal.read_bytes(d, "lock.json")).get("format"))
            r = hub.register("new_cell", OK_CELL, dict(CONTRACT), GT, base=self.user)
            self.assertFalse(r["locked"]); self.assertFalse(os.path.exists(os.path.join(self.user, "new_cell", "1.0")))

    def test_the_record_comes_before_the_lock(self):
        d = self.own("own_cell")
        with mock.patch.object(seal, "write", side_effect=OSError("stopped")):
            with self.assertRaises(OSError): reseal.reseal(["own_cell"], confirm=lambda plan: True)
        self.assertTrue(hub.was_sealed("own_cell", "1.0"))
        self.assertIsNone(json.loads(seal.read_bytes(d, "lock.json")).get("format"))
        self.assertEqual(hub.call("own_cell", {"x": 1}, caller="t")["status"], "not_available")
        out = reseal.reseal(["own_cell"], confirm=lambda plan: True)
        self.assertEqual(out["resealed"], []); self.assertIn(hub.HELD_BEFORE, out["failed"][0]["why"])

class DeepResults(Place):
    def test_deep_result_without_schema_is_refused_and_logged(self):
        for depth in (65, 1500, 5000):
            with self.subTest(depth=depth):
                shutil.rmtree(os.path.join(self.user, "deep_cell"), ignore_errors=True)
                src = "def cell_executor(input_data):\n    v = 1\n    for i in range(%d):\n        v = [v]\n    return {\"v\": v}\n" % depth
                make(self.user, "deep_cell", src=src)
                r = hub.call("deep_cell", {"x": 1}, caller="t")
                self.assertEqual((r["status"], r["reason"], r["result"]), ("not_available", "cell returned an unexpected result", None))
        rows = [x for x in hub._rows("call") if x.get("cell") == "deep_cell"]
        self.assertEqual(len(rows), 3); self.assertTrue(all(x["status"] == "not_available" for x in rows))

    def test_results_the_runner_cannot_pass_on(self):
        for body in ("return [1]", "return {\"v\": {1, 2}}", "return {\"v\": \"x\" * (2 * 1024 * 1024)}"):
            with self.subTest(body=body):
                shutil.rmtree(os.path.join(self.user, "form_cell"), ignore_errors=True)
                make(self.user, "form_cell", src="def cell_executor(input_data):\n    %s\n" % body)
                r = hub.call("form_cell", {"x": 1}, caller="t")
                self.assertEqual((r["status"], r["reason"]), ("not_available", "cell returned an unexpected result"))

    def test_nesting_up_to_the_limit_still_passes(self):
        src = "def cell_executor(input_data):\n    v = 1\n    for i in range(%d):\n        v = [v]\n    return {\"v\": v}\n" % (shape.HARD_DEPTH - 1)
        make(self.user, "deep_cell", src=src)
        self.assertEqual(hub.call("deep_cell", {"x": 1}, caller="t")["status"], "ok")

class MinimalLedgerKeys(Place):
    def test_minimal_keeps_only_declared_key_names(self):
        src = "def cell_executor(input_data):\n    return {\"v\": 1, \"홍길동 010-1234\": 2}\n"
        make(self.user, "keys_cell", src=src, contract=dict(CONTRACT, output_schema={"v": "number"}))
        with mock.patch.dict(os.environ, {"STEMSEAL_LOG": "minimal"}):
            r = hub.call("keys_cell", {"x": 1}, caller="t")
            self.assertEqual(r["reason"], "cell returned an unexpected result")
            hub.call("keys_cell", {"김철수 고객": 1}, caller="t")
        with open(hub.LEDGER, encoding="utf-8") as f: text = f.read()
        for word in ("홍길동", "010-", "김철수"): self.assertNotIn(word, text)
        rows = [x for x in hub._rows("call") if x.get("cell") == "keys_cell"]
        self.assertIn("1 other", rows[0]["reason"])
        self.assertEqual((rows[1]["input_keys"], rows[1]["input_other"]), ([], 1))

    def test_full_mode_keeps_input_key_names(self):
        make(self.user, "keys_cell")
        with mock.patch.dict(os.environ, {"STEMSEAL_LOG": "full"}): hub.call("keys_cell", {"y": 1}, caller="t")
        self.assertEqual([x for x in hub._rows("call") if x.get("cell") == "keys_cell"][0]["input_keys"], ["y"])

class Relock(Place):
    def test_relock_does_not_reissue_a_changed_cell(self):
        self.edit("vat_supply_price/1.0/cell.py", lambda d: d + b"\n")
        self.edit("food_calories/1.0/contract.json", lambda d: d.replace(b'"description"', b'"description" ', 1))
        before = {p: open(p, "rb").read() for p in glob.glob(os.path.join(self.cells, "*", "*", "lock.json"))}
        r = reseal.relock(base=self.cells)
        self.assertFalse(r["ok"]); self.assertFalse(r["written"])
        why = {x["cell"]: x["why"] for x in r["failed"]}
        self.assertEqual(sorted(why), ["food_calories", "vat_supply_price"])
        self.assertIn("contract.json", why["food_calories"])
        self.assertEqual({p: open(p, "rb").read() for p in glob.glob(os.path.join(self.cells, "*", "*", "lock.json"))}, before)

    def test_relock_keeps_a_format_2_lock_whose_files_match(self):
        d = os.path.join(self.cells, "vat_supply_price/1.0"); lock = json.loads(seal.read_bytes(d, "lock.json"))
        lock["policy"] = lock["policy"] - 1 if lock["policy"] > 0 else lock["policy"] + 1          # only the policy number differs
        with open(os.path.join(d, "lock.json"), "wb") as f: f.write(seal.dumps(lock))
        r = reseal.relock(base=self.cells)
        self.assertEqual((r["ok"], r["changed"]), (True, [os.path.join("vat_supply_price", "1.0")]))

    def test_relock_refuses_a_lock_that_is_neither_format(self):
        d = os.path.join(self.cells, "vat_supply_price/1.0"); lock = json.loads(seal.read_bytes(d, "lock.json"))
        del lock["format"]
        with open(os.path.join(d, "lock.json"), "wb") as f: f.write(b(lock))
        r = reseal.relock(base=self.cells)
        self.assertFalse(r["ok"]); self.assertEqual([x["cell"] for x in r["failed"]], ["vat_supply_price"])

    def test_relock_from_format_1(self):
        d = os.path.join(self.cells, "vat_supply_price/1.0")
        lock = json.loads(seal.read_bytes(d, "lock.json"))
        old = {k: v for k, v in lock.items() if k not in ("format", "kind", "files", "policy")}
        with open(os.path.join(d, "lock.json"), "wb") as f: f.write(b(old))
        r = reseal.relock(base=self.cells)
        self.assertEqual((r["ok"], r["changed"]), (True, [os.path.join("vat_supply_price", "1.0")]))
        self.assertEqual(seal.read_bytes(d, "lock.json"), seal.dumps(lock))

class Register(Place):
    def test_register_writes_format_2(self):
        r = hub.register("twice_cell", OK_CELL, dict(CONTRACT, output_schema={"v": "number"}), GT, base=self.user)
        self.assertTrue(r["locked"])
        d = os.path.join(self.user, "twice_cell", "1.0"); lock = json.loads(seal.read_bytes(d, "lock.json"))
        self.assertIsNone(seal.problem_all(lock, d, "twice_cell", "1.0"))
        self.assertEqual(hub.call("twice_cell", {"x": 4}, caller="t")["result"], {"v": 8})

    def test_register_refuses_a_bad_schema(self):
        for sch in ({"v": "float"}, {"v": "number", "w": "number"}, {"v": {"list": "number"}}, {}):
            with self.subTest(schema=sch):
                r = hub.register("bad_schema_cell", OK_CELL, dict(CONTRACT, output_schema=sch), GT, base=self.user)
                self.assertFalse(r["locked"]); self.assertIn("output_schema", r["reason"])

    def test_register_refuses_answers_outside_the_schema(self):
        r = hub.register("str_cell", OK_CELL, dict(CONTRACT, output_schema={"v": "string"}), GT, base=self.user)
        self.assertFalse(r["locked"]); self.assertEqual(r["reason"], "ground-truth gate")

class CallShape(Place):
    def cell(self, src, schema):
        make(self.user, "shape_cell", src=src, contract=dict(CONTRACT, output_keys=["v"], **({"output_schema": schema} if schema else {})))
        return hub.call("shape_cell", {"x": 1}, caller="t")

    def test_unexpected_result(self):
        cases = [("return {\"v\": \"x\"}", {"v": "number"}), ("return {\"v\": 1, \"w\": 2}", {"v": "number"}), ("return {}", {"v": "number"}),
                 ("return {\"v\": \"a\" * 201}", None), ("return {\"v\": [[[[1]]]]}", {"v": "list"}), ("return {\"v\": None}", {"v": "number"}),
                 ("return {\"v\": 1}", {"v": "list<number>"})]
        for body, schema in cases:
            with self.subTest(body=body, schema=schema):
                shutil.rmtree(os.path.join(self.user, "shape_cell"), ignore_errors=True)
                r = self.cell("def cell_executor(input_data):\n    %s\n" % body, schema)
                self.assertEqual((r["status"], r["reason"], r["result"]), ("not_available", "cell returned an unexpected result", None))
        rows = [x for x in hub._rows("call") if x.get("cell") == "shape_cell"]
        self.assertTrue(all(x["reason"].startswith("cell returned an unexpected result: ") for x in rows))

    def test_fitting_results(self):
        for body, schema in (("return {\"v\": None}", {"v": "number?"}), ("return {\"v\": [{\"a\": [1]}]}", {"v": "list"}),
                             ("return {\"v\": \"b\"}", {"v": "enum:a,b"}), ("return {\"v\": \"a\" * 200}", None), ("return {\"v\": [1] * 50}", None)):
            with self.subTest(body=body, schema=schema):
                shutil.rmtree(os.path.join(self.user, "shape_cell"), ignore_errors=True)
                self.assertEqual(self.cell("def cell_executor(input_data):\n    %s\n" % body, schema)["status"], "ok")

class Shape(unittest.TestCase):
    def test_types(self):
        fits = [(1, "number"), (1.5, "number"), (1, "integer"), (True, "boolean"), ("x", "string"), ([], "list"), ({}, "object"),
                ("a", "enum:a,b"), (None, "integer?"), (None, "list?"), (None, "enum:a?")]
        misses = [(True, "number"), (True, "integer"), (1.0, "integer"), (1, "boolean"), (1, "string"), ({}, "list"), ([], "object"),
                  ("c", "enum:a,b"), (None, "integer"), (None, "string"), (1, "List"), (1, "int"), (1, "?"), (1, "enum:"), (1, ["number"])]
        for v, t in fits: self.assertIsNone(shape.problem({"k": v}, {"k": t}), (v, t))
        for v, t in misses: self.assertIsNotNone(shape.problem({"k": v}, {"k": t}), (v, t))

    def test_bounds(self):
        S = {"k": "list"}
        self.assertIsNone(shape.problem({"k": [[[1]]]}, S))                          # 4 levels, the result object is the first
        self.assertIsNotNone(shape.problem({"k": [[[[1]]]]}, S))
        self.assertIsNone(shape.problem({"k": [0] * shape.MAX_ITEMS}, S))
        self.assertIsNotNone(shape.problem({"k": [0] * (shape.MAX_ITEMS + 1)}, S))
        self.assertIsNotNone(shape.problem({"k": [{str(i): 0 for i in range(shape.MAX_KEYS + 1)}]}, S))
        self.assertIsNotNone(shape.problem({"k": ["x" * (shape.MAX_STR + 1)]}, S))
        self.assertIsNotNone(shape.problem({"k": [{"x" * (shape.MAX_STR + 1): 1}]}, S))
        self.assertIsNotNone(shape.problem({"k": ["x" * 200] * 90}, S))              # over MAX_BYTES
        self.assertIsNotNone(shape.problem({"k": [float("nan")]}, S))
        self.assertIsNotNone(shape.problem({"k": [(1, 2)]}, S))

    def test_keys_exact(self):
        self.assertIsNotNone(shape.problem({"a": 1}, {"a": "number", "b": "number"}))
        self.assertIsNotNone(shape.problem({"a": 1, "b": 1}, {"a": "number"}))

    def test_without_schema_only_strings_and_nesting_are_limited(self):
        self.assertIsNone(shape.problem({"k": [[[[[1]]]]], "n": list(range(500))}))
        self.assertIsNotNone(shape.problem({"k": [{"a": "x" * 201}]}))
        def nest(n):
            v = 1
            for _ in range(n): v = [v]
            return {"k": v}
        self.assertIsNone(shape.problem(nest(shape.HARD_DEPTH - 1)))
        for n in (shape.HARD_DEPTH, 100000):
            self.assertEqual(shape.problem(nest(n)), "nested deeper than %d levels" % shape.HARD_DEPTH)
        self.assertEqual(shape.problem(nest(100000), {"k": "list"}), "nested deeper than %d levels" % shape.MAX_DEPTH)

    def test_key_names_outside_the_schema_are_not_repeated(self):
        p = shape.problem({"a": 1, "홍길동 010-1234": 2, "x": 3}, {"a": "number", "b": "number"})
        self.assertNotIn("홍길동", p); self.assertNotIn("x'", p); self.assertIn("'b'", p); self.assertIn("2 other", p)

if __name__ == "__main__":
    unittest.main()
