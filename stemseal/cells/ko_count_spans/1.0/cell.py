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
# --- korean counts 1 begin (shared, byte-identical in the cells that find count words; tests/test_reader.py checks) ---
_QCNT = "|".join(sorted([c for c in COUNTERS if c not in ("명", "인")], key=len, reverse=True))   # order counters; '명', '분', '인' count people
_BARE = "(?:%s)(?:%s)?|%s" % ("|".join(w for w, n in _TENS), "하나|둘|셋|넷|다섯|여섯|일곱|여덟|아홉", "하나|둘|셋|넷|다섯|여섯|일곱|여덟|아홉")
_END = r"(?=$|[^가-힣0-9a-z]|요|이요|에|로|으로|인데|만|씩|이랑|랑|하고|이고|주세요|줘|더)"   # '둘에요', '둘로 할게요', '둘에 콜라 둘'
_QX = re.compile("|".join((   # a count word with its counter first, so '두 세트' is two sets, not the range '두세'
    r"(?P<num>\d+)(?P<c1>%s)" % _QCNT,
    r"(?P<nat>%s)(?P<c2>%s)" % (NATIVE_RE, _QCNT),
    r"(?P<sino>[일이삼사오육칠팔구십백천만]+)(?P<c3>%s)" % _QCNT,
    r"(?P<approx>(?:한두|두세|두셋|서너|세네|네다섯|너댓|대여섯|예닐곱|두어)(?:%s)?|(?:몇|여러|반)(?:%s))" % (_QCNT, _QCNT),
    r"(?P<bare>%s)%s" % (_BARE, _END),
    r"(?P<digits>\d+)(?=$|[^가-힣0-9a-z]|요|이요|만|씩|이랑|랑|하고|이고|주세요|(?:%s)(?:%s))" % (NATIVE_RE, _QCNT),
    r"(?P<spaced>%s)" % _BARE)))   # '하나 주시고', '셋 부탁해요': a count word with a space after it (kept only then)
_SKIP = re.compile(r"(?:으로|로|를|을|는|은|도|이(?!인분)|가|[\d일이삼사오육칠팔구십백천만]+원(?:짜리)?|(?:%s|\d+)(?:명|사람)?이서|(?:%s|\d+)(?:명|사람)|추가로|추가|꼭|딱|더|각각|각|총|모두|다(?!섯))*" % (NATIVE_RE, NATIVE_RE))   # between a name and its count: particles, a price, who it is for, '추가', '꼭', '각각'
def _qty_after(rest):
    """The customer's words for how many, right after a name: '두병', '3인분', '하나'. None when there are none."""
    m = _QX.match(rest, _SKIP.match(rest).end())
    return m.group(0) if m else None
def _eun(w):
    """'은' after a final consonant, '는' otherwise (so the question to the customer reads naturally)."""
    ch = w.rstrip("'\" )")[-1:] if w else ""
    return "은" if ch and "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 else "는"
def _show(q, a, b):
    """The customer's own words for positions a..b of norm(q), with their spaces back."""
    t, gaps = _flat(q)
    return "".join((" " if gaps[i] and i > a else "") + t[i] for i in range(a, b))
