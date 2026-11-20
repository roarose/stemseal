# -*- coding: utf-8 -*-
"""The cell policy (stemseal/policy.py): every shipped cell is allowed, and each kind of thing outside the lists is refused.
Run: python -m unittest discover -s tests"""
import ast, glob, os, sys, unittest
import builtins as _builtins
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from stemseal import policy

CELL = "def cell_executor(input_data):\n    return {'x': 1}\n"
def cell(body, head=""):
    """A cell whose cell_executor body is `body` (one or more lines), with `head` at the top of the module."""
    lines = "\n".join("    " + l for l in body.strip("\n").split("\n"))
    return head + ("\n" if head and not head.endswith("\n") else "") + "def cell_executor(input_data):\n" + lines + "\n    return {'x': 1}\n"
def codes(src): return [p.code for p in policy.check(src)]
def read(path):
    with open(path, encoding="utf-8") as f: return f.read()

class ShippedCells(unittest.TestCase):
    def test_every_shipped_cell_is_allowed(self):
        files = sorted(glob.glob(os.path.join(ROOT, "stemseal", "cells", "*", "*", "cell.py")))
        self.assertTrue(files)
        for f in files:
            with self.subTest(cell=os.path.relpath(f, ROOT)):
                self.assertEqual([policy.describe(p) for p in policy.check(read(f))], [])

    def test_imports_of_lists_top_level_allowed_modules(self):
        src = "import re\nfrom decimal import Decimal\nimport math\n" + CELL
        self.assertEqual(policy.imports_of(src), ["re", "decimal", "math"])

class Allowed(unittest.TestCase):
    def test_minimal_cell(self): self.assertEqual(policy.check(CELL), [])

    def test_each_module_name_can_be_used_both_ways(self):
        for m, names in policy.MODULES.items():
            for n in names:
                with self.subTest(name="%s.%s" % (m, n)):
                    self.assertEqual(codes(cell("y = %s.%s" % (m, n), "import %s" % m)), [])
                    self.assertEqual(codes(cell("y = %s" % n, "from %s import %s" % (m, n))), [])

    def test_each_builtin(self):
        for n in policy.BUILTINS:
            with self.subTest(name=n): self.assertEqual(codes(cell("y = %s" % n)), [])

    def test_each_attribute(self):
        for n in policy.ATTRIBUTES:
            with self.subTest(name=n): self.assertEqual(codes(cell("y = input_data.%s" % n)), [])

    def test_single_underscore_names_the_cell_defines(self):
        self.assertEqual(codes(cell("return _helper(input_data)", "_TABLE = {'a': 1}\ndef _helper(x):\n    return {'v': _TABLE.get('a')}")), [])

    def test_exception_class(self):
        self.assertEqual(codes("class Ask(Exception):\n    pass\n" + CELL), [])
        self.assertEqual(codes('class Ask(ValueError):\n    """why"""\n' + CELL), [])

    def test_common_syntax(self):
        body = """
a, *b = [1, 2, 3]
c = {k: v for k, v in zip(b, b)}
d = [x for x in range(3) if x] + list(x for x in b)
e = {x for x in d}
f = (lambda q: q + 1)(2) if a else -1
g = f"{a:,} {f!r}" + "%05.2f" % 1.5
while a < 3:
    a += 1
    if a == 2: continue
    break
try:
    h = 1 / 0
except (ZeroDivisionError, ValueError) as err:
    h = str(err)
assert a
i = d[1:2], c.get(1), input_data["k"]
"""
        self.assertEqual(codes(cell(body)), [])

    def test_annotations(self):
        self.assertEqual(codes("def cell_executor(input_data: dict) -> dict:\n    return {}\n"), [])

