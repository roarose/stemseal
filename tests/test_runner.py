# -*- coding: utf-8 -*-
"""The cell runner (stemseal/_runner.py): shipped cells give the same results as before, every allowed name works with the
audit hook on, and after the hook is on a cell can do nothing but compute. Run: python -m unittest discover -s tests"""
import glob, json, os, subprocess, sys, tempfile, textwrap, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("STEMSEAL_HOME", tempfile.mkdtemp(prefix="stemseal_test_"))
from stemseal import hub, policy

RUNNER = os.path.join(ROOT, "stemseal", "_runner.py")
def read(path, mode="r"):
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f: return f.read()
def shipped():
    for d in sorted(glob.glob(os.path.join(ROOT, "stemseal", "cells", "*", "*"))):
        if os.path.exists(os.path.join(d, "lock.json")): yield d

# The runner as it was in 0.2.3, kept here only to compare results.
LEGACY = '''import json, sys
src = open(sys.argv[1], encoding="utf-8").read()
ns = {"__name__": "cell"}
exec(compile(src, "cell.py", "exec"), ns)
out = []
for x in json.load(sys.stdin):
    try:
        r = ns["cell_executor"](x)
        json.dumps(r)
        out.append({"ok": isinstance(r, dict), "out": r} if isinstance(r, dict) else {"ok": False, "err": "result is not an object"})
    except Exception as e:
        out.append({"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:200])})
sys.stdout.write(json.dumps(out, ensure_ascii=False))
'''

# Drives the runner's own steps with the policy check switched off, so the audit hook is tested by itself.
# `X` hands the cell objects a real cell could never reach; the hook must stop whatever the cell does with them.
DRIVER = '''import importlib.util, json, sys, os, io, socket, subprocess, importlib
spec = importlib.util.spec_from_file_location("r", sys.argv[1]); r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
policy = r.load_policy()
req = json.loads(sys.stdin.read())
code, ns, _ = r.prepare(policy, req["src"], enforce_policy=False)
ns["X"] = {"os": os, "io": io, "socket": socket, "subprocess": subprocess, "sys": sys, "importlib": importlib, "exec": exec,
           "compile": compile, "load_policy": r.load_policy, "open": open}
state = r.guard(code)
if req.get("one_by_one"):
    exec(code, ns); fn = ns["cell_executor"]; first_bad = None
    for i in range(req["n"]):
        try: fn(i)
        except Exception as e: first_bad = first_bad or [i, "%s: %s" % (type(e).__name__, e)]
        if state[1] is not None: first_bad = [i, "event " + state[1]]; break
        if first_bad: break
    sys.stdout.write(json.dumps({"first_bad": first_bad})); sys.stdout.flush(); os._exit(0)
reply = r.execute(code, ns, req["inputs"], state)
sys.stdout.write(json.dumps(reply)); sys.stdout.flush(); os._exit(0)
'''

def drive(src, inputs=None, **extra):
    d = tempfile.mkdtemp(prefix="stemseal_drv_"); drv = os.path.join(d, "driver.py")
    with open(drv, "w", encoding="utf-8") as f: f.write(DRIVER)
    p = subprocess.run([sys.executable, "-I", "-S", drv, RUNNER], input=json.dumps(dict(src=src, inputs=inputs or [{}], **extra)).encode(),
                       capture_output=True, timeout=60, cwd=d)
    try: return json.loads(p.stdout.decode())
    except ValueError: raise AssertionError("driver failed: %s" % p.stderr.decode()[-2000:])

def run_raw(request, cwd=None, env=None):
    p = subprocess.run([sys.executable, "-I", "-S", "-B", "-X", "utf8", RUNNER], input=request if isinstance(request, bytes) else json.dumps(request).encode(),
                       capture_output=True, timeout=60, cwd=cwd or tempfile.mkdtemp(), env=env or {"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")})
    return p.returncode, json.loads(p.stdout.decode())

def req(src, inputs=None, mode="run"):
    return {"mode": mode, "src": src, "sha256": hub.sha(src), "inputs": inputs if inputs is not None else [{}]}

OK_CELL = "def cell_executor(input_data):\n    return {'v': input_data.get('a', 0) + 1}\n"

