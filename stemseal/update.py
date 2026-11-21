# -*- coding: utf-8 -*-
"""stemseal update - bring cells released after this version was installed.

Cells come in numbered releases (git tag cells-N). This takes the newest release only when every step holds:

  1. the newest N is not below the last release this machine took (~/.stemseal/state.json),
  2. release.json at tag cells-N carries a signature by one of the release keys built into this version,
  3. release.json says it is release N, is format 2, and this version is new enough for it,
  4. its sha256 is the one this version lists for N (trusted_releases.json), or it links, release by release,
     to one that this version lists,
  5. each cell's files have the hashes release.json gives, its lock covers them, it passes the checker and every one of
     its ground-truth cases on this machine, under the same watch and limits as any call.

A cell that fails is not installed; nothing already installed is overwritten. Withdrawn cells (release.json "revoked")
are no longer used. Only runs when you type it; nothing else in stemseal touches the network. Nothing is sent.

  stemseal update          install new cells
  stemseal update --check  only list what is new
Maintainers: `stemseal release <N>` writes stemseal/cells/release.json for release N."""
import json, os, re, shutil, tempfile, urllib.request
from . import __version__, ed25519, hub, seal, shape, state

PKG = os.path.dirname(os.path.abspath(__file__))
REFS = "https://api.github.com/repos/roarose/stemseal/git/matching-refs/tags/cells-"
RAW = "https://raw.githubusercontent.com/roarose/stemseal/cells-%d/stemseal/cells/%s"
SIG = "https://github.com/roarose/stemseal/releases/download/cells-%d/release.json.sig"
TEST_BASE = os.environ.get("STEMSEAL_TEST_RELEASE_BASE")       # tests only: a local server in place of GitHub
FILES = ("cell.py", "contract.json", "gt_cases.json", "lock.json", "baseline.json")
NEEDED = ("cell.py", "contract.json", "gt_cases.json", "lock.json")
MAX_RELEASE = 1024 * 1024
MAX_FILE = 512 * 1024
MAX_CHAIN = 50
NAME = re.compile(r"[a-z][a-z0-9_]{2,63}")
VERSION = re.compile(r"[0-9]{1,4}\.[0-9]{1,4}")
TAG = re.compile(r"refs/tags/cells-([1-9][0-9]{0,8})")
HEX = re.compile(r"[0-9a-f]{64}")

class Refused(Exception):
    """The release as a whole is not taken."""

def _load_pkg(name, default):
    try:
        with open(os.path.join(PKG, name), encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError): return default
def release_keys():
    """The public keys a release must be signed with (release_keys.json, hex). Empty: no release is taken."""
    keys = _load_pkg("release_keys.json", {}).get("keys", [])
    return [bytes.fromhex(k) for k in keys if isinstance(k, str) and re.fullmatch(r"[0-9a-f]{64}", k)]
def trusted_releases():
    """{N: sha256 of release.json} for the releases out when this version was built."""
    t = _load_pkg("trusted_releases.json", {})
    return {int(k): v for k, v in t.items() if isinstance(k, str) and k.isdigit() and isinstance(v, str) and HEX.fullmatch(v)}

def _urls():
    if TEST_BASE: return TEST_BASE + "/refs", TEST_BASE + "/cells-%d/%s", TEST_BASE + "/sig/cells-%d/release.json.sig"
    return REFS, RAW, SIG
def _get(url, limit, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "stemseal-update"})
    with urllib.request.urlopen(req, timeout=timeout) as r: data = r.read(limit + 1)
    if len(data) > limit: raise Refused("a download is larger than allowed")
    return data

def _version_tuple(v):
    try: return tuple(int(x) for x in str(v).split("."))
    except ValueError: return None

# ---------------------------------------------------------------- this machine's state
def read_state():
    return state.read(hub.STATE)[0]

# ---------------------------------------------------------------- the release
def _signature(raw):
    """The 64 signature bytes from a .sig file: 128 hex characters (spaces and line ends ignored), or the raw 64 bytes."""
    try:
        text = raw.decode("ascii"); h = re.sub(r"\s+", "", text)
        if re.fullmatch(r"[0-9a-fA-F]{128}", h): return bytes.fromhex(h)
    except UnicodeDecodeError: pass
    return raw if len(raw) == 64 else None

def signed_by_release_key(raw, sig_raw, keys=None):
    sig = _signature(sig_raw or b"")
    return bool(sig) and any(ed25519.verify(k, raw, sig) for k in (release_keys() if keys is None else keys))