class Refused(unittest.TestCase):
    def assertRefused(self, src, code):
        got = codes(src)
        self.assertIn(code, got, "expected %s, got %s for:\n%s" % (code, got, src))

    def test_modules_outside_the_list(self):
        for m in ("os", "sys", "io", "socket", "subprocess", "importlib", "random", "time", "datetime", "pathlib", "ctypes", "builtins", "heapq"):
            with self.subTest(module=m):
                self.assertRefused(cell("pass", "import %s" % m), "E_IMPORT")
                self.assertRefused(cell("pass", "from %s import x" % m), "E_IMPORT")

    def test_import_forms(self):
        self.assertRefused(cell("pass", "import re as r"), "E_IMPORT")
        self.assertRefused(cell("pass", "from re import sub as s"), "E_IMPORT")
        self.assertRefused(cell("pass", "from re import *"), "E_IMPORT")
        self.assertRefused(cell("pass", "from . import re"), "E_IMPORT")
        self.assertRefused(cell("import re"), "E_IMPORT")

    def test_module_names_outside_each_module_list(self):
        """Every public and private name a module really has, minus the allowed ones, is refused (both forms)."""
        for m, names in policy.MODULES.items():
            mod = __import__(m)
            for n in sorted(set(dir(mod)) - set(names)):
                with self.subTest(name="%s.%s" % (m, n)):
                    self.assertTrue(set(codes(cell("y = %s.%s" % (m, n), "import %s" % m))) & {"E_ATTR"})
                    self.assertTrue(set(codes(cell("y = 1", "from %s import %s" % (m, n)))) & {"E_IMPORT"})

    def test_module_used_as_a_value(self):
        for body in ("y = re", "y = [re]", "y = len(re)", "y = re.compile.x", "y = {1: re}", "y = (re)"):
            with self.subTest(body=body): self.assertTrue(set(codes(cell(body, "import re"))) & {"E_ATTR"})

    def test_builtins_outside_the_list(self):
        allowed = set(policy.BUILTINS)
        for n in sorted(set(dir(_builtins)) - allowed):
            with self.subTest(name=n): self.assertRefused(cell("y = %s" % n), "E_NAME")

    def test_replacing_or_rebinding_names(self):
        self.assertRefused(cell("list = 1"), "E_NAME")
        self.assertRefused(cell("re = 1", "import re"), "E_NAME")
        self.assertRefused(cell("Decimal = 1", "from decimal import Decimal"), "E_NAME")

    def test_double_underscore_names(self):
        self.assertRefused(cell("__x = 1"), "E_NAME")
        self.assertRefused(cell("y = __name__"), "E_NAME")
        self.assertRefused("def __helper(x):\n    return x\n" + CELL, "E_NAME")
        self.assertRefused(cell("y = dict(__x=1)"), "E_NAME")

    def test_underscore_attributes(self):
        for a in ("_x", "__class__", "__dict__", "_private", "__globals__"):
            with self.subTest(attr=a): self.assertRefused(cell("y = input_data.%s" % a), "E_ATTR")
        self.assertRefused(cell("return _m._x", "_m = 1"), "E_ATTR")

    def test_attributes_outside_the_list(self):
        for a in ("format", "format_map", "mro", "gi_frame", "gi_code", "f_back", "f_globals", "f_locals", "f_builtins",
                  "tb_frame", "tb_next", "co_code", "cr_frame", "ag_frame", "with_traceback", "args", "fromkeys", "encode", "decode"):
            with self.subTest(attr=a):
                self.assertNotIn(a, policy.ATTRIBUTES)
                self.assertRefused(cell("y = input_data.%s" % a), "E_ATTR")

    def test_setting_attributes(self):
        self.assertRefused(cell("input_data.get = 1"), "E_ATTR")

    def test_syntax_outside_the_list(self):
        cases = {
            "global": cell("global g"), "nonlocal": "def cell_executor(input_data):\n    def f():\n        nonlocal input_data\n    return {}\n",
            "yield": cell("yield 1"), "with": cell("with input_data:\n    pass"), "del": cell("del input_data"),
            "walrus": cell("y = (z := 1)"), "async": "async def f():\n    pass\n" + CELL, "await": "async def f():\n    await f()\n" + CELL,
            "bit and": cell("y = 1 & 2"), "bit or": cell("y = 1 | 2"), "xor": cell("y = 1 ^ 2"), "shift": cell("y = 1 << 2"), "invert": cell("y = ~1"),
            "matmul": cell("y = input_data @ input_data"), "decorator": "def d(f):\n    return f\n@d\n" + CELL,
        }
        for k, src in cases.items():
            with self.subTest(case=k): self.assertTrue(set(codes(src)) & {"E_NODE", "E_SYNTAX"}, (k, codes(src)))

    def test_classes_outside_the_one_form(self):
        cases = ["class A(dict):\n    pass\n", "class A:\n    pass\n", "class A(Exception, ValueError):\n    pass\n",
                 "class A(Exception):\n    def f(self):\n        return 1\n", "class A(Exception):\n    x = 1\n",
                 "class A(Exception, metaclass=type):\n    pass\n"]
        for c in cases:
            with self.subTest(src=c): self.assertTrue(set(codes(c + CELL)) & {"E_CLASS", "E_NAME"})

    def test_entry_point(self):
        self.assertRefused("def run(x):\n    return {}\n", "E_ENTRY")
        self.assertRefused("def cell_executor(a, b):\n    return {}\n", "E_ENTRY")

    def test_size_limits(self):
        self.assertRefused("x = 1\n" * 12000 + CELL, "E_SIZE")
        self.assertRefused("x = '" + "a" * 3000 + "'\n" + CELL, "E_SIZE")
        self.assertRefused("x = " + "(" * 60 + "1" + ")" * 60 + "\n" + CELL, "E_SIZE")
        self.assertRefused("x = " + "-" * 200 + "1\n" + CELL, "E_SIZE")
        self.assertRefused("def cell_executor(input_data):\n    return {\n", "E_SYNTAX")

    def test_precheck_does_not_parse(self):
        """precheck refuses deep nesting and large input from bytes alone, and does not need the source to parse."""
        self.assertEqual(policy.precheck(CELL.encode()), [])
        self.assertTrue(policy.precheck(b"(" * 1000))
        self.assertTrue(policy.precheck(b"x" * (policy.MAX_BYTES + 1)))
        self.assertTrue(policy.precheck(b"\xff\xfe"))
        self.assertTrue(policy.precheck("x"))

    def test_checker_never_raises(self):
        for src in ("", "\x00", "def", CELL * 2, b"\xff", 123):
            with self.subTest(src=repr(src)[:30]):
                self.assertTrue(isinstance(policy.check(src), list))