class SameResults(unittest.TestCase):
    def test_shipped_cells_give_the_same_results_as_the_old_runner(self):
        tmp = tempfile.mkdtemp(); legacy = os.path.join(tmp, "legacy.py")
        with open(legacy, "w", encoding="utf-8") as f: f.write(LEGACY)
        n = 0
        for d in shipped():
            src = read(os.path.join(d, "cell.py")); inputs = [c["input"] for c in json.loads(read(os.path.join(d, "gt_cases.json")))]
            old = subprocess.run([sys.executable, "-I", "-X", "utf8", legacy, os.path.join(d, "cell.py")], input=json.dumps(inputs, ensure_ascii=False).encode(),
                                 capture_output=True, timeout=120, cwd=d)
            new = hub.run_isolated(src, hub.sha(src), inputs, timeout=120)
            with self.subTest(cell=os.path.relpath(d, ROOT)):
                self.assertEqual(json.dumps(new, ensure_ascii=False, sort_keys=True), json.dumps(json.loads(old.stdout.decode()), ensure_ascii=False, sort_keys=True))
            n += len(inputs)
        self.assertGreater(n, 200)

    def test_verify_passes(self):
        out = hub.verify_all()
        self.assertTrue(out)
        for k, v in out.items():
            with self.subTest(cell=k): self.assertTrue(v["hash_ok"] and v["policy_ok"] and v["deterministic"] and v["gt"].split("/")[0] == v["gt"].split("/")[1], v)

