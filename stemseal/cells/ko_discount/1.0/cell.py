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
_PCT = re.compile(r"\d+(?:\.\d+)?\s*(?:%|퍼센트|프로)|[일이삼사오육칠팔구십]+\s*(?:퍼센트|프로)")
_WON_OFF = re.compile(r"[\d일이삼사오육칠팔구십백천만,.]+\s*원\s*(?:짜리\s*)?(?:\S+\s*)?(?:할인|쿠폰|깎|빼)|(?:할인|쿠폰)\S*\s*[\d일이삼사오육칠팔구십백천만,.]+\s*원(?!\s*짜리)")
_DISC_VERB = re.compile(r"\s*(?:써서|써도|쓸게요|쓰고|써요|받을게요|받고|받아요)(?=\s|[.,!?]|$)")   # '쿠폰 써서', '할인 안 받을게요': only right after a discount word, so it says nothing about a dish
_NOT_CLAIM = re.compile(r"[^.,!]{0,8}?(?:\?|없|안\s|안받|안 받|말고|됐|돼|되나|되요|되죠|가능|있나|있어요\?|있어\?|있죠)")   # '할인 돼요?', '쿠폰 없어요': a question or a no, not a discount to apply
_HALF = ("반값", "반액")
_DISC_WORD = re.compile(r"(할인|쿠폰|서비스로|서비스\s*(?:주|해)|공짜|무료|깎|에누리|반값|반액)")
def _take(v, question, what, units):
    """One value from the customer's words. Text must be in the question; a bare number must appear there as digits."""
    if isinstance(v, bool) or not isinstance(v, (str, int, float)):
        raise ValueError("%s must be the customer's words for it, e.g. %s" % (what, units[1]))
    if not found(str(v), question):
        raise ValueError("%s is not in the question; copy the customer's words exactly (like %s), do not convert or calculate" % (what, units[1]))
    n, u = amount(str(v))
    if u not in units[0]:
        base = what.split()[-1]
        raise ValueError("%s reads as a %s, not a %s; pass the words that give the %s" % (what, u or "plain number", base, base))
    return n
def _claims(rx, q):
    """Discount words the customer uses as a claim, leaving out a question or a no ('할인 돼요?', '할인 없음')."""
    return [m for m in rx.finditer(q) if not _NOT_CLAIM.match(q, m.end())]
def _token(qn, gaps, a, step):
    """The word that ends at a (step -1) or starts at a (step 1) in norm(question), as (start, end); None at a space-less edge."""
    i = a
    if step < 0:
        while i > 0 and re.match(r"[가-힣0-9a-z]", qn[i - 1]) and (i == a or not gaps[i]):
            i -= 1
        return (i, a) if i < a and (i == 0 or gaps[i] or not re.match(r"[가-힣0-9a-z]", qn[i - 1])) else None
    while i < len(qn) and re.match(r"[가-힣0-9a-z]", qn[i]) and (i == a or not gaps[i]):
        i += 1
    return (a, i) if i > a and (i == len(qn) or gaps[i] or not re.match(r"[가-힣0-9a-z]", qn[i])) else None
def cell_executor(inp):
    q = inp.get("question")
    if not isinstance(q, str) or not q.strip():
        raise ValueError("pass question: the customer's whole sentence, unchanged")
    extra = sorted(str(k) for k in inp if k not in ("question", "discount_pct", "discount_won"))
    if extra:
        raise ValueError("unknown input %s; use question, discount_pct (percent), discount_won (won)" % extra[:3])
    qn = norm(q); spent = []
    pct = inp.get("discount_pct"); won = inp.get("discount_won")
    if isinstance(pct, str) and norm(pct) in _HALF and found(pct, q):   # '반값' is 50%
        pct = 50
    else:
        pct = _take(pct, q, "discount_pct", (("%",), "'10%'")) if pct not in (None, "", 0) else None
    won = _take(won, q, "discount_won", (("원",), "'3천원'")) if won not in (None, "", 0) else None
    if pct is None and _claims(_PCT, q):   # a discount the customer said but the model left out would overcharge
        raise ValueError("the question gives a percent discount; pass it as discount_pct in the customer's words ('10%')")
    if won is None and _claims(_WON_OFF, q):
        raise ValueError("the question gives a discount in won; pass it as discount_won in the customer's words ('3천원')")
    m = _claims(_DISC_WORD, q)
    m = m[0] if m else None
    if pct is None and won is None and m:   # a discount with no amount: the total would be wrong either way
        if m.group(1) in _HALF:
            raise ValueError("the question says '%s'; pass it as discount_pct ('%s')" % (m.group(1), m.group(1)))
        raise ValueError("the customer mentions '%s' but no amount; ask the customer how much the discount is, or whether it applies" % m.group(1))
    if pct is not None or won is not None:   # the discount words that were passed, found in the words as said (spaces kept)
        spent += [(len(norm(q[:x.start()])), len(norm(q[:x.end()]))) for rx in (_PCT, _WON_OFF) for x in rx.finditer(q)]
    gaps = _flat(q)[1]
    for x in _DISC_WORD.finditer(q):   # discount talk: a question or a no, or a discount that was passed, is understood
        n = _NOT_CLAIM.match(q, x.end())
        if n or pct is not None or won is not None:
            e = n.end() if n else x.end(); v = _DISC_VERB.match(q, e)
            if v: e = v.end()
            a = len(norm(q[:x.start()])); b = len(norm(q[:e]))
            t = _token(qn, gaps, b, 1) if b < len(qn) and not gaps[b] else None
            spent.append((a, t[1] if t else b))
    return {"pct": pct or 0, "won": won or 0, "spans": [[a, b] for a, b in sorted(set(spent))]}