class Versions(unittest.TestCase):
    """The lists only hold names every supported Python has (CI runs this on 3.9 to 3.13)."""
    SAMPLES = ["", 1, 1.5, [], {}, set(), (), frozenset(), complex(1)]
    def samples(self):
        import re, decimal, fractions, collections
        return self.SAMPLES + [decimal.Decimal(1), fractions.Fraction(1, 2), re.compile("a"), re.match("a", "a"),
                               collections.Counter(), collections.OrderedDict(), collections.defaultdict(int)]

    def test_module_names_exist(self):
        for m, names in policy.MODULES.items():
            mod = __import__(m)
            for n in names:
                with self.subTest(name="%s.%s" % (m, n)): self.assertTrue(hasattr(mod, n))

    def test_builtins_exist(self):
        for n in policy.BUILTINS:
            with self.subTest(name=n): self.assertTrue(hasattr(_builtins, n))

    def test_attributes_exist_on_some_standard_value(self):
        vals = self.samples()
        for a in policy.ATTRIBUTES:
            with self.subTest(attr=a): self.assertTrue(any(hasattr(v, a) for v in vals))

    def test_policy_file_imports_only_the_standard_library(self):
        tree = ast.parse(read(os.path.join(ROOT, "stemseal", "policy.py")))
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import): names |= {a.name for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                self.assertEqual(n.level, 0); names.add(n.module)
        self.assertLessEqual(names, {"ast", "builtins", "collections"})

if __name__ == "__main__":
    unittest.main()