# One example use of every name the policy allows. A name without an example fails the completeness test below.
EXAMPLES = {
 "math": {"floor": "math.floor(1.5)", "ceil": "math.ceil(1.2)", "sqrt": "math.sqrt(2)", "exp": "math.exp(1)", "log": "math.log(2)", "log10": "math.log10(2)",
          "log2": "math.log2(2)", "pow": "math.pow(2, 3)", "fabs": "math.fabs(-1)", "isclose": "math.isclose(1, 1)", "isfinite": "math.isfinite(1)",
          "isnan": "math.isnan(1)", "inf": "math.inf", "nan": "math.nan", "pi": "math.pi", "e": "math.e", "prod": "math.prod([1, 2])",
          "fsum": "math.fsum([0.1, 0.2])", "comb": "math.comb(5, 2)", "perm": "math.perm(5, 2)", "factorial": "math.factorial(5)",
          "gcd": "math.gcd(4, 6)", "trunc": "math.trunc(1.5)"},
 "statistics": {"fmean": "statistics.fmean([1, 2])", "pstdev": "statistics.pstdev([1, 2])", "mean": "statistics.mean([1, 2])",
                "median": "statistics.median([1, 2, 3])", "median_low": "statistics.median_low([1, 2])", "median_high": "statistics.median_high([1, 2])",
                "mode": "statistics.mode([1, 1, 2])", "pvariance": "statistics.pvariance([1, 2])", "stdev": "statistics.stdev([1, 2, 3])",
                "variance": "statistics.variance([1, 2, 3])", "quantiles": "statistics.quantiles([1, 2, 3, 4])",
                "StatisticsError": "statistics.mean([]) if False else statistics.StatisticsError"},
 "decimal": {"Decimal": "decimal.Decimal('1.25')", "ROUND_FLOOR": "decimal.Decimal('1.25').quantize(decimal.Decimal('0.1'), rounding=decimal.ROUND_FLOOR)",
             "ROUND_HALF_UP": "decimal.Decimal('1.25').quantize(decimal.Decimal('0.1'), rounding=decimal.ROUND_HALF_UP)",
             "ROUND_DOWN": "decimal.Decimal('1.25').quantize(decimal.Decimal('0.1'), rounding=decimal.ROUND_DOWN)",
             "ROUND_UP": "decimal.Decimal('1.25').quantize(decimal.Decimal('0.1'), rounding=decimal.ROUND_UP)",
             "ROUND_CEILING": "decimal.Decimal('1.25').quantize(decimal.Decimal('0.1'), rounding=decimal.ROUND_CEILING)",
             "ROUND_HALF_EVEN": "decimal.Decimal('1.25').quantize(decimal.Decimal('0.1'), rounding=decimal.ROUND_HALF_EVEN)",
             "ROUND_HALF_DOWN": "decimal.Decimal('1.25').quantize(decimal.Decimal('0.1'), rounding=decimal.ROUND_HALF_DOWN)",
             "InvalidOperation": "_try(lambda: decimal.Decimal('x'))"},
 "fractions": {"Fraction": "fractions.Fraction(1, 3) + fractions.Fraction('1.5')"},
 "re": {"compile": "re.compile('a', re.I)", "escape": "re.escape('a.b')", "findall": "re.findall('a', 'aa')", "finditer": "list(re.finditer('a', 'aa'))",
        "fullmatch": "re.fullmatch('a', 'a')", "match": "re.match('a', 'a')", "search": "re.search('a', 'ba')", "split": "re.split(',', 'a,b')",
        "sub": "re.sub('a', 'b', 'aa')", "subn": "re.subn('a', 'b', 'aa')", "IGNORECASE": "re.compile('a', re.IGNORECASE).search('A')", "I": "re.I"},
 "collections": {"Counter": "collections.Counter('aab')", "OrderedDict": "collections.OrderedDict(a=1)", "defaultdict": "collections.defaultdict(int)"},
 "itertools": {"filterfalse": "list(itertools.filterfalse(None, [0, 1]))", "accumulate": "list(itertools.accumulate([1, 2]))",
               "chain": "list(itertools.chain([1], [2]))", "combinations": "list(itertools.combinations([1, 2, 3], 2))",
               "groupby": "[k for k, g in itertools.groupby('aab')]", "islice": "list(itertools.islice(range(5), 2))",
               "permutations": "list(itertools.permutations([1, 2]))", "product": "list(itertools.product([1], [2]))",
               "zip_longest": "list(itertools.zip_longest([1], [2, 3]))"},
 "functools": {"reduce": "functools.reduce(lambda a, b: a + b, [1, 2])"},
 "json": {"dumps": "json.dumps({'a': [1, 2.5, '한글']})", "loads": "json.loads('{\"a\": 1}')"},
}
BUILTIN_EXAMPLES = {
 "Exception": "_try(lambda: _raise(Exception('x')))", "ValueError": "_try(lambda: int('x'))", "ZeroDivisionError": "_try(lambda: 1 / 0)",
 "KeyError": "_try(lambda: {}['k'])", "TypeError": "_try(lambda: 1 + 'a')", "IndexError": "_try(lambda: [][1])",
 "ArithmeticError": "_try(lambda: _raise(ArithmeticError('x')))", "OverflowError": "_try(lambda: 10.0 ** 400)",
 "all": "all([1])", "any": "any([0])", "abs": "abs(-1)", "bool": "bool(1)", "chr": "chr(65)", "dict": "dict(a=1)", "divmod": "divmod(7, 2)",
 "enumerate": "list(enumerate('ab'))", "filter": "list(filter(None, [0, 1]))", "float": "float('1e3')", "frozenset": "frozenset([1])",
 "int": "int('12')", "isinstance": "isinstance(1, int)", "len": "len('ab')", "list": "list('ab')", "map": "list(map(int, '12'))",
 "max": "max(1, 2)", "min": "min(1, 2)", "ord": "ord('a')", "pow": "pow(2, 3, 5)", "range": "list(range(3))", "reversed": "list(reversed([1, 2]))",
 "round": "round(2.675, 2)", "set": "set([1])", "sorted": "sorted({'b': 1, 'a': 2})", "str": "str(1.5)", "sum": "sum([1, 2])",
 "tuple": "tuple([1])", "zip": "list(zip([1], [2]))", "True": "True", "False": "False", "None": "None",
}
ATTRIBUTE_EXAMPLES = {
 "add": "set().add(1)", "append": "[].append(1)", "count": "'aa'.count('a')", "denominator": "fractions.Fraction(1, 3).denominator",
 "end": "re.match('a', 'a').end()", "endswith": "'ab'.endswith('b')", "find": "'ab'.find('b')", "finditer": "list(re.compile('a').finditer('aa'))",
 "fullmatch": "re.compile('a').fullmatch('a')", "get": "{}.get(1)", "group": "re.match('a', 'a').group(0)", "is_finite": "decimal.Decimal(1).is_finite()",
 "isdigit": "'1'.isdigit()", "isspace": "' '.isspace()", "items": "list({1: 2}.items())", "join": "','.join('ab')", "lower": "'A'.lower()",
 "match": "re.compile('a').match('a')", "pop": "[1].pop()", "quantize": "decimal.Decimal('1.25').quantize(decimal.Decimal('0.1'))",
 "replace": "'a'.replace('a', 'b')", "rstrip": "'a '.rstrip()", "setdefault": "{}.setdefault(1, 2)", "split": "'a b'.split()",
 "start": "re.match('a', 'a').start()", "startswith": "'ab'.startswith('a')", "strip": "' a '.strip()", "sub": "re.compile('a').sub('b', 'aa')",
 "to_integral_value": "decimal.Decimal('1.5').to_integral_value()", "update": "{}.update({1: 2})", "values": "list({1: 2}.values())",
 "keys": "list({1: 2}.keys())", "extend": "[].extend([1])", "insert": "[].insert(0, 1)", "index": "[1].index(1)", "remove": "[1].remove(1)",
 "sort": "[2, 1].sort()", "reverse": "[1, 2].reverse()", "copy": "[1].copy()", "clear": "[1].clear()", "upper": "'a'.upper()", "lstrip": "' a'.lstrip()",
 "rfind": "'aba'.rfind('a')", "isalpha": "'가'.isalpha()", "isalnum": "'a1'.isalnum()", "isdecimal": "'1'.isdecimal()", "isnumeric": "'½'.isnumeric()",
 "zfill": "'1'.zfill(3)", "ljust": "'a'.ljust(3)", "rjust": "'a'.rjust(3)", "center": "'a'.center(3)", "partition": "'a,b'.partition(',')",
 "rpartition": "'a,b'.rpartition(',')", "splitlines": "'a\\nb'.splitlines()", "title": "'ab'.title()", "numerator": "fractions.Fraction(1, 3).numerator",
 "groups": "re.match('(a)', 'a').groups()", "groupdict": "re.match('(?P<x>a)', 'a').groupdict()", "span": "re.match('a', 'a').span()",
 "most_common": "collections.Counter('aab').most_common(1)", "real": "(1.5).real", "imag": "(1.5).imag", "as_integer_ratio": "(1.5).as_integer_ratio()",
 "is_integer": "(1.0).is_integer()", "limit_denominator": "fractions.Fraction(1, 3).limit_denominator(10)", "normalize": "decimal.Decimal('1.0').normalize()",
 "to_integral": "decimal.Decimal('1.5').to_integral()", "is_nan": "decimal.Decimal(1).is_nan()", "is_zero": "decimal.Decimal(0).is_zero()",
 "is_signed": "decimal.Decimal(-1).is_signed()", "sqrt": "decimal.Decimal(2).sqrt()", "ln": "decimal.Decimal(2).ln()", "log10": "decimal.Decimal(2).log10()",
 "exp": "decimal.Decimal(2).exp()", "adjusted": "decimal.Decimal(100).adjusted()", "search": "re.compile('a').search('ba')",
}