# --- korean counts 1 end ---
_EACH = re.compile(r"각각|각(?!자)")
_ALL = re.compile(r"총|모두|다(?!섯)")
_PEOPLE = re.compile(r"(?:%s|\d+)(?:명|사람|번)|(?<!인)(?:%s|\d+)분|(?:둘|셋|넷|다섯|여섯|일곱|여덟|아홉|열)이서" % (NATIVE_RE, NATIVE_RE))
_PEOPLE_SAID = re.compile(r"(?:%s|\d+)\s*(?:명|사람|분)(?:이서|이|서)?|(?:둘|셋|넷|다섯|여섯|일곱|여덟|아홉|열)이서" % NATIVE_RE)
# words right after a thing and its count that change what was read: taken away, cancelled, corrected, half more, more.
# With one of these the part gives no number for it: it asks, even when called on its own (the unread-word step is a second net).
_CHANGE = re.compile(r"빼|빠|취소|제외|말고|아니|대신|반(?!값|찬|반)|더(?!운|워|위)|추가|두\s*배|곱하기|x\d|\*\d")
_NEXT_OK = ("요", "이요", "예요", "이에요", "에요", "입니다", "이랑", "랑", "하고", "이고", "고", "와", "과", "도", "은", "는", "을", "를", "이", "가", "에", "에다", "에다가", "로", "으로", "만", "짜리", "주세요", "주시고", "줘", "주실래요", "할게요", "할께요", "해", "해요", "부탁해요", "부탁드려요", "부탁합니다", "드릴게요", "시킬게요", "주문", "주문할게요", "갈게요", "먹고", "가져갈게요", "그리고", "포장", "포장해", "포장할게요", "그냥", "일단", "우선", "얼마", "얼마예요", "얼마에요", "얼마죠", "얼마인가요", "여기요", "저기요", "사장님", "총", "다해서", "전부해서", "합쳐서", "인데", "인데요")   # the words that may follow a thing said without a count (the menu order's list of plain words)
_NEXT_RE = re.compile("(?:%s)+" % "|".join(sorted(_NEXT_OK, key=len, reverse=True)))
def _next_word(qn, gaps, i):
    """The customer's word starting at i in norm(question): up to the next space."""
    j = i
    while j < len(qn) and not (j > i and gaps[j]):
        j += 1
    return qn[i:j]
def _count(m):
    """A count match -> (whole number or None, why not). None means ask: a range ('한두 개') or 0 or over 99."""
    if m.group("approx"):
        return None, "approx"
    v = int(m.group("num") or m.group("digits")) if (m.group("num") or m.group("digits")) else (native(m.group("nat") or m.group("bare") or m.group("spaced")) if (m.group("nat") or m.group("bare") or m.group("spaced")) else sino(m.group("sino")))
    if v is None or not 1 <= v <= 99:
        return None, "range"
    return v, None
def _owners(v, n):
    if not isinstance(v, list) or not v:
        raise ValueError("pass owners: [{start, end}] for each thing the customer named, in order (the matches of the name-finding step can be passed as they are)")
    out = []
    for o in v:
        if not isinstance(o, dict) or not all(isinstance(o.get(k), int) and not isinstance(o.get(k), bool) for k in ("start", "end")) or not 0 <= o["start"] < o["end"] <= n:
            raise ValueError("each owner is {start, end}: where its name stands in the question (positions with spaces taken out)")
        out.append({"span": (o["start"], o["end"]), "end": o["end"], "qty": None})
    return out
