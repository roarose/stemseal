# -*- coding: utf-8 -*-
"""stemseal - the shape of a cell's result.

A contract may give `output_schema`: {"key": type, ...} for every key the cell returns. A type is one of
    number  integer  boolean  string  list  object  enum:a,b,c
and a trailing "?" also allows null ("integer?" is a whole number or null). A list or an object is checked only
within the bounds below, not item by item. Any other type, or a type that is not a string, is not accepted:
a result is then not passed on.

    the result's keys       exactly the schema's keys
    values inside           null, true/false, numbers, strings, lists and objects only (object keys are strings)
    nesting                 at most MAX_DEPTH levels, the result object being level 1
    a list                  at most MAX_ITEMS items
    an object               at most MAX_KEYS keys
    a string                at most MAX_STR characters, anywhere in the result, keys included
    the whole result        at most MAX_BYTES bytes as JSON

Without output_schema only the string rule applies. Standard library only."""
import json, math

MAX_DEPTH = 4
MAX_ITEMS = 100
MAX_KEYS = 32
MAX_STR = 200
MAX_BYTES = 16 * 1024
SCALAR = ("number", "integer", "boolean", "string")
SHALLOW = ("list", "object")

def _parse(spec):
    """(base, allows_null, enum values or None), or None for a type this version does not accept."""
    if not isinstance(spec, str) or not spec: return None
    null = spec.endswith("?"); base = spec[:-1] if null else spec
    if base in SCALAR or base in SHALLOW: return base, null, None
    if base.startswith("enum:"):
        vals = base[5:].split(",")
        if all(v and len(v) <= MAX_STR for v in vals) and len(set(vals)) == len(vals): return "enum", null, vals
    return None

def schema_problem(schema, output_keys=None):
    """None when the schema can be used; otherwise what is wrong with it."""
    if not isinstance(schema, dict) or not schema: return "output_schema must be a non-empty object"
    if len(schema) > MAX_KEYS: return "output_schema has more than %d keys" % MAX_KEYS
    for k, spec in schema.items():
        if len(k) > MAX_STR: return "output_schema key too long"
        if _parse(spec) is None: return "output_schema: type not accepted for %s" % k
    if output_keys is not None and set(output_keys) != set(schema): return "output_schema keys differ from output_keys"
    return None

def _fits(v, parsed):
    base, null, vals = parsed
    if v is None: return null
    if base == "number": return isinstance(v, (int, float)) and not isinstance(v, bool)
    if base == "integer": return isinstance(v, int) and not isinstance(v, bool)
    if base == "boolean": return isinstance(v, bool)
    if base == "string": return isinstance(v, str)
    if base == "enum": return isinstance(v, str) and v in vals
    if base == "list": return isinstance(v, list)
    return isinstance(v, dict)

def _walk(v, depth, bounds):
    """What in v is outside the bounds, or None."""
    if v is None or isinstance(v, bool) or isinstance(v, int): return None
    if isinstance(v, float): return None if math.isfinite(v) else "a number that is not finite"
    if isinstance(v, str): return None if len(v) <= MAX_STR else "a string longer than %d characters" % MAX_STR
    if isinstance(v, (list, dict)):
        if bounds and depth > MAX_DEPTH: return "nested deeper than %d levels" % MAX_DEPTH
        if isinstance(v, list):
            if bounds and len(v) > MAX_ITEMS: return "a list longer than %d items" % MAX_ITEMS
            items = v
        else:
            if bounds and len(v) > MAX_KEYS: return "an object with more than %d keys" % MAX_KEYS
            for k in v:
                if not isinstance(k, str): return "an object key that is not a string"
                if len(k) > MAX_STR: return "a string longer than %d characters" % MAX_STR
            items = v.values()
        for x in items:
            p = _walk(x, depth + 1, bounds)
            if p: return p
        return None
    return "a value that is not plain JSON"

def problem(out, schema=None):
    """None when the result fits; otherwise a short description of the first thing that does not."""
    if not isinstance(out, dict): return "the result is not an object"
    if schema is None: return _walk(out, 1, False)
    bad = schema_problem(schema)
    if bad: return bad
    if set(out) != set(schema):
        missing, extra = sorted(set(schema) - set(out)), sorted(set(out) - set(schema))
        return "keys differ from output_schema (missing %s, extra %s)" % (missing[:5], [k[:40] for k in extra[:5]])
    p = _walk(out, 1, True)
    if p: return p
    for k, spec in schema.items():
        if not _fits(out[k], _parse(spec)): return "%s is not %s" % (k, spec)
    try: size = len(json.dumps(out, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError): return "a value that is not plain JSON"
    return None if size <= MAX_BYTES else "the result is larger than %d bytes" % MAX_BYTES