class AllowedNamesUnderTheHook(unittest.TestCase):
    def test_every_allowed_name_has_an_example(self):
        for m, names in policy.MODULES.items(): self.assertEqual(set(names), set(EXAMPLES[m]), m)
        self.assertEqual(set(policy.BUILTINS), set(BUILTIN_EXAMPLES))
        self.assertEqual(set(policy.ATTRIBUTES), set(ATTRIBUTE_EXAMPLES))

    def test_every_allowed_name_works_with_the_hook_on(self):
        """Each example runs in a runner with the hook on; nothing may raise or trigger an event (no late imports, no file access).
        This is where a name that needs a module loaded up front (policy.HIDDEN_DEPS) shows up."""
        exprs = [e for m in EXAMPLES.values() for e in m.values()] + list(BUILTIN_EXAMPLES.values()) + list(ATTRIBUTE_EXAMPLES.values())
        src = ("import " + ", ".join(policy.MODULES) + "\n"
               "def _raise(e):\n    raise e\n"
               "def _try(f):\n    try:\n        f()\n    except Exception as e:\n        return str(e)\n"
               "_E = [" + ", ".join("lambda: (%s)" % e for e in exprs) + "]\n"
               "def cell_executor(i):\n    _E[i]()\n    return {}\n")
        out = drive(src, one_by_one=True, n=len(exprs))
        self.assertIsNone(out["first_bad"], "%s -> %s" % (exprs[out["first_bad"][0]] if out["first_bad"] else "", out["first_bad"]))

    def test_shipped_cells_trigger_no_event(self):
        for d in shipped():
            src = read(os.path.join(d, "cell.py")); inputs = [c["input"] for c in json.loads(read(os.path.join(d, "gt_cases.json")))]
            with self.subTest(cell=os.path.relpath(d, ROOT)):
                self.assertIsNone(drive(src, inputs)["blocked"])

