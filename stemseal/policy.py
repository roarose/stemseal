# -*- coding: utf-8 -*-
"""stemseal - what a cell may contain (policy version 2).

A cell is a small pure calculation. This module lists exactly what one may use, and refuses everything else:
the syntax it may contain, the built-in names, the modules and the names inside each module, and the attribute
names it may read from values. Anything not listed is refused, so the list only ever grows on purpose, with a
new POLICY_VERSION.

Standard library only, and nothing from the stemseal package: the cell runner loads this file by its path
before it reads any cell (see _runner.py).

  precheck(src_bytes)  cheap checks that do not parse the source (size, line length, bracket depth)
  check(src)           the full check; it parses the source, so stemseal only calls it inside the runner process
  imports_of(src)      the allowed modules a cell imports (the runner loads only these, plus HIDDEN_DEPS)
"""
import ast, builtins
from collections import namedtuple

POLICY_VERSION = 2

MAX_BYTES = 64 * 1024
MAX_LINES = 5000
MAX_LINE_CHARS = 2000
MAX_BRACKET_DEPTH = 50
MAX_NODES = 20000
MAX_DEPTH = 50

# ---------------------------------------------------------------- syntax
NODES = frozenset("""
Module FunctionDef Return Pass Expr Assign AugAssign If For While Break Continue Try ExceptHandler Raise Assert ClassDef
BoolOp BinOp UnaryOp Lambda IfExp Dict Set List Tuple ListComp SetComp DictComp GeneratorExp comprehension Compare Call keyword
Constant JoinedStr FormattedValue Attribute Subscript Slice Starred Name Load Store arguments arg alias Import ImportFrom
Add Sub Mult Div FloorDiv Mod Pow USub UAdd Not And Or Eq NotEq Lt LtE Gt GtE In NotIn Is IsNot
Index
""".split())   # Index: Python 3.8-style subscripts; its contents are checked like any other node

# ---------------------------------------------------------------- names
BUILTINS = frozenset("""
Exception ValueError ZeroDivisionError KeyError TypeError IndexError ArithmeticError OverflowError
all any abs bool chr dict divmod enumerate filter float frozenset int isinstance len list map max min ord pow range
reversed round set sorted str sum tuple zip
True False None
""".split())

CLASS_BASES = frozenset({"Exception", "ValueError"})

# module -> the names a cell may use from it. Only names present in every supported Python (3.9 and later).
MODULES = {
    "math": frozenset("floor ceil sqrt exp log log10 log2 pow fabs isclose isfinite isnan inf nan pi e prod fsum comb perm "
                      "factorial gcd trunc".split()),
    "statistics": frozenset("fmean pstdev mean median median_low median_high mode pvariance stdev variance quantiles "
                            "StatisticsError".split()),
    "decimal": frozenset("Decimal ROUND_FLOOR ROUND_HALF_UP ROUND_DOWN ROUND_UP ROUND_CEILING ROUND_HALF_EVEN ROUND_HALF_DOWN "
                         "InvalidOperation".split()),
    "fractions": frozenset({"Fraction"}),
    "re": frozenset("compile escape findall finditer fullmatch match search split sub subn IGNORECASE I".split()),
    "collections": frozenset({"Counter", "OrderedDict", "defaultdict"}),
    "itertools": frozenset("filterfalse accumulate chain combinations groupby islice permutations product zip_longest".split()),
    "functools": frozenset({"reduce"}),
    "json": frozenset({"dumps", "loads"}),
}

# Standard modules an allowed module imports the first time some allowed name is used. The runner loads them
# up front; a cell cannot import them itself.
HIDDEN_DEPS = {"collections": ("heapq",), "statistics": ("heapq",)}

# Attribute names a cell may read from values (strings, numbers, lists, dicts, sets, Decimal, Fraction, regex results, Counter).
ATTRIBUTES = frozenset("""
add append count denominator end endswith find finditer fullmatch get group is_finite isdigit isspace items join lower match
pop quantize replace rstrip setdefault split start startswith strip sub to_integral_value update values
keys extend insert index remove sort reverse copy clear upper lstrip rfind isalpha isalnum isdecimal isnumeric zfill ljust
rjust center partition rpartition splitlines title numerator groups groupdict span most_common real imag as_integer_ratio
is_integer limit_denominator normalize to_integral is_nan is_zero is_signed sqrt ln log10 exp adjusted
search
""".split())

Problem = namedtuple("Problem", "line col code what")
def _p(node, code, what):
    return Problem(getattr(node, "lineno", 0) or 0, getattr(node, "col_offset", 0) or 0, code, what)
