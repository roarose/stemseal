# -*- coding: utf-8 -*-
"""stemseal - this machine's state file (~/.stemseal/state.json).

    {"sealed": {"<cell>/<version>": "<cell.py sha256>", ...},   cell versions this machine has held with a format 2 lock
     "last_release": <n>, "release_sha256": "...", "revoked": [{"cell", "version", "reason"}, ...],   the last cell release taken
     "damaged": "<file name>"}                                    present after an unreadable state file was kept aside

Every change is made while holding state.json.lock (a file created only when absent), by reading the file, changing it
and writing a new file that replaces the old one in one step, so changes made at the same time by several stemseal
processes are all kept.

A state file that cannot be read, or whose known keys are not in their form, is never written over: the next change
moves it aside to state.bad-<time>.json and starts a new file that names it under "damaged". While the file cannot be
read or carries "damaged", what it would say is unknown and every user of it takes the safe side (status() says so).
Deleting state.json starts a new, empty record: versions held before are then not known to this machine.
Standard library only."""
import json, os, re, tempfile, time

LOCK_WAIT = 10.0        # seconds to wait for state.json.lock
LOCK_STALE = 60.0       # a lock file older than this was left by a process that ended; it is removed
_HEX = re.compile(r"[0-9a-f]{64}")

class Unavailable(Exception):
    """The state file cannot be changed now (its lock cannot be taken, or the new file cannot be written)."""

def _form_ok(s):
    if not isinstance(s, dict): return False
    sealed = s.get("sealed", {})
    if not (isinstance(sealed, dict) and all(isinstance(k, str) and isinstance(v, str) and _HEX.fullmatch(v) for k, v in sealed.items())): return False
    if "last_release" in s and not (type(s["last_release"]) is int and s["last_release"] >= 0): return False
    if "revoked" in s and not (isinstance(s["revoked"], list) and all(isinstance(r, dict) for r in s["revoked"])): return False
    if "release_sha256" in s and not isinstance(s["release_sha256"], str): return False
    if "damaged" in s and not isinstance(s["damaged"], str): return False
    return True

def read(path):
    """(state, "ok" | "missing" | "unreadable"). An unreadable state is returned as {}."""
    for i in range(20):                     # Windows only: the file being replaced answers PermissionError for a moment
        try:
            with open(path, "rb") as f: data = f.read()
            break
        except FileNotFoundError: return {}, "missing"
        except PermissionError:
            if os.name != "nt" or i == 19 or os.path.isdir(path): return {}, "unreadable"
            time.sleep(0.05)
        except OSError: return {}, "unreadable"
    try: s = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError): return {}, "unreadable"
    return (s, "ok") if _form_ok(s) else ({}, "unreadable")

def status(path):
    """"ok" when the record can be trusted as it is ("missing" counts: nothing recorded yet), "damaged" otherwise."""
    s, how = read(path)
    return "damaged" if how == "unreadable" or "damaged" in s else "ok"

class _Lock:
    def __init__(self, path): self.path = path + ".lock"; self.fd = None
    def __enter__(self):
        end = time.time() + LOCK_WAIT; last = None
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(self.fd, str(os.getpid()).encode()); return self
            except (FileExistsError, PermissionError) as e:   # Windows: a lock file being removed answers PermissionError for a moment
                last = e
                try:
                    if time.time() - os.stat(self.path).st_mtime > LOCK_STALE: os.remove(self.path); continue
                except OSError: pass
            except OSError as e: raise Unavailable("cannot create %s (%s)" % (os.path.basename(self.path), type(e).__name__))
            if time.time() > end:
                raise Unavailable("%s is held by another stemseal process" % os.path.basename(self.path) if isinstance(last, FileExistsError)
                                  else "cannot create %s (%s)" % (os.path.basename(self.path), type(last).__name__))
            time.sleep(0.02)
    def __exit__(self, *a):
        try: os.close(self.fd)
        except OSError: pass
        try: os.remove(self.path)
        except OSError: pass

def _clean_tmp(folder):
    """Remove new-file attempts that a process left when it ended in the middle of a change (only under the lock)."""
    try: names = os.listdir(folder)
    except OSError: return
    for n in names:
        if n.startswith(".state_") and n.endswith(".tmp"):
            p = os.path.join(folder, n)
            try:
                if time.time() - os.stat(p).st_mtime > LOCK_STALE: os.remove(p)
            except OSError: pass

def _replace(tmp, path):
    for i in range(20):                     # on Windows a reader holding the file open makes replace fail for a moment
        try: os.replace(tmp, path); return
        except PermissionError:
            if i == 19: raise
            time.sleep(0.05)

def change(path, fn):
    """Apply fn(state) -> None (changing the dict in place) under the lock and write the result. Raises Unavailable."""
    folder = os.path.dirname(path) or "."
    try: os.makedirs(folder, exist_ok=True)
    except OSError as e: raise Unavailable("cannot create %s (%s)" % (folder, type(e).__name__))
    with _Lock(path):
        _clean_tmp(folder)
        s, how = read(path)
        if how == "unreadable":
            aside = "state.bad-%s.json" % time.strftime("%Y%m%dT%H%M%S", time.gmtime())
            try: os.replace(path, os.path.join(folder, aside))
            except OSError as e: raise Unavailable("state.json cannot be read and cannot be moved aside (%s)" % type(e).__name__)
            s = {"damaged": aside}
        fn(s)
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(dir=folder, prefix=".state_", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f: json.dump(s, f, ensure_ascii=False, indent=1)
            _replace(tmp, path); tmp = None
        except OSError as e: raise Unavailable("cannot write state.json (%s)" % type(e).__name__)
        finally:
            if tmp:
                try: os.remove(tmp)
                except OSError: pass
    return s
