import re
_PM = ("오후", "저녁", "밤", "pm")
_AM = ("오전", "아침", "새벽", "am")
def _m(t, key):
    if not isinstance(t, str) or not t.strip():
        raise ValueError("%s must be a time like '20:20' or '오후 8시 20분'" % key)
    s = t.strip().lower().replace(" ", "")
    if s in ("자정", "밤12시", "0시"):
        return 0
    if s in ("정오", "낮12시"):
        return 720
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
    else:
        m = re.fullmatch(r"(오전|오후|아침|저녁|밤|새벽|낮|am|pm)?(\d{1,2})(?:(?:시|:)(?:(\d{1,2})분?|(반))?)?(am|pm)?", s)
        if not m or (not m.group(1) and not m.group(5) and "시" not in s):
            raise ValueError("%s: cannot read time %r; use '20:20' or '오후 8시 20분'" % (key, t))
        mark = m.group(1) or m.group(5) or ""
        h = int(m.group(2)); mi = 30 if m.group(4) else int(m.group(3) or 0)
        if mark in _PM and h < 12:
            h += 12
        elif mark == "낮" and h < 6:
            h += 12
        elif (mark in _AM or mark == "밤") and h == 12:
            h = 0
    if h > 24 or mi > 59 or (h == 24 and mi != 0):
        raise ValueError("%s out of range" % key)
    return h * 60 + mi
def cell_executor(inp):
    now = _m(inp.get("now"), "now") % 1440
    op = _m(inp.get("open"), "open") % 1440
    cl = _m(inp.get("close"), "close") % 1440
    hhmm = lambda x: "%02d:%02d" % (x // 60, x % 60)
    base = {"now_24h": hhmm(now), "open_24h": hhmm(op), "close_24h": hhmm(cl)}
    if op == cl:
        base.update(is_open=True, minutes_to_close=None, minutes_to_open=0); return base
    is_open = (op <= now < cl) if op < cl else (now >= op or now < cl)
    if is_open:
        base.update(is_open=True, minutes_to_close=(cl - now) % 1440, minutes_to_open=0)
    else:
        base.update(is_open=False, minutes_to_close=0, minutes_to_open=(op - now) % 1440)
    return base
