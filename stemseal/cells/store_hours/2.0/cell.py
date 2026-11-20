import re
# Each word that says which half of the day it is, with the clock hours it may be followed by, and how to turn that hour into 24h.
# A word with an hour outside its range (오전 13시, 낮 7시, 밤 5시) is a contradiction: refuse, do not guess.
def _am(h):  # 오전 0~11
    return h
def _pm(h):  # 오후 12~11, pm
    return h if h == 12 else h + 12
_MARKS = {
    "오전": (range(0, 12), _am),
    "am": (range(1, 13), lambda h: 0 if h == 12 else h),
    "아침": (range(5, 12), _am),
    "새벽": (list(range(0, 7)) + [12], lambda h: 0 if h == 12 else h),
    "오후": (range(1, 13), _pm),
    "pm": (range(1, 13), _pm),
    "낮": ([11, 12, 1, 2, 3, 4, 5], lambda h: h if h >= 11 else h + 12),
    "저녁": (range(5, 12), lambda h: h + 12),
    "밤": ([7, 8, 9, 10, 11, 12, 1, 2, 3, 4], lambda h: 0 if h == 12 else (h if h <= 4 else h + 12)),
}
_ASK = ("ask the customer: %s is %s. Ask whether it is 오전 or 오후 (am or pm) and call again with that word, "
        "e.g. '오후 9시'. Do not guess the half of the day.")
def _m(t, key):
    """Minutes after midnight (0..1440; 1440 only for an explicit 24:00 / 24시). Never echoes the caller's text in an error."""
    if not isinstance(t, str) or not t.strip():
        raise ValueError("%s must be a time like '20:20' or '오후 8시 20분'" % key)
    s = t.strip().lower().replace(" ", "")
    if s in ("자정", "밤12시", "0시", "00시"):
        return 0
    if s in ("24시", "24:00"):
        return 1440
    if s in ("정오", "낮12시"):
        return 720
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
    if m:  # HH:MM is read as 24h, as the contract says
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 24 or mi > 59 or (h == 24 and mi):
            raise ValueError("%s is out of range (00:00..24:00)" % key)
        return h * 60 + mi
    m = re.fullmatch(r"(오전|오후|아침|저녁|밤|새벽|낮|am|pm)?(\d{1,2})(시(?:(\d{1,2})분?|(반))?|:(\d{2}))?(am|pm)?", s)
    if not m or (m.group(1) and m.group(7)) or not (m.group(1) or m.group(7) or (m.group(3) or "").startswith("시")):
        raise ValueError("%s: cannot read this time; use '20:20' or '오후 8시 20분'" % key)
    mark = m.group(1) or m.group(7) or ""
    h = int(m.group(2))
    mi = 30 if m.group(5) else int(m.group(4) or m.group(6) or 0)
    if mi > 59:
        raise ValueError("%s: minutes must be 0..59" % key)
    if not mark:
        if 13 <= h <= 23:   # "21시" can only be one time
            return h * 60 + mi
        if h == 24 and mi == 0:
            return 1440
        if h == 0:
            return mi
        raise ValueError(_ASK % (key, "a clock hour without 오전/오후 (am/pm)"))
    ok, conv = _MARKS[mark]
    if h not in ok:
        raise ValueError(_ASK % (key, "a half-of-day word that does not fit its hour (like 오전 13시 or 저녁 12시)"))
    return conv(h) * 60 + mi
def cell_executor(inp):
    raw_op = _m(inp.get("open"), "open")
    raw_cl = _m(inp.get("close"), "close")
    now = _m(inp.get("now"), "now") % 1440
    op, cl = raw_op % 1440, raw_cl % 1440
    hhmm = lambda x: "%02d:%02d" % (x // 60, x % 60)
    base = {"now_24h": hhmm(now), "open_24h": hhmm(op), "close_24h": hhmm(cl)}
    if op == cl:
        if raw_op == 0 and raw_cl == 1440:   # only '00:00'~'24:00' says open all day
            base.update(is_open=True, minutes_to_close=None, minutes_to_open=0)
            return base
        raise ValueError("open and close are the same time. If the store is open 24 hours, pass open '00:00' and close '24:00'; "
                         "otherwise ask the customer for the real hours.")
    is_open = (op <= now < cl) if op < cl else (now >= op or now < cl)
    if is_open:
        base.update(is_open=True, minutes_to_close=(cl - now) % 1440, minutes_to_open=0)
    else:
        base.update(is_open=False, minutes_to_close=0, minutes_to_open=(op - now) % 1440)
    return base