def _parse(raw, n):
    try: rel = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError): raise Refused("release.json of cells-%d is not valid JSON" % n)
    if not isinstance(rel, dict) or rel.get("format") != 2: raise Refused("release.json of cells-%d is not format 2" % n)
    if rel.get("release") != n: raise Refused("release.json says it is release %r, not cells-%d" % (rel.get("release"), n))
    if not isinstance(rel.get("cells"), dict) or not isinstance(rel.get("revoked", []), list): raise Refused("release.json of cells-%d is not in order" % n)
    return rel

def _anchored(n, raw, rel, fetch):
    """release.json of cells-n is the one this version lists, or links back to one it lists."""
    trusted = trusted_releases(); digest = seal.sha(raw)
    for _ in range(MAX_CHAIN):
        if n in trusted:
            if trusted[n] != digest: raise Refused("cells-%d is not the release this version knows" % n)
            return
        prev = rel.get("previous_index_sha256")
        if n <= 1 or not (isinstance(prev, str) and HEX.fullmatch(prev)): break
        n -= 1; raw = fetch(n); digest = seal.sha(raw)
        if digest != prev: raise Refused("the link from cells-%d to cells-%d does not hold" % (n + 1, n))
        rel = _parse(raw, n)
    raise Refused("cells releases do not link to one this version knows")

def latest_release():
    refs, _, _ = _urls()
    try: tags = json.loads(_get(refs, MAX_RELEASE).decode("utf-8"))
    except Refused: raise
    except Exception as e: raise Refused("cannot read the list of cell releases: %s" % type(e).__name__)
    ns = [int(m.group(1)) for t in tags if isinstance(t, dict) for m in [TAG.fullmatch(str(t.get("ref", "")))] if m]
    return max(ns) if ns else 0

def fetch_release(n):
    """(raw bytes, parsed release) for cells-n after the signature, format and anchor checks; Refused otherwise."""
    keys = release_keys()
    if not keys: raise Refused("this stemseal version has no release key; update stemseal")
    _, raw_url, sig_url = _urls()
    def fetch(k):
        try: return _get(raw_url % (k, "release.json"), MAX_RELEASE)
        except Refused: raise
        except Exception as e: raise Refused("cannot download release.json of cells-%d: %s" % (k, type(e).__name__))
    raw = fetch(n)
    try: sig = _get(sig_url % n, 4096)
    except Refused: raise
    except Exception: sig = None
    if not sig: raise Refused("cells-%d has no signature" % n)
    if not signed_by_release_key(raw, sig, keys): raise Refused("cells-%d is not signed by a stemseal release key" % n)
    rel = _parse(raw, n)
    need = _version_tuple(rel.get("min_client", "0"))
    if need is None or need > _version_tuple(__version__): raise Refused("cells-%d needs stemseal %s or newer; update stemseal" % (n, rel.get("min_client")))
    _anchored(n, raw, rel, fetch)
    return raw, rel

# ---------------------------------------------------------------- one cell
def _have(name, v):
    """'no' | 'yes' | 'replace' (a cell `update` installed before with an old lock, same cell.py)."""
    d = hub._found(name).get(v)
    if not d: return "no"
    c = hub.inspect(name, v)
    same = lambda a, b: os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    if c and c["seal"] == seal.OLD and same(os.path.dirname(os.path.dirname(c["dir"])), hub.USER_CELLS) \
            and hub._from_update(name, v, c["lock"]): return "replace"
    return "yes"