def describe(p):
    return "line %d: %s (%s)" % (p.line, p.what, p.code)

ALLOWED_SUMMARY = "allowed: modules %s; built-ins %s; see stemseal/policy.py" % (
    ", ".join("%s(%s)" % (m, ",".join(sorted(v))) for m, v in sorted(MODULES.items())), ", ".join(sorted(BUILTINS)))

# ---------------------------------------------------------------- precheck: no parsing
def precheck(src_bytes):
    """Checks that need no parser, safe to run on any bytes in any process."""
    if not isinstance(src_bytes, (bytes, bytearray)): return [Problem(0, 0, "E_SIZE", "source must be bytes")]
    if len(src_bytes) > MAX_BYTES: return [Problem(0, 0, "E_SIZE", "source is larger than %d bytes" % MAX_BYTES)]
    try: text = bytes(src_bytes).decode("utf-8")
    except UnicodeDecodeError: return [Problem(0, 0, "E_SIZE", "source is not UTF-8")]
    lines = text.split("\n")
    if len(lines) > MAX_LINES: return [Problem(0, 0, "E_SIZE", "more than %d lines" % MAX_LINES)]
    for i, l in enumerate(lines, 1):
        if len(l) > MAX_LINE_CHARS: return [Problem(i, 0, "E_SIZE", "line longer than %d characters" % MAX_LINE_CHARS)]
    depth = 0; line = 1
    for ch in text:   # brackets inside strings and comments count too: this only has to be conservative
        if ch == "\n": line += 1
        elif ch in "([{":
            depth += 1
            if depth > MAX_BRACKET_DEPTH: return [Problem(line, 0, "E_SIZE", "brackets nested deeper than %d" % MAX_BRACKET_DEPTH)]
        elif ch in ")]}": depth = max(0, depth - 1)
    return []

# ---------------------------------------------------------------- check: parses, so it runs inside the runner process
def _tree(src):
    pre = precheck(src.encode("utf-8") if isinstance(src, str) else src)
    if pre: return None, pre
    if not isinstance(src, str): src = bytes(src).decode("utf-8")
    try: return ast.parse(src, "cell.py", "exec"), []
    except SyntaxError as e: return None, [Problem(e.lineno or 0, e.offset or 0, "E_SYNTAX", "syntax error: %s" % e.msg)]
    except (RecursionError, MemoryError, ValueError) as e: return None, [Problem(0, 0, "E_SIZE", "source too complex: %s" % type(e).__name__)]

def imports_of(src):
    """The allowed modules the source imports, in order. Empty if it does not pass precheck or parse."""
    tree, _ = _tree(src)
    out = []
    if tree is None: return out
    for n in tree.body:
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name in MODULES and a.name not in out: out.append(a.name)
        elif isinstance(n, ast.ImportFrom) and n.module in MODULES and n.module not in out: out.append(n.module)
    return out

def check(src):
    """Every problem with the source as a list of Problem (empty = allowed). Never raises."""
    try: return _check(src)
    except Exception as e:   # a checker fault is a refusal, never a pass
        return [Problem(0, 0, "E_INTERNAL", "checker error: %s" % type(e).__name__)]

