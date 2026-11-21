def cell_executor(inp):
    extra = sorted(str(k) for k in inp if k not in ("words",))
    if extra:
        raise ValueError("unknown input %s; use words" % extra[:3])
    ws = inp.get("words")
    if not isinstance(ws, list) or not ws or not all(w is None or (isinstance(w, str) and w.strip()) for w in ws):
        raise ValueError("pass words: the time words that need 오전/오후 (null for a time that was read)")
    ask = [w for w in ws if w is not None]
    if not ask:
        return {"answer_ready": True, "asks": []}
    return {"answer_ready": False, "asks": ["말씀하신 %s, 오전인가요 오후인가요?" % ", ".join("'%s'" % a for a in ask)]}
