# --- korean reader 3 begin (shared, byte-identical in the cells that read a customer's own words; tests/test_reader.py checks) ---
import re
from fractions import Fraction
_SINO = {"영": 0, "공": 0, "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "륙": 6, "칠": 7, "팔": 8, "구": 9}
_SMALL = {"십": 10, "백": 100, "천": 1000}
_BIG = {"만": 10000, "억": 100000000}
_TENS = [("스무", 20), ("스물", 20), ("서른", 30), ("마흔", 40), ("쉰", 50), ("예순", 60), ("일흔", 70), ("여든", 80), ("아흔", 90), ("열", 10)]
_ONES = [("아홉", 9), ("여덟", 8), ("일곱", 7), ("여섯", 6), ("다섯", 5),
         ("하나", 1), ("한", 1), ("둘", 2), ("두", 2), ("셋", 3), ("세", 3), ("석", 3), ("넷", 4), ("네", 4), ("너", 4)]
_NATIVE = _TENS + _ONES
NATIVE_RE = "(?:%s)(?:%s)?|%s" % ("|".join(w for w, n in _TENS), "|".join(w for w, n in _ONES), "|".join(w for w, n in _ONES))   # a native count word, 1 to 99
COUNTERS = ("인분", "그릇", "공기", "접시", "세트", "마리", "조각", "잔", "개", "병", "캔", "판", "장", "컵", "줄", "팩", "명", "인")
_TAIL = re.compile(r"(짜리|씩|이요|요|이에요|예요|입니다)+$")
def norm(s):
    """Spaces out; a comma only as a thousands mark (4,500 -> 4500), so '25:00,10:00' stays two times."""
    return re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", re.sub(r"\s", "", str(s))).lower()
def sino(s):
    """'만이천구백' 12900, '9천5백' 9500, '2만3천' 23000, '1.5만' 15000, '12,900' 12900. Whole numbers only; None if it is not a number."""
    s = norm(s)
    if not s:
        return None
    if re.fullmatch(r"\d+", s):
        return int(s)
    total = 0; sec = 0; num = None; last_small = 10 ** 9; last_big = 10 ** 18
    for tok in re.findall(r"\d+(?:\.\d+)?|.", s):
        if tok[0].isdigit() or tok in _SINO:
            if num is not None:
                return None
            num = Fraction(tok) if tok[0].isdigit() else Fraction(_SINO[tok])
        elif tok in _SMALL:
            u = _SMALL[tok]
            if u >= last_small:
                return None
            sec += (num if num is not None else 1) * u; num = None; last_small = u
        elif tok in _BIG:
            u = _BIG[tok]
            if u >= last_big:
                return None
            sec += num if num is not None else 0
            total += (sec if sec else 1) * u; sec = 0; num = None; last_small = 10 ** 9; last_big = u
        else:
            return None
    total += sec + (num if num is not None else 0)
    return int(total) if total.denominator == 1 else None
def native(s):
    """'두' 2, '열두' 12, '스물셋' 23, '서른다섯' 35, '아흔아홉' 99 (counting words); None otherwise."""
    s = norm(s); v = 0
    for w, n in _TENS:
        if s.startswith(w):
            v = n; s = s[len(w):]; break
    if not s:
        return v or None
    for w, n in _ONES:
        if s == w:
            return v + n
    return None
def amount(text):
    """Text as the customer said it -> (whole number, unit). Unit: '원', a counter ('잔', '인분' ...), '%', or ''.
    '만이천구백원' (12900, '원'), '두 잔' (2, '잔'), '10%' (10, '%'), '4,500' (4500, ''). Raises ValueError when it cannot read it."""
    s = _TAIL.sub("", norm(text))
    unit = ""
    for u in ("퍼센트", "프로", "%", "원") + COUNTERS:
        if s.endswith(u) and len(s) > len(u):
            unit = "%" if u in ("퍼센트", "프로") else u; s = s[:-len(u)]; break
    v = native(s) if unit not in ("원", "%") else None
    if v is None:
        v = sino(s)
    if v is None:
        raise ValueError("cannot read this amount; pass the customer's words for it exactly as written, e.g. '만이천구백원' or '두 잔'")
    return v, unit
_NUMCH = set("0123456789.영공일이삼사오육륙칠팔구십백천만억")
def _flat(s):
    """norm(s) plus, for each kept character, whether a space stood before it in the customer's words."""
    chars = []; gaps = []; gap = False
    for c in str(s).lower():
        if c.isspace():
            gap = True; continue
        chars.append(c); gaps.append(gap); gap = False
    j = "".join(chars)
    drop = {m.start() for m in re.finditer(r"(?<=\d),(?=\d{3}(?!\d))", j)}
    return "".join(c for i, c in enumerate(chars) if i not in drop), [g for i, g in enumerate(gaps) if i not in drop] + [True]
def spots(fragment, question):
    """Where the fragment stands in the customer's words, as (start, end) in norm(question). A match must not start or end
    inside a longer number: '오백원' is not in '삼천오백원', '1시' is not in '11시'. A space counts as a boundary between
    Korean number words ('이 만원'), never between digits."""
    f = norm(fragment); q, gaps = _flat(question); out = []
    if not f:
        return out
    for m in re.finditer("(?=%s)" % re.escape(f), q):
        a = m.start(); b = a + len(f)
        if a > 0 and f[0] in _NUMCH and q[a - 1] in _NUMCH and (not gaps[a] or (f[0].isdigit() and q[a - 1].isdigit())):
            continue
        if b < len(q) and f[-1] in _NUMCH and q[b] in _NUMCH and (not gaps[b] or (f[-1].isdigit() and q[b].isdigit())):
            continue
        out.append((a, b))
    return out
def found(fragment, question):
    """Is the fragment really in the customer's words (spaces and thousands commas ignored, not inside a longer number)?"""
    return bool(spots(fragment, question))
# --- korean reader 3 end ---
# half-of-day word -> clock hours it may take, and how that hour becomes 24h (same table as store_hours 2.0)
_MARKS = {
    "오전": (range(0, 12), lambda h: h), "am": (range(1, 13), lambda h: 0 if h == 12 else h), "아침": (range(5, 12), lambda h: h),
    "새벽": (list(range(0, 7)) + [12], lambda h: 0 if h == 12 else h), "오후": (range(1, 13), lambda h: h if h == 12 else h + 12),
    "pm": (range(1, 13), lambda h: h if h == 12 else h + 12), "낮": ([11, 12, 1, 2, 3, 4, 5], lambda h: h if h >= 11 else h + 12),
    "저녁": (range(5, 12), lambda h: h + 12), "밤": ([7, 8, 9, 10, 11, 12, 1, 2, 3, 4], lambda h: 0 if h == 12 else (h if h <= 4 else h + 12)),
}
class Ask(Exception):
    pass
def _hour(s):
    v = native(s)
    return v if v is not None else sino(s)
def _clock(t, key):
    """Customer's words for one time -> minutes after midnight (1440 only for 24:00/24시). Raises Ask when only the customer can say."""
    s = _TAIL.sub("", norm(t))
    if s in ("자정", "밤12시", "0시", "영시"):
        return 0
    if s in ("24시", "24:00", "스물네시"):
        return 1440
    if s in ("정오", "낮12시"):
        return 720
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 24 or mi > 59 or (h == 24 and mi):
            raise ValueError("%s is out of range (00:00..24:00)" % key)
        if len(m.group(1)) == 1 and h:
            raise Ask(key)
        return h * 60 + mi
    m = re.fullmatch(r"(오전|오후|아침|저녁|밤|새벽|낮|am|pm)?(.+?)시(?:(.+?)분|(반))?(am|pm)?", s) or \
        re.fullmatch(r"(오전|오후|아침|저녁|밤|새벽|낮|am|pm)?(\d{1,2})()()(am|pm)", s)
    if not m or (m.group(1) and m.group(5)):
        raise ValueError("%s: cannot read this time; pass the customer's words for it, e.g. '밤 7시 반' or '19:30'" % key)
    h = _hour(m.group(2)); mi = 30 if m.group(4) else (sino(m.group(3)) if m.group(3) else 0)
    if h is None or mi is None or h > 24 or mi > 59:
        raise ValueError("%s: cannot read this time; pass the customer's words for it, e.g. '밤 7시 반' or '19:30'" % key)
    mark = m.group(1) or m.group(5) or ""
    if not mark:
        if 13 <= h <= 23 or h == 0:
            return h * 60 + mi
        if h == 24 and mi == 0:
            return 1440
        raise Ask(key)
    ok, conv = _MARKS[mark]
    if h not in ok:
        raise Ask(key)
    return conv(h) * 60 + mi
_WHAT = {"now": "지금 시각", "open": "여는 시각", "close": "닫는 시각"}
_MARK = r"(?:오전|오후|아침|저녁|밤|새벽|낮|am|pm)"
_HOURW = [("열두", 12), ("열한", 11), ("열", 10), ("아홉", 9), ("여덟", 8), ("일곱", 7), ("여섯", 6), ("다섯", 5), ("네", 4), ("세", 3), ("두", 2), ("한", 1)]
_BEFORE = "(?:^|(?<=[^가-힣])|(?<=오전)|(?<=오후)|(?<=아침)|(?<=저녁)|(?<=밤)|(?<=새벽)|(?<=낮))"
def _canon(s):
    """Spoken hours and minutes as digits ('여덟 시 사십 분' -> '8시40분'), spaces out, so a model that wrote the same
    time in digits still finds the customer's words. Only the form changes, never the value."""
    s = str(s).lower()
    for w, n in _HOURW:
        s = re.sub(_BEFORE + w + r"\s*시", "%d시" % n, s)
    s = re.sub(r"(?<=시)(\s*)([일이삼사오육칠팔구십]+)\s*분", lambda m: m.group(1) + ("%s분" % sino(m.group(2)) if sino(m.group(2)) is not None else m.group(0)), s)
    s = re.sub(r"(?<!\d)(\d{2}):(\d{2})(?!\d)", lambda m: "%d시" % int(m.group(1)) + ("%d분" % int(m.group(2)) if int(m.group(2)) else "") if int(m.group(1)) >= 13 else m.group(0), s)
    return norm(s)
_OPENW = ("열고", "열어", "열었", "연다", "열면", "여는", "열죠", "열어요", "오픈", "부터", "시작")
_CLOSEW = ("닫", "마감", "까지", "끝")
def _role(q, a, b):
    """'open' or 'close' when the words right after this time (up to the next time) or just before it say so, else None."""
    after = re.split(r"\d|%s" % _MARK, q[b:b + 8])[0]; hits = []
    for words, r in ((_OPENW, "open"), (_CLOSEW, "close")):
        for w in words:
            i = after.find(w)
            if i >= 0:
                hits.append((i, r))
    if hits:
        return min(hits)[1]
    before = q[max(0, a - 3):a]
    return "close" if "마감" in before else ("open" if "오픈" in before else None)
def _locate(v, q, key):
    """The customer's own words for this time, read from the question. The model's fragment may add or change the
    half-of-day word ('오후 11시' for '11시'); the question's word wins, and with none there the customer is asked.
    Returns None when the time is not in the question. Raises ValueError when it stands where the other role is said."""
    qc = _canon(q); vc = _canon(v)
    m = re.fullmatch("(%s)?(.+)" % _MARK, vc)
    core = m.group(2) if m and m.group(1) and m.group(2) else vc
    hits = []
    for a, b in spots(core, qc):
        if re.match(r"(\d{1,2}|[일이삼사오육칠팔구십]+)분|반|:\d", qc[b:]) and not re.search(r"(분|반)$", core):
            continue
        mk = re.search("%s$" % _MARK, qc[:a])
        words = (mk.group(0) if mk else "") + core
        hits.append((words, _role(qc, a - (len(mk.group(0)) if mk else 0), b)))
    if not hits:
        return None
    if key != "now":
        other = "close" if key == "open" else "open"
        fit = [h for h in hits if h[1] != other]
        if not fit:
            raise ValueError("%s looks swapped: open is the time said with 열/오픈/부터, close the one with 닫/마감/까지; pass them again" % key)
        hits = fit
    exact = [h for h in hits if h[0] == vc]
    return (exact or hits)[0][0]
def cell_executor(inp):
    q = inp.get("question")
    if not isinstance(q, str) or not q.strip():
        raise ValueError("pass question: the customer's whole sentence, unchanged")
    clock = inp.get("now_from_clock") is True
    extra = sorted(str(k) for k in inp if k not in ("question", "now", "open", "close", "now_from_clock"))
    if extra:
        raise ValueError("unknown input %s; use question, now, open, close (and now_from_clock)" % extra[:3])
    got = {}; ask = []; said = {}
    for key in ("now", "open", "close"):
        v = inp.get(key)
        if not isinstance(v, str) or not v.strip():
            raise ValueError("pass %s: the customer's words for it, e.g. '밤 7시 반'" % key)
        if key == "now" and clock:
            if not re.fullmatch(r"\d{2}:\d{2}", v.strip()):
                raise ValueError("now from the clock must be 24h HH:MM, e.g. '19:30'")
        else:
            w = _locate(v, q, key)
            if w is None:
                raise ValueError("%s is not in the question; copy the customer's words for it exactly (like '밤 7시 반'), do not convert" % key)
            if w != _canon(v):
                v = w
        said[key] = v.strip()
        try:
            got[key] = _clock(v, key)
        except Ask:
            ask.append(v.strip())
    out = {"answer_ready": False, "ask_customer": None, "now_24h": None, "open_24h": None, "close_24h": None,
           "is_open": None, "minutes_to_close": None, "minutes_to_open": None, "long_hours": None}
    if ask:
        out["ask_customer"] = "말씀하신 %s, 오전인가요 오후인가요?" % ", ".join("'%s'" % a for a in ask)
        return out
    now = got["now"] % 1440; op = got["open"] % 1440; cl = got["close"] % 1440
    hhmm = lambda x: "%02d:%02d" % (x // 60, x % 60)
    out.update(now_24h=hhmm(now), open_24h=hhmm(op), close_24h=hhmm(cl))
    if op == cl:
        if got["open"] == 0 and got["close"] == 1440:
            out.update(answer_ready=True, is_open=True, minutes_to_close=None, minutes_to_open=0, long_hours=False)
            return out
        out["ask_customer"] = "여는 시각과 닫는 시각이 같게 들렸어요. 영업시간을 다시 한번 말씀해 주시겠어요?"
        return out
    out["long_hours"] = (cl - op) % 1440 > 20 * 60
    if out["long_hours"]:
        out["ask_customer"] = "영업시간이 %s부터 다음 날 %s까지가 맞나요?" % (said["open"], said["close"])
        return out
    is_open = (op <= now < cl) if op < cl else (now >= op or now < cl)
    out.update(answer_ready=True, is_open=is_open, minutes_to_close=(cl - now) % 1440 if is_open else 0,
               minutes_to_open=0 if is_open else (op - now) % 1440)
    return out
