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
_ALONE = ("혼자", "혼자서", "혼밥", "나혼자")
def _people(words):
    s = norm(words)
    if s in _ALONE or s.rstrip("요") in _ALONE or s.rstrip("이요") in _ALONE:
        return 1
    s = re.sub(r"(이서요|이서|서요|이에요|이요|명이요|명이서|명|사람|인분|인이요|인)$", "", s)
    return amount(s)[0] if s else None
_PCOUNT = r"(\d+|%s|[일이삼사오육칠팔구십]+)" % NATIVE_RE
_BARE = "|".join(["(?:%s)(?:하나|둘|셋|넷|다섯|여섯|일곱|여덟|아홉)?" % "|".join(w for w, n in _TENS), "둘|셋|넷|다섯|여섯|일곱|여덟|아홉"])
_PWORD = re.compile(r"(?<![가-힣\d])(?:%s\s*(?:명|사람|분(?!\s*(?:걸|남|뒤|후|동안|정도|만에)))|(%s)(?:이(?:서|고|요|에요|예요|라|면|니까|인데|$|(?=\s))|인데)|(\d+)\s*인(?!분))|(혼자|혼밥)|(?<![가-힣\d])(%s|하나)(?=\s|$|[,.?!]|요|인데)" % (_PCOUNT, _BARE, _BARE))   # last: a bare count word ('어른 셋 아이 둘이요') also counts
_NEG = re.compile(r"^\s*(?:\S+\s*){0,2}?(?:아니|아닌|말고)")
_MORE = re.compile(r"(?:이랑|랑|하고|와|과)\s*(?:저|나|제가|내가)(?:요|도|까지|$|\s)|(?:명|이|분|사람|둘|셋|넷|다섯|여섯|일곱|여덟|아홉)\s*더|더\s*(?:와|올|오|있)")
# words that change what a number of people means: a range, people added or taken away, a correction, 'only two of us'.
# With one of these the part never gives a number: it asks (reading the number alone would be a quiet wrong answer).
_CHANGE = re.compile("|".join((
    r"\d\s*[~∼\-–]\s*\d|[~∼]",                                       # '2~3명'
    r"추가|빠지|빠졌|빠져|빼고|빼면|제외|안\s*먹|못\s*먹|안\s*와|못\s*와|안\s*오|못\s*오|늦게|나중에\s*와|따로",   # people added or taken away
    r"아니|아닌|말고|대신|정정|잘못",                                          # a correction or a taken-back word
    r"(?:명|분|사람|이|둘|셋|넷|다섯|여섯|일곱|여덟|아홉|하나|\d)\s*만(?=\s|$|[,.?!]|요|이요|먹|있)",   # '둘만', '두 명만 먹어요'
    r"(?:하나|둘|셋|넷|다섯|여섯|일곱|여덟|아홉|명|분)\s*에\s*(?:하나|둘|셋|넷|다섯|여섯|일곱|여덟|아홉|\d|한|두|세|네)",   # '둘에 둘'
    r"(?:하나|둘|셋|넷|다섯|여섯|일곱|여덟|아홉|명|분|사람)\s*(?:이랑|랑|하고|와|과)?\s*(?:아이|애기|아기|어린이|애)\s*(?:하나|둘|셋|\d|한|두|세)",   # adults and children told apart
)))
def _scan(q):
    """How many people the customer said, read from their whole sentence: '넷이서', '두 명', '혼자', '4인', and where it stands.
    A bare count word counts too ('어른 셋 아이 둘이요' has two numbers, so the cell asks). A number the customer takes back ('혼자 온 건 아니고') does not count. None when it says nothing about it, says two different
    numbers, or adds people on top ('친구 셋이랑 저요', '두 명 더 와요'): then the cell asks instead of adding up."""
    t = str(q)
    if _MORE.search(t):
        return None, []
    got = set(); at = []
    for m in _PWORD.finditer(t):
        if _NEG.match(t[m.end():]):
            continue
        at.append((len(norm(t[:m.start()])), len(norm(t[:m.end()]))))
        if m.group(4):
            got.add(1); continue
        w = m.group(1) or m.group(2) or m.group(3) or m.group(5)
        try:
            v = amount(w)[0]
        except ValueError:
            return None, at
        if v:
            got.add(v)
    return (got.pop() if len(got) == 1 else None), at
_ASK = "몇 분이 드실 건가요?"
def cell_executor(inp):
    q = inp.get("question")
    if not isinstance(q, str) or not q.strip():
        raise ValueError("pass question: the customer's whole sentence, unchanged")
    extra = sorted(str(k) for k in inp if k not in ("question", "people"))
    if extra:
        raise ValueError("unknown input %s; use question, people" % extra[:3])
    if _CHANGE.search(q):   # the number's meaning changes (a range, more or fewer people, a correction): ask, never guess
        return {"answer_ready": False, "asks": [_ASK], "people": None, "spans": []}
    n, at = _scan(q)
    p = inp.get("people")
    if n is None and isinstance(p, str) and p.strip() and found(p, q):   # the cell found nothing itself: try the model's words
        try:
            n = _people(p)
        except ValueError:
            n = None
        at = spots(p, q)[:1] if n else at
    if not n:
        return {"answer_ready": False, "asks": [_ASK], "people": n, "spans": []}
    return {"answer_ready": True, "asks": [], "people": n, "spans": [[a, b] for a, b in sorted(set(at))]}
