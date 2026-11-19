# -*- coding: utf-8 -*-
"""stemseal - model guides. Every contact (find, call) names the caller's model; the hub answers with that model's
cell-selection guide and applies it: how many candidates, what each candidate card shows, and input repair before a call.
Guides live in guides/<id>.json. 'match' holds lowercase glob patterns on the model name; the most specific family match wins,
and the size guide 'tiny' (4B or smaller) tightens it further. No match -> _default.
A guide marked 'measured' came from this hub's experiments; the others are public reports to be re-measured."""
import fnmatch, json, os, re
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

def lang_of(text):
    """Guide language: STEMSEAL_LANG (ko|en) if set, else Korean when the request has Hangul, otherwise English.
    The measured results were with the Korean wording; the English wording is a translation, not yet re-measured."""
    v = (os.environ.get("STEMSEAL_LANG") or "").lower()
    if v in ("ko", "en"): return v
    return "ko" if any("\uac00" <= ch <= "\ud7a3" for ch in (text or "")) else "en"

def brief(g, lang="ko"):
    en = lang == "en"
    return {"id": g["id"], "version": g["version"], "source": g["source"], "lang": lang,
            "rules": g.get("prompt_rules_en") if en and g.get("prompt_rules_en") else g["prompt_rules"],
            "teaching": g.get("teaching_en") if en and g.get("teaching_en") else g.get("teaching"),
            "max_candidates": g["selection"]["max_candidates"], "search_words": g["selection"].get("search_words", False),
            "search_words_prompt": g.get("search_words_prompt_en") if en and g.get("search_words_prompt_en") else g.get("search_words_prompt"), "output_format": g["selection"]["output_format"], "disable_thinking": g["selection"]["disable_thinking"]}

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
    out = {"guide": brief(g, lang_of(need + " " + (request or ""))), "cells": hits}
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
    for k, v in list(inp.items()):
        # "12,000" or "5%" as text -> number (templates are text, and small models sometimes keep the quotes)
        if isinstance(v, str):
            # "12,000", "8%", "10030 (won)", "10,030원": exactly one number in the text -> that number
            nums = re.findall(r"-?\d+(?:\.\d+)?", v.replace(",", ""))
            if len(nums) == 1:
                inp[k] = int(nums[0]) if re.fullmatch(r"-?\d+", nums[0]) else float(nums[0]); fx.append("number:%s" % k)
        elif isinstance(v, list) and v and all(isinstance(x, str) for x in v):
            try: inp[k] = [float(x.replace(",", "").replace("%", "").strip()) for x in v]; fx.append("number:%s" % k)
            except ValueError: pass
    norm = lambda x: "".join(ch for ch in str(x).lower() if ch.isalnum())
    for k in list(inp):
        # hourlyWage / Hourly-Wage -> hourly_wage: same key in another spelling (small models write camelCase often)
        if k not in props and k not in rq:
            m = [t for t in dict.fromkeys(list(rq) + list(props)) if norm(t) == norm(k) and t not in inp]
            if len(m) == 1: inp[m[0]] = inp.pop(k); fx.append("rename:%s->%s" % (k, m[0]))
    al = {norm(a): t for t, lst in (c["contract"].get("input_aliases") or {}).items() for a in lst}
    for t in dict.fromkeys(al.values()):
        # a cell can list the other names small models use for an input (portion -> grams); only when exactly one is there
        if t in inp: continue
        m = [k for k in inp if k not in props and k not in rq and al.get(norm(k)) == t]
        if len(m) == 1: inp[t] = inp.pop(m[0]); fx.append("alias:%s->%s" % (m[0], t))
    for k, rule in (c["contract"].get("input_sanity") or {}).items():
        # a cell can name an optional input that small models commonly fill with the wrong unit; drop it and say so
        v = inp.get(k)
        if rule.get("action") == "drop" and isinstance(v, (int, float)) and not isinstance(v, bool) and v < rule.get("min", float("-inf")):
            inp.pop(k); fx.append("dropped:%s=%s (%s)" % (k, v, rule.get("why", "out of range")))
        if rule.get("action") == "per100_currency" and isinstance(v, (int, float)) and not isinstance(v, bool) and v >= rule.get("min", 100):
            cur = " ".join(str(x).lower() for kk, x in inp.items() if "currency" in str(kk).lower() or "unit" in str(kk).lower())
            if any(w in cur for w in rule.get("currencies", [])):
                inp[k] = v / 100; fx.append("per100:%s=%s/100 (%s)" % (k, v, rule.get("why", "quoted per 100")))
        if rule.get("action") == "fraction_to_pct" and isinstance(v, (int, float)) and not isinstance(v, bool) and 0 < v < 1:
            inp[k] = round(v * 100, 10); fx.append("pct:%s=%s*100 (%s)" % (k, v, rule.get("why", "fraction given")))
        if rule.get("action") == "percent_list" and isinstance(v, list) and v and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v) \
                and any(abs(x) >= rule.get("if_any_abs_at_least", 1) for x in v):
            # 5, 3, -2 written as percent where the cell takes 0.05, 0.03, -0.02
            inp[k] = [x / 100 for x in v]; fx.append("percent:%s/100 (%s)" % (k, rule.get("why", "percent given")))
    if "rename_single" in g["selection"].get("repair_input", []):
        miss = [k for k in rq if k not in inp]; extra = [k for k in inp if k not in rq and k not in props]
        if len(miss) == 1 and len(extra) == 1: inp[miss[0]] = inp.pop(extra[0]); fx.append("rename:%s->%s" % (extra[0], miss[0]))
    return inp, fx

def call(name, inp, model=None, caller="unknown"):
    g = guide_for(model)
    inp2, fx = repair(name, inp, g)
    r = hub.call(name, inp2, caller=caller)
    r["guide"] = g["id"]; r["repairs"] = fx
    if r.get("status") == "ok":
        r["input_used"] = inp2
        # small models drop or move a digit when they copy 2060740 into a sentence; hand them the number already written out
        if isinstance(r.get("result"), dict):
            r["answer_text"] = ", ".join("%s = %s" % (k, ("{:,}".format(v) if isinstance(v, int) else "{:,.2f}".format(v).rstrip("0").rstrip("."))
                                         if isinstance(v, (int, float)) and not isinstance(v, bool) else v) for k, v in r["result"].items())
            r["say"] = "Copy the numbers from answer_text exactly."
    if fx: hub._log({"type": "repair", "cell": name, "model": model, "guide": g["id"], "fixes": fx, "status": r["status"]})
    return r