class HookStopsEverythingElse(unittest.TestCase):
    """With the policy check off, a cell is handed real objects; the audit hook must still stop the action and fail the whole batch."""
    def assertBlocked(self, body, marker=None):
        src = "def cell_executor(input_data):\n" + textwrap.indent(textwrap.dedent(body).strip("\n"), "    ") + "\n    return {'done': 1}\n"
        out = drive(src, [{}, {}])
        self.assertTrue(out["blocked"], out)
        self.assertTrue(all(not r["ok"] for r in out["results"]), out)
        if marker: self.assertFalse(os.path.exists(marker))

    def test_open_file(self):
        m = os.path.join(tempfile.mkdtemp(), "marker")
        self.assertBlocked("X['open'](%r, 'w').write('x')" % m, m)
        self.assertBlocked("X['io'].open(%r, 'w').write('x')" % m, m)
    def test_list_folder(self): self.assertBlocked("X['os'].listdir('.')")
    def test_environment(self): self.assertBlocked("X['os'].putenv('A', 'B')")
    def test_command(self): self.assertBlocked("X['os'].system('echo hi')")
    def test_process(self): self.assertBlocked("X['subprocess'].run(['echo', 'hi'])")
    def test_socket(self): self.assertBlocked("X['socket'].create_connection(('127.0.0.1', 9), timeout=1)")
    def test_import(self): self.assertBlocked("X['importlib'].import_module('wave')")
    def test_compile_and_exec(self):
        self.assertBlocked("X['compile']('1', 'x', 'eval')")
        self.assertBlocked("X['exec']('y = 1', {})")
    def test_second_hook(self): self.assertBlocked("X['sys'].addaudithook(lambda *a: None)")
    def test_frame(self): self.assertBlocked("X['sys']._getframe()")
    def test_loading_the_policy_again(self): self.assertBlocked("X['load_policy']()")
    def test_a_caught_refusal_still_fails_the_batch(self):
        self.assertBlocked("try:\n    X['os'].listdir('.')\nexcept Exception:\n    pass")

