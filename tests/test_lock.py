# -*- coding: utf-8 -*-
"""Lock format 2 (stemseal/seal.py), re-sealing (stemseal/reseal.py) and the result shape (stemseal/shape.py).
Run: python -m unittest discover -s tests"""
import glob, json, os, shutil, sys, tempfile, unittest
from unittest import mock
os.environ.setdefault("STEMSEAL_HOME", tempfile.mkdtemp(prefix="stemseal_test_"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from stemseal import hub, policy, reseal, seal, shape, update

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
                        mock.patch.object(hub, "LEDGER", os.path.join(self.tmp, "ledger.jsonl")), mock.patch.object(hub, "_TAMPER_SEEN", set())]
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
        idx = {"cells": {"got_cell": {"1.0": {"sha256": sha}}, "own_cell": {"1.0": {"sha256": seal.sha(OK_CELL.encode())}}}}
        self.assertEqual([(n, v) for n, v, _ in update.new_cells(idx)], [("got_cell", "1.0")])

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
        self.assertEqual([x["cell"] for x in dry["resealed"]], ["good_cell"])

        r = reseal.reseal()
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
        r = reseal.reseal(["two_cell", "not_here"])
        self.assertEqual([x["cell"] for x in r["resealed"]], ["two_cell"])
        self.assertEqual([x["cell"] for x in r["skipped"]], ["not_here"])
        self.assertIsNone(self.lock_of("one_cell").get("format"))

    def test_reseal_does_not_touch_shipped_cells(self):
        r = reseal.reseal(["vat_supply_price"])
        self.assertEqual(r["resealed"], []); self.assertEqual(len(r["skipped"]), 1)

class Relock(Place):
    def test_relock_does_not_reissue_a_changed_cell(self):
        self.edit("vat_supply_price/1.0/cell.py", lambda d: d + b"\n")
        self.edit("food_calories/1.0/contract.json", lambda d: d.replace(b'"description"', b'"description" ', 1))
        before = {p: open(p, "rb").read() for p in glob.glob(os.path.join(self.cells, "*", "*", "lock.json"))}
        r = reseal.relock(base=self.cells)
        self.assertFalse(r["ok"]); self.assertFalse(r["written"])
        self.assertEqual([x["cell"] for x in r["failed"]], ["vat_supply_price"])
        self.assertEqual({p: open(p, "rb").read() for p in glob.glob(os.path.join(self.cells, "*", "*", "lock.json"))}, before)

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

    def test_without_schema_only_strings_are_limited(self):
        self.assertIsNone(shape.problem({"k": [[[[[1]]]]], "n": list(range(500))}))
        self.assertIsNotNone(shape.problem({"k": [{"a": "x" * 201}]}))

if __name__ == "__main__":
    unittest.main()
