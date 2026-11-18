# -*- coding: utf-8 -*-
"""stemseal - model guides. Every contact (find, call) names the caller's model; the hub answers with that model's
cell-selection guide and applies it: how many candidates, what each candidate card shows, and input repair before a call.
Guides live in guides/<id>.json. 'match' holds lowercase glob patterns on the model name; the most specific family match wins,
and the size guide 'tiny' (4B or smaller) tightens it further. No match -> _default.
A guide marked 'measured' came from this hub's experiments; the others are public reports to be re-measured."""
import fnmatch, json, os
from . import hub
GDIR = os.environ.get("STEMSEAL_GUIDES_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "guides")

def _all():
    out = {}
    for f in sorted(os.listdir(GDIR)) if os.path.isdir(GDIR) else []:
        if f.endswith(".json"): g = json.load(open(os.path.join(GDIR, f), encoding="utf-8")); out[g["id"]] = g
    return out

def guide_for(model):
    G = _all(); m = (model or "").lower().strip()
    best = None
    for g in G.values():
        if g["id"] in ("_default", "tiny"): continue
        for p in g.get("match", []):
            if fnmatch.fnmatch(m, p) and (best is None or len(p) > best[0]): best = (len(p), g)
    g = json.loads(json.dumps(best[1] if best else G["_default"]))
    t = G.get("tiny")
    if t and m and any(fnmatch.fnmatch(m, p) for p in t["match"]):
        g["selection"]["max_candidates"] = min(g["selection"]["max_candidates"], t["selection"]["max_candidates"])
        g["weaknesses"] = g["weaknesses"] + t["weaknesses"]; g["id"] += "+tiny"
    return g

def brief(g):
    return {"id": g["id"], "version": g["version"], "source": g["source"], "rules": g["prompt_rules"], "teaching": g.get("teaching"),
            "max_candidates": g["selection"]["max_candidates"], "search_words": g["selection"].get("search_words", False), "search_words_prompt": g.get("search_words_prompt"), "output_format": g["selection"]["output_format"], "disable_thinking": g["selection"]["disable_thinking"]}

def _short(v):
    if isinstance(v, list): return v[:3] + (["..."] if len(v) > 3 else [])
    if isinstance(v, dict): return {k: _short(x) for k, x in list(v.items())[:3]}
    return v

def find(need, model=None, caller="unknown", request=None, k=None, min_score=None, words=None):
    g = guide_for(model); s = g["selection"]
    q = need + (" " + request if request and s.get("search_with_request", True) else "")
    if s.get("search_words") and request:
        # the request is searched as written and the model's own phrase on its own, taken in turn: a garbled or
        # off-target phrase from a small model can then add candidates but never push the request's own matches out
        q = request; words = list(words or []) + ([need] if need.strip() else [])
    hits = hub.find(q, caller=caller, k=k or s["max_candidates"], min_score=min_score if min_score is not None else s["min_score"],
                    words=words if s.get("search_words") else None)
    for h in hits:
        c = hub.load(h["cell"])
        if s.get("show_output_keys"): h["output_keys"] = c["contract"]["output_keys"]
        if s.get("show_input_example"):
            try: h["input_example"] = _short(json.load(open(os.path.join(c["dir"], "gt_cases.json"), encoding="utf-8"))[0]["input"])
            except Exception: pass
    out = {"guide": brief(g), "cells": hits}
    if not hits: out["no_cell"] = hub.request_cell(need + (" | " + request if request else ""), caller=caller)
    if s.get("output_format") == "schema":
        # constrained decoding: the model can only answer with a candidate's name or "none", and only with the cell's input keys
        out["pick_schema"] = {"type": "object", "properties": {"cell": {"type": "string", "enum": [h["cell"] for h in hits] + ["none"]}}, "required": ["cell"]}
        for h in hits: h["input_json_schema"] = input_schema(hub.load(h["cell"])["contract"])
    return out

def _prop_schema(desc):
    d = str(desc).lower()
    if "list" in d: return {"type": "array"}
    if "object" in d: return {"type": "object"}
    if "|" in d and not any(w in d for w in ("number", "int")): return {"type": "string", "enum": [x.strip() for x in d.split("|")]}
    if any(w in d for w in ("number", "int", ">", "<", "won", "0~")): return {"type": "number"}
    return {}
def input_schema(contract):
    """JSON schema of a cell's input, for Ollama's format= (structured output)."""
    sch = contract.get("input_schema", {}); props = sch.get("properties", {}); req = sch.get("required", [])
    return {"type": "object", "properties": {k: _prop_schema(props.get(k, "")) for k in req}, "required": req}

def repair(name, inp, g):
    """Fix the input shapes a guide says this model gets wrong. Returns (input, list of fixes)."""
    c = hub.load(name) if isinstance(name, str) else None
    if not c or not isinstance(inp, dict): return inp, []
    fx = []; inp = dict(inp); rq = c["contract"]["input_schema"].get("required", []); props = c["contract"]["input_schema"].get("properties", {})
    if "unwrap" in g["selection"].get("repair_input", []):
        for k in rq:
            v = inp.get(k)
            if isinstance(v, dict) and len(v) == 1:
                (ik, iv), = v.items()
                is_obj = "object" in str(props.get(k, ""))
                if (not is_obj and isinstance(iv, (list, int, float)) and not isinstance(iv, bool)) or (is_obj and isinstance(iv, dict) and iv):
                    inp[k] = iv; fx.append("unwrap:%s" % k)
    if "rename_single" in g["selection"].get("repair_input", []):
        miss = [k for k in rq if k not in inp]; extra = [k for k in inp if k not in rq and k not in props]
        if len(miss) == 1 and len(extra) == 1: inp[miss[0]] = inp.pop(extra[0]); fx.append("rename:%s->%s" % (extra[0], miss[0]))
    return inp, fx

def call(name, inp, model=None, caller="unknown"):
    g = guide_for(model)
    inp2, fx = repair(name, inp, g)
    r = hub.call(name, inp2, caller=caller)
    r["guide"] = g["id"]; r["repairs"] = fx
    if fx: hub._log({"type": "repair", "cell": name, "model": model, "guide": g["id"], "fixes": fx, "status": r["status"]})
    return r