class RunnerRequests(unittest.TestCase):
    def test_ok(self):
        code, rep = run_raw(req(OK_CELL, [{"a": 1}, {"a": 2}]))
        self.assertEqual(code, 0); self.assertIsNone(rep["blocked"])
        self.assertEqual(rep["results"], [{"ok": True, "out": {"v": 2}}, {"ok": True, "out": {"v": 3}}])

    def test_cell_errors_keep_their_wording(self):
        src = "def cell_executor(input_data):\n    raise ValueError('need a')\n"
        self.assertEqual(run_raw(req(src))[1]["results"], [{"ok": False, "err": "ValueError: need a"}])

    def test_policy_refusal(self):
        src = "import os\n" + OK_CELL
        code, rep = run_raw(req(src, [{}, {}]))
        self.assertEqual(code, 3); self.assertEqual(rep["blocked"], "policy"); self.assertTrue(rep["problems"])
        self.assertEqual([r["ok"] for r in rep["results"]], [False, False])

    def test_hash_mismatch(self):
        r = req(OK_CELL); r["sha256"] = "0" * 64
        self.assertEqual(run_raw(r)[1]["blocked"], "hash")

    def test_request_too_large(self):
        self.assertEqual(run_raw(b"x" * (8 * 1024 * 1024 + 10))[1]["blocked"], "request")

    def test_bad_request(self):
        self.assertEqual(run_raw(b"{not json")[1]["blocked"], "request")

    def test_result_too_large(self):
        src = "def cell_executor(input_data):\n    return {'s': 'a' * 2000000}\n"
        self.assertEqual(run_raw(req(src))[1]["results"], [{"ok": False, "err": "result too large"}])

    def test_result_not_an_object(self):
        src = "def cell_executor(input_data):\n    return 1\n"
        self.assertEqual(run_raw(req(src))[1]["results"], [{"ok": False, "err": "result is not an object"}])

    def test_check_mode_runs_nothing(self):
        src = "def cell_executor(input_data):\n    return {}\nx = 1 / 0\n"
        code, rep = run_raw(req(src, [], mode="check"))
        self.assertEqual(rep["problems"], []); self.assertEqual(rep["results"], [])
        self.assertTrue(run_raw(req("import os\n" + OK_CELL, [], mode="check"))[1]["problems"])

    def test_policy_loads_from_the_runner_folder_only(self):
        """Look-alike files where the runner starts and a hostile PYTHONPATH are ignored; the real policy is used."""
        d = tempfile.mkdtemp(); marker = os.path.join(d, "fake_was_used")
        for name in ("policy.py", "ast.py", "json.py", "hashlib.py", "sitecustomize.py", "usercustomize.py"):
            with open(os.path.join(d, name), "w", encoding="utf-8") as f: f.write("open(%r, 'w').write('x')\n" % marker)
        env = {"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "PYTHONPATH": d, "PYTHONSTARTUP": os.path.join(d, "ast.py"), "PYTHONHOME": ""}
        env = {k: v for k, v in env.items() if v}
        code, rep = run_raw(req(OK_CELL, [{"a": 1}]), cwd=d, env=env)
        self.assertEqual(rep["results"], [{"ok": True, "out": {"v": 2}}])
        self.assertFalse(os.path.exists(marker))
        self.assertTrue(run_raw(req("import os\n" + OK_CELL), cwd=d, env=env)[1]["problems"])
        self.assertFalse(os.path.exists(marker))

class ParentSide(unittest.TestCase):
    def test_parent_does_not_parse_what_precheck_refuses(self):
        self.assertTrue(hub.purity_check("x = " + "(" * 5000 + ")" * 5000 + "\n" + OK_CELL))

    def test_policy_gate_in_a_separate_process(self):
        self.assertEqual(hub.purity_check(OK_CELL), [])
        self.assertTrue(hub.purity_check("import os\n" + OK_CELL))

    def test_run_isolated_marks_refusals(self):
        src = "import os\n" + OK_CELL
        r = hub.run_isolated(src, hub.sha(src), [{}])
        self.assertEqual(r[0]["blocked"], "policy"); self.assertFalse(r[0]["ok"])

    def test_call_answers_not_available_for_a_refused_cell(self):
        d = tempfile.mkdtemp(); base = os.path.join(d, "cells", "bad_cell", "1.0"); os.makedirs(base)
        src = "import os\n" + OK_CELL
        with open(os.path.join(base, "cell.py"), "w", encoding="utf-8") as f: f.write(src)
        with open(os.path.join(base, "contract.json"), "w", encoding="utf-8") as f: json.dump({"description": "x", "input_schema": {}, "output_keys": ["v"]}, f)
        with open(os.path.join(base, "lock.json"), "w", encoding="utf-8") as f: json.dump({"cell": "bad_cell", "version": "1.0", "sha256": hub.sha(src), "gt_total": 20, "locked_at": "x"}, f)
        old = hub.USER_CELLS
        try:
            hub.USER_CELLS = os.path.join(d, "cells")
            r = hub.call("bad_cell", {}, caller="t")
        finally: hub.USER_CELLS = old
        self.assertEqual(r["status"], "not_available"); self.assertEqual(r["reason"], "cell failed the safety check")
        self.assertTrue([x for x in hub._rows("blocked") if x.get("cell") == "bad_cell"])

    def test_register_refuses_before_running(self):
        d = tempfile.mkdtemp(); marker = os.path.join(d, "ran")
        src = "import os\ndef cell_executor(input_data):\n    return {}\n"
        r = hub.register("bad_cell_two", src, {"description": "x", "input_schema": {}, "output_keys": []}, [{"input": {}, "expected": {}}] * 20, base=d)
        self.assertFalse(r["locked"]); self.assertEqual(r["reason"], "purity gate")
        self.assertFalse(os.path.exists(os.path.join(d, "bad_cell_two")))

if __name__ == "__main__":
    unittest.main()