def cell_executor(inp):
    q = inp.get("question")
    if not isinstance(q, str) or not q.strip():
        raise ValueError("pass question: the customer's whole sentence, unchanged")
    extra = sorted(str(k) for k in inp if k not in ("question", "owners"))
    if extra:
        raise ValueError("unknown input %s; use question, owners" % extra[:3])
    qn = norm(q)
    rows = _owners(inp.get("owners"), len(qn))
    asks = []
    names = [(r["span"][0], r["end"]) for r in rows]
    masked = "".join("|" if any(a <= i < b for a, b in names) else c for i, c in enumerate(qn))
    _t, gaps = _flat(q)
    found_q = [m for m in _QX.finditer(masked) if not m.group("spaced") or (gaps[m.end()] and not re.match(r"명|사람|분|이서", masked[m.end():]))]
    used = set()
    for r in rows:   # a count right after the name ...
        sk = _SKIP.match(masked, r["end"]).end()
        for j, m in enumerate(found_q):
            if m.start() == sk and j not in used:
                r["qty"] = m; used.add(j); break
    for r in rows:   # ... or right before it ('두 개 계란말이요')
        if r["qty"] is None:
            for j, m in enumerate(found_q):
                if m.end() == r["span"][0] and j not in used:
                    r["qty"] = m; used.add(j); break
    order = sorted(range(len(rows)), key=lambda i: rows[i]["span"][0])
    for pos, i in enumerate(order):   # '계란말이랑 콜라 두 개씩': a count said 'each' covers the names listed before it without a count
        r = rows[i]; m = r["qty"]
        if m is None:
            continue
        gap = masked[r["end"]:m.start()]
        each = masked.startswith("씩", m.end()) or bool(_EACH.search(gap))
        group = []
        for k in reversed(order[:pos]):
            if rows[k]["qty"] is not None:
                break
            group.append(rows[k])
        if (each or _ALL.search(gap)) and _PEOPLE.search(qn):   # '하나씩 두 명': each of whom? the cell does not multiply
            r["unclear"] = True
            for g in group:
                g["unclear"] = True
        elif each:
            for g in group:
                g["qty"] = m
        elif _ALL.search(gap) and group:   # '계란말이랑 콜라 모두 두 개': two each, or two in all?
            r["unclear"] = True
            for g in group:
                g["unclear"] = True
    if "똑같이" in qn or "같은걸로" in qn:   # '콜라도 똑같이요': the count is somewhere else in the sentence
        for r in rows:
            if r["qty"] is None:
                r["unclear"] = True
    for j, m in enumerate(found_q):   # every count the customer said must belong to a name; otherwise a total could be short
        if j not in used:
            w = _show(q, m.start(), m.end())
            asks.append("'%s'%s 어느 메뉴의 수량인지 다시 말씀해 주시겠어요?" % (w, _eun(w)))
    spent = [(found_q[j].start(), found_q[j].end()) for j in range(len(found_q)) if j not in used]
    for r in rows:   # a name's own count and the particles between them are used up
        m = r["qty"]
        if m is not None and m.start() >= r["end"]:
            spent.append((r["end"], m.end()))
        elif m is not None and m.end() <= r["span"][0]:
            spent.append((m.start(), r["span"][0]))
        if m is not None and masked.startswith("씩", m.end()):   # '두 개씩' was read above (spread, or asked with people)
            spent.append((m.end(), m.end() + 1))
    if all(r["qty"] is not None for r in rows):   # every name has its count: '세 명이서' only says who it is for
        spent += [(m.start(), m.end()) for m in _PEOPLE_SAID.finditer(qn)]
    starts = sorted(r["span"][0] for r in rows)
    for r in rows:   # read on its own, a count can still be changed by the words after it ('두 개 빼 주세요', '두 개 반', '계란말이 너이')
        m = r["qty"]; at = max(r["end"], m.end() if m is not None else 0)
        nxt = min([s for s in starts if s >= at] + [at + 12, len(qn)])
        if _CHANGE.search(masked[at:nxt]):
            r["changed"] = True
        elif m is None and not r.get("unclear"):
            w = _next_word(masked, gaps, r["end"]).split("|")[0]
            if w and not _NEXT_RE.fullmatch(w):
                r["changed"] = True
    if any(r.get("changed") for r in rows):
        asks.append("주문하신 수량을 메뉴마다 한 번 더 말씀해 주시겠어요?")
    counts = []
    for r in rows:
        m = r["qty"]
        if m is None:
            counts.append({"value": None, "why": "unclear" if r.get("unclear") or r.get("changed") else "none", "text": None, "start": None, "end": None})
            continue
        v, why = _count(m)
        if r.get("unclear") or r.get("changed"):
            v, why = None, "unclear"
        counts.append({"value": v, "why": why, "text": _show(q, m.start(), m.end()), "start": m.start(), "end": m.end()})
    return {"answer_ready": not asks, "asks": asks, "counts": counts, "spans": [[a, b] for a, b in sorted(set(spent))]}
