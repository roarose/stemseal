def _m(v):
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 1440
def cell_executor(inp):
    extra = sorted(str(k) for k in inp if k not in ("now", "open", "close", "open_words", "close_words"))
    if extra:
        raise ValueError("unknown input %s; use now, open, close (minutes after midnight) and open_words, close_words" % extra[:3])
    n, o, c = inp.get("now"), inp.get("open"), inp.get("close")
    if not (_m(n) and _m(o) and _m(c)):
        raise ValueError("now, open and close are minutes after midnight, 0..1440 (read the customer's words with the time step first)")
    ow, cw = inp.get("open_words"), inp.get("close_words")
    if not isinstance(ow, str) or not isinstance(cw, str):
        raise ValueError("pass open_words and close_words: the customer's words for the two times (used in the question back)")
    out = {"answer_ready": False, "asks": [], "now_24h": None, "open_24h": None, "close_24h": None,
           "is_open": None, "minutes_to_close": None, "minutes_to_open": None, "long_hours": None}
    now = n % 1440; op = o % 1440; cl = c % 1440
    hhmm = lambda x: "%02d:%02d" % (x // 60, x % 60)
    out.update(now_24h=hhmm(now), open_24h=hhmm(op), close_24h=hhmm(cl))
    if op == cl:
        if o == 0 and c == 1440:
            out.update(answer_ready=True, is_open=True, minutes_to_close=None, minutes_to_open=0, long_hours=False)
            return out
        out["asks"] = ["여는 시각과 닫는 시각이 같게 들렸어요. 영업시간을 다시 한번 말씀해 주시겠어요?"]
        return out
    out["long_hours"] = (cl - op) % 1440 > 20 * 60
    if out["long_hours"]:
        out["asks"] = ["영업시간이 %s부터 다음 날 %s까지가 맞나요?" % (ow, cw)]
        return out
    is_open = (op <= now < cl) if op < cl else (now >= op or now < cl)
    out.update(answer_ready=True, is_open=is_open, minutes_to_close=(cl - now) % 1440 if is_open else 0,
               minutes_to_open=0 if is_open else (op - now) % 1440)
    return out