def _install(n, name, v, meta, raw_url):
    files = meta.get("files")
    if not (isinstance(files, dict) and set(NEEDED) <= set(files) <= set(FILES) and all(isinstance(h, str) and HEX.fullmatch(h) for h in files.values())):
        return "file list is not in order"
    root = os.path.realpath(hub.USER_CELLS); os.makedirs(root, exist_ok=True)
    dest = os.path.realpath(os.path.join(root, name, v))
    if os.path.dirname(os.path.dirname(dest)) != root: return "install folder is outside the cells folder"
    tmp = tempfile.mkdtemp(prefix=".incoming_", dir=root)
    try:
        raw = {}
        for f in sorted(files):
            try: raw[f] = _get(raw_url % (n, "%s/%s/%s" % (name, v, f)), MAX_FILE)
            except Refused: return "%s is larger than allowed" % f
            except Exception as e: return "download failed (%s)" % type(e).__name__
            if seal.sha(raw[f]) != files[f]: return "%s does not match the release" % f
            with open(os.path.join(tmp, f), "wb") as fh: fh.write(raw[f])
        try: lock = json.loads(raw["lock.json"].decode("utf-8"))
        except (UnicodeDecodeError, ValueError): return "lock.json is not valid JSON"
        if not isinstance(lock, dict) or not isinstance(lock.get("files"), dict) or any(files.get(f) != h for f, h in lock["files"].items()):
            return "the lock does not match the release"
        p = seal.problem_all(lock, tmp, name, v)
        if p: return "lock: %s" % p
        try: contract = json.loads(raw["contract.json"].decode("utf-8")); gt = json.loads(raw["gt_cases.json"].decode("utf-8"))
        except (UnicodeDecodeError, ValueError): return "contract.json or gt_cases.json is not valid JSON"
        schema = contract.get("output_schema") if isinstance(contract, dict) else None
        if schema is not None and shape.schema_problem(schema, contract.get("output_keys")): return "output_schema is not usable"
        problems = hub.purity_check(raw["cell.py"])
        if problems: return "policy gate: %s" % problems[:3]
        if not isinstance(gt, list): return "gt_cases.json is not a list"
        rep = hub.gt_check(raw["cell.py"].decode("utf-8"), gt, schema)
        if rep["passed"] != rep["total"] or rep["total"] < hub.MIN_GT or not rep["deterministic"]:
            return "ground-truth gate on this machine: %d/%d" % (rep["passed"], rep["total"])
        if os.path.exists(dest):
            aside = os.path.join(root, ".replaced", "%s-%s-%s" % (name, v, hub.now().replace(":", "")))
            os.makedirs(os.path.dirname(aside), exist_ok=True); os.replace(dest, aside)
        try: hub.mark_sealed(name, v, files["cell.py"])          # the record first, then the cell
        except state.Unavailable as e: return "cannot record the cell on this machine: %s" % e
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        os.replace(tmp, dest); tmp = None
        hub._log({"type": "update", "cell": name, "version": v, "sha256": files["cell.py"], "release": n})
        for t in meta.get("answers", []) if isinstance(meta.get("answers"), list) else []: hub._log({"type": "fulfilled", "ticket": str(t)[:40], "cell": name})
        return None
    finally:
        if tmp: shutil.rmtree(tmp, ignore_errors=True)

# ---------------------------------------------------------------- update
def _revoked(rel):
    return [{"cell": r["cell"], "version": r["version"], "reason": str(r.get("reason", ""))[:200]} for r in rel.get("revoked", [])
            if isinstance(r, dict) and isinstance(r.get("cell"), str) and isinstance(r.get("version"), str)]

def update(check_only=False):
    out = {"ok": False}
    if TEST_BASE: out["warning"] = "STEMSEAL_TEST_RELEASE_BASE is set: cells come from %s, not from GitHub" % TEST_BASE
    bad = hub.state_problem()
    if bad: out["reason"] = bad; return out
    last = read_state().get("last_release", 0)
    try:
        n = latest_release()
        if n == 0: out.update(ok=True, new=[], installed=[], refused=[], note="no cell release yet"); return out
        if n < last: raise Refused("the newest release (cells-%d) is older than the one this machine took (cells-%d)" % (n, last))
        raw, rel = fetch_release(n)
    except Refused as e:
        out["reason"] = str(e); return out
    revoked = {(r["cell"], r["version"]) for r in _revoked(rel)}
    todo, refused = [], []
    for name, vers in sorted(rel["cells"].items()):
        if not (isinstance(name, str) and NAME.fullmatch(name) and isinstance(vers, dict)):
            refused.append({"cell": str(name)[:64], "reason": "name is not allowed"}); continue
        for v, meta in sorted(vers.items(), key=lambda x: _version_tuple(x[0]) or ()):
            if not (isinstance(v, str) and VERSION.fullmatch(v) and isinstance(meta, dict)):
                refused.append({"cell": name, "version": str(v)[:16], "reason": "version is not allowed"}); continue
            if (name, v) in revoked: continue
            if meta.get("tier") != "sealed": refused.append({"cell": name, "version": v, "reason": "not a sealed cell"}); continue
            have = _have(name, v)
            if have != "yes": todo.append((name, v, meta))
    if check_only:
        out.update(ok=True, release=n, new=[{"cell": a, "version": b, "description": m.get("description")} for a, b, m in todo], refused=refused)
        return out
    _, raw_url, _ = _urls(); done = []
    for name, v, meta in todo:
        why = _install(n, name, v, meta, raw_url)
        if why: refused.append({"cell": name, "version": v, "reason": why})
        else: done.append({"cell": name, "version": v, "description": meta.get("description")})
    def took(s): s.update(last_release=max(n, s.get("last_release", 0)), revoked=_revoked(rel), release_sha256=seal.sha(raw))
    try: state.change(hub.STATE, took)
    except state.Unavailable as e: out["warning"] = "cells installed, but this machine's record of the release was not written: %s" % e
    out.update(ok=True, release=n, installed=done, refused=refused, where=hub.USER_CELLS)
    return out

