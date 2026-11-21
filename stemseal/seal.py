# -*- coding: utf-8 -*-
"""stemseal - the lock of a cell (lock.json, format 2).

    {"format": 2, "kind": "cell", "cell": name, "version": v,
     "sha256": <cell.py sha256>,                      same place and meaning as format 1
     "files": {"cell.py": ..., "contract.json": ..., "gt_cases.json": ...},   every file of the folder that the lock covers
     "policy": <checker policy version the cell passed>,
     "gt_total", "gt_passed", "deterministic", "locked_at", "locked_by"}

A cell is used only when its lock is format 2 of a kind this version knows, names its own folder, and every file it lists
is byte for byte the one it lists. Each kind has files it must list (KINDS); a lock without "kind" is a cell.
The hashes are of the file bytes as stored. Standard library only."""
import hashlib, json, os, re

FORMAT = 2
SEALED = ("cell.py", "contract.json", "gt_cases.json")      # what a cell's lock lists
KINDS = {"cell": SEALED}                                    # kind -> files its lock must list; any other kind is not used
OLD = "old lock format"
_HEX = re.compile(r"[0-9a-f]{64}")
_NAME = re.compile(r"[a-z0-9_][a-z0-9_.-]{0,63}")
def kind(lock): return lock.get("kind", "cell") if isinstance(lock, dict) else None

def sha(b): return hashlib.sha256(b).hexdigest()

def read_bytes(d, name):
    try:
        with open(os.path.join(d, name), "rb") as f: return f.read()
    except OSError: return None

def problem(lock, raw, name=None, version=None):
    """None when the lock is a well-formed format 2 lock for this cell and every file in raw ({file name: bytes}) is listed
    in it and matches it. Otherwise OLD for a format 1 lock, or the name of the first file that does not match ("lock.json"
    when the lock itself is not in order)."""
    if not isinstance(lock, dict): return "lock.json"
    if "format" not in lock or lock.get("format") == 1: return OLD
    if lock.get("format") != FORMAT or kind(lock) not in KINDS: return "lock.json"
    files = lock.get("files")
    if not (isinstance(files, dict) and all(isinstance(f, str) and _NAME.fullmatch(f) and f != "lock.json" and isinstance(h, str) and _HEX.fullmatch(h)
                                            for f, h in files.items())):
        return "lock.json"
    if not set(KINDS[kind(lock)]) <= set(files): return "lock.json"
    if "cell.py" in files and lock.get("sha256") != files["cell.py"]: return "lock.json"
    if not isinstance(lock.get("policy"), int) or isinstance(lock.get("policy"), bool): return "lock.json"
    if (name is not None and lock.get("cell") != name) or (version is not None and lock.get("version") != version): return "lock.json"
    for f, b in raw.items():
        if f not in files or b is None or sha(b) != files[f]: return f
    return None

def problem_all(lock, d, name=None, version=None):
    """problem() over every file the lock lists, read from folder d."""
    files = lock.get("files") if isinstance(lock, dict) else None
    listed = sorted(files) if isinstance(files, dict) and all(isinstance(f, str) and _NAME.fullmatch(f) for f in files) else []
    return problem(lock, {f: read_bytes(d, f) for f in listed}, name, version)

def build(cell, version, raw, policy_version, gt_total, gt_passed, locked_at, locked_by):
    """A format 2 lock for the given file bytes ({file name: bytes} for all of SEALED)."""
    files = {f: sha(raw[f]) for f in SEALED}
    return {"format": FORMAT, "kind": "cell", "cell": cell, "version": version, "sha256": files["cell.py"], "files": files, "policy": policy_version,
            "gt_total": gt_total, "gt_passed": gt_passed, "deterministic": True, "locked_at": locked_at, "locked_by": locked_by}

def dumps(lock):
    return (json.dumps(lock, ensure_ascii=False, indent=1) + "\n").encode("utf-8")

def write(d, lock, keep_old_as=None):
    """Write lock.json in d, replacing it in one step. keep_old_as: first keep the current lock.json under this name."""
    p = os.path.join(d, "lock.json")
    if keep_old_as:
        old = read_bytes(d, "lock.json")
        with open(os.path.join(d, keep_old_as), "xb") as f: f.write(old)
    tmp = p + ".new"
    with open(tmp, "wb") as f: f.write(dumps(lock))
    os.replace(tmp, p)