def _check(src):
    tree, pre = _tree(src)
    if tree is None: return pre
    bad = []
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES: return [Problem(0, 0, "E_SIZE", "more than %d syntax nodes" % MAX_NODES)]
    if _depth(tree) > MAX_DEPTH: return [Problem(0, 0, "E_SIZE", "nested deeper than %d" % MAX_DEPTH)]

    # imports: only at the top level, plain forms only
    modules = {}            # name bound by `import m` -> m
    imported = set()        # names bound by `from m import x`
    top = set(id(n) for n in tree.body)
    for n in nodes:
        if isinstance(n, ast.Import):
            if id(n) not in top: bad.append(_p(n, "E_IMPORT", "import inside a block")); continue
            for a in n.names:
                if a.name not in MODULES: bad.append(_p(n, "E_IMPORT", "module %s is not allowed" % a.name))
                elif a.asname: bad.append(_p(n, "E_IMPORT", "import %s as %s: rename is not allowed" % (a.name, a.asname)))
                else: modules[a.name] = a.name
        elif isinstance(n, ast.ImportFrom):
            if id(n) not in top: bad.append(_p(n, "E_IMPORT", "import inside a block")); continue
            if n.level: bad.append(_p(n, "E_IMPORT", "relative import is not allowed")); continue
            if n.module not in MODULES: bad.append(_p(n, "E_IMPORT", "module %s is not allowed" % n.module)); continue
            for a in n.names:
                if a.name == "*": bad.append(_p(n, "E_IMPORT", "from %s import * is not allowed" % n.module))
                elif a.name not in MODULES[n.module]: bad.append(_p(n, "E_IMPORT", "%s.%s is not allowed" % (n.module, a.name)))
                elif a.asname: bad.append(_p(n, "E_IMPORT", "from %s import %s as %s: rename is not allowed" % (n.module, a.name, a.asname)))
                else: imported.add(a.name)

    # names the cell defines itself
    defined = set()
    for n in nodes:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)): defined.add(n.name)
        elif isinstance(n, ast.arg): defined.add(n.arg)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store): defined.add(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name: defined.add(n.name)
    for name in sorted(defined):
        if name.startswith("__"): bad.append(Problem(0, 0, "E_NAME", "name %s is not allowed (starts with __)" % name))
        elif name in modules or name in imported: bad.append(Problem(0, 0, "E_NAME", "name %s rebinds an imported name" % name))
        elif hasattr(builtins, name): bad.append(Problem(0, 0, "E_NAME", "name %s replaces a built-in" % name))

    parent = {}
    for n in nodes:
        for c in ast.iter_child_nodes(n): parent[c] = n

    for n in nodes:
        kind = type(n).__name__
        if kind not in NODES: bad.append(_p(n, "E_NODE", "%s is not allowed" % kind)); continue
        if isinstance(n, ast.FunctionDef):
            if n.decorator_list: bad.append(_p(n, "E_NODE", "decorators are not allowed"))
        elif isinstance(n, ast.ClassDef):
            ok = (len(n.bases) == 1 and isinstance(n.bases[0], ast.Name) and n.bases[0].id in CLASS_BASES and not n.keywords
                  and not n.decorator_list and all(isinstance(b, ast.Pass) or (isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant)
                                                                              and isinstance(b.value.value, str)) for b in n.body))
            if not ok: bad.append(_p(n, "E_CLASS", "class %s: only `class Name(Exception|ValueError): pass`" % n.name))
        elif isinstance(n, ast.Name):
            if n.id.startswith("__"): bad.append(_p(n, "E_NAME", "name %s is not allowed" % n.id))
            elif n.id in modules:
                p = parent.get(n)
                if not (isinstance(p, ast.Attribute) and p.value is n and isinstance(p.ctx, ast.Load)):
                    bad.append(_p(n, "E_ATTR", "module %s may only be used as %s.<name>" % (n.id, n.id)))
            elif n.id in defined or n.id in imported: pass
            elif n.id not in BUILTINS: bad.append(_p(n, "E_NAME", "name %s is not allowed" % n.id))
        elif isinstance(n, ast.Attribute):
            if not isinstance(n.ctx, ast.Load): bad.append(_p(n, "E_ATTR", "setting attribute .%s is not allowed" % n.attr))
            elif n.attr.startswith("_"): bad.append(_p(n, "E_ATTR", "attribute .%s is not allowed" % n.attr))
            elif isinstance(n.value, ast.Name) and n.value.id in modules:
                if n.attr not in MODULES[modules[n.value.id]]: bad.append(_p(n, "E_ATTR", "%s.%s is not allowed" % (n.value.id, n.attr)))
            elif n.attr not in ATTRIBUTES: bad.append(_p(n, "E_ATTR", "attribute .%s is not allowed" % n.attr))
        elif isinstance(n, ast.keyword) and n.arg and n.arg.startswith("__"):
            bad.append(_p(n, "E_NAME", "keyword %s is not allowed" % n.arg))

    if not [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "cell_executor" and len(_args(n.args)) == 1]:
        bad.append(Problem(0, 0, "E_ENTRY", "needs one top-level `def cell_executor(input_data)`"))
    elif len([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "cell_executor"]) > 1:
        bad.append(Problem(0, 0, "E_ENTRY", "cell_executor is defined more than once"))

    seen = set(); out = []
    for p in sorted(bad, key=lambda p: (p.line, p.col, p.code, p.what)):
        if (p.code, p.what) not in seen: seen.add((p.code, p.what)); out.append(p)
    return out[:20]

def _args(a):
    return list(getattr(a, "posonlyargs", [])) + list(a.args) + list(a.kwonlyargs) + [x for x in (a.vararg, a.kwarg) if x is not None]

def _depth(tree):
    best = 0; stack = [(tree, 1)]
    while stack:
        n, d = stack.pop()
        if d > best: best = d
        if best > MAX_DEPTH: return best
        stack.extend((c, d + 1) for c in ast.iter_child_nodes(n))
    return best