# ---------------------------------------------------------------- maintainers
def build_index(base=None):
    """The format 1 index.json that stemseal 0.2.3 and older read from main (kept as it is during the move to releases)."""
    base = base or hub.CELLS; out = {}
    for name in sorted(os.listdir(base)):
        d = os.path.join(base, name)
        if not os.path.isdir(d): continue
        for v in sorted((v for v in os.listdir(d) if os.path.exists(os.path.join(d, v, "lock.json"))), key=hub._vkey):
            L = json.load(open(os.path.join(d, v, "lock.json"), encoding="utf-8"))
            c = json.load(open(os.path.join(d, v, "contract.json"), encoding="utf-8"))
            out.setdefault(name, {})[v] = {"sha256": L["sha256"], "gt": L["gt_total"], "locked_at": L["locked_at"],
                                           "description": c.get("description", ""), "description_en": c.get("description_en", ""),
                                           "answers": c.get("answers", [])}
    idx = {"format": 1, "cells": out}
    json.dump(idx, open(os.path.join(base, "index.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return idx

def build_release(n, min_client=None, revoke=(), base=None):
    """Write release.json (format 2) for release n from the shipped cells, and add its sha256 to trusted_releases.json.
    The previous release's sha256 comes from trusted_releases.json; its withdrawn cells carry over. Returns (release, sha256)."""
    base = base or hub.CELLS; trusted_path = os.path.join(PKG, "trusted_releases.json") if base == hub.CELLS else os.path.join(base, "trusted_releases.json")
    try:
        with open(trusted_path, encoding="utf-8") as f: trusted = json.load(f)
    except (OSError, ValueError): trusted = {}
    if n > 1 and str(n - 1) not in trusted: raise ValueError("cells-%d is not in trusted_releases.json" % (n - 1))
    cells = {}
    for name in sorted(os.listdir(base)):
        d = os.path.join(base, name)
        if not os.path.isdir(d): continue
        for v in sorted((v for v in os.listdir(d) if os.path.exists(os.path.join(d, v, "lock.json"))), key=hub._vkey):
            vd = os.path.join(d, v)
            lock = json.loads(seal.read_bytes(vd, "lock.json").decode("utf-8"))
            p = seal.problem_all(lock, vd, name, v)
            if p: raise ValueError("%s %s: %s" % (name, v, p))
            c = json.loads(seal.read_bytes(vd, "contract.json").decode("utf-8"))
            files = {f: seal.sha(seal.read_bytes(vd, f)) for f in FILES if os.path.isfile(os.path.join(vd, f))}
            cells.setdefault(name, {})[v] = {"files": files, "tier": "sealed", "gt": lock["gt_total"], "locked_at": lock["locked_at"],
                                             "description": c.get("description", ""), "description_en": c.get("description_en", ""),
                                             "answers": c.get("answers", [])}
    old = []
    try:
        with open(os.path.join(base, "release.json"), encoding="utf-8") as f: prev = json.load(f)
        if prev.get("release") == n - 1: old = prev.get("revoked", [])
    except (OSError, ValueError, AttributeError): pass
    rel = {"format": 2, "release": n, "min_client": min_client or __version__, "created_at": hub.now(),
           "previous_index_sha256": trusted.get(str(n - 1)) if n > 1 else None, "cells": cells, "revoked": list(old) + list(revoke)}
    raw = (json.dumps(rel, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    with open(os.path.join(base, "release.json"), "wb") as f: f.write(raw)
    trusted[str(n)] = seal.sha(raw)
    with open(trusted_path, "w", encoding="utf-8") as f: json.dump(trusted, f, indent=1); f.write("\n")
    return rel, trusted[str(n)]
