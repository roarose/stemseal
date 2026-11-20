import re
def _m(t, key):
    if not isinstance(t, str):
        raise ValueError("%s must be 'HH:MM' (24h)" % key)
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", t)
    if not m:
        raise ValueError("%s must be 'HH:MM' (24h)" % key)
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 24 or mi > 59 or (h == 24 and mi != 0):
        raise ValueError("%s out of range" % key)
    return h * 60 + mi
def cell_executor(inp):
    now = _m(inp.get("now"), "now") % 1440
    op = _m(inp.get("open"), "open") % 1440
    cl = _m(inp.get("close"), "close") % 1440
    if op == cl:
        return {"is_open": True, "minutes_to_close": None, "minutes_to_open": 0}
    if op < cl:
        is_open = op <= now < cl
    else:
        is_open = now >= op or now < cl
    if is_open:
        return {"is_open": True, "minutes_to_close": (cl - now) % 1440, "minutes_to_open": 0}
    return {"is_open": False, "minutes_to_close": 0, "minutes_to_open": (op - now) % 1440}
