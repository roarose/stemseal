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
def _eun(w):
    """'은' after a final consonant, '는' otherwise (so the question to the customer reads naturally)."""
    ch = w.rstrip("'\" )")[-1:] if w else ""
    return "은" if ch and "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 else "는"
_WON = re.compile(r"[\d일이삼사오육칠팔구십백천만,.]*[\d일이삼사오육칠팔구십백천만]\s*원(?:짜리)?")
_UNITS = "|".join(COUNTERS + ("통", "번", "가지", "사람", "봉지", "박스", "배"))
_LEFT = re.compile("|".join((   # a number word that could be a count: if one is left over, the cell does not guess
    r"\d",
    r"한두|두세(?!요)|두셋|서너|세네|네다섯|너댓|대여섯|예닐곱|두어|몇|여러|하나|둘|셋(?!트)|(?<!터)넷|다섯|여섯|일곱|여덟|아홉|스물|스무|서른|마흔|예순|일흔|여든|아흔",
    r"(?<![가-힣])(?:열|쉰)(?![가-힣])|(?<![가-힣])(?:열|쉰)(?=[한두세네하둘셋넷다여일아]|요|이|에|로|씩|%s)" % _UNITS,
    r"(?<![가-힣])(?:한(?!\s*번)|두|세|석|너|네|[일이삼사오육칠팔구십백천만]+)\s*(?:%s)" % _UNITS,
    r"(?<!\S)(?:한(?!\s*번)|두|세|석|일|삼|사|육|칠|팔|구|십)(?:요|이요|개)?(?=\s|$|[,.?!~])")))
# word lists: pieces whose meaning plainly does not touch a count, a price or whether something is ordered. Never 더, 추가, 빼, 말고, 반 and the like.
_ORDER_WORDS = ("요", "이요", "예요", "이에요", "에요", "입니다", "이랑", "랑", "하고", "이고", "고", "와", "과", "도", "은", "는", "을", "를", "이", "가", "에", "에다", "에다가", "로", "으로", "만", "짜리", "주세요", "주시고", "줘", "주실래요", "할게요", "할께요", "해", "해요", "부탁해요", "부탁드려요", "부탁합니다", "드릴게요", "시킬게요", "주문", "주문할게요", "갈게요", "먹고", "가져갈게요", "그리고", "포장", "포장해", "포장할게요", "그냥", "일단", "우선", "얼마", "얼마예요", "얼마에요", "얼마죠", "얼마인가요", "여기요", "저기요", "사장님", "총", "다해서", "전부해서", "합쳐서", "인데", "인데요")   # menu order: the list of menu_order_total 8.0, word for word
_PRICED_WORDS = _ORDER_WORDS + ("있어요", "있는데", "있는데요", "있고", "해서", "주문하는데", "주문하는데요")   # priced order: the list of order_total 9.0 (a customer who says the price is ordering)
LISTS = {"order": {"words": _ORDER_WORDS, "count": "'%s'%s 어느 메뉴의 수량인지 다시 말씀해 주시겠어요?", "other": "'%s'%s 잘 알아듣지 못했어요. 주문을 다시 한번 말씀해 주시겠어요?"},
         "order_refuse": {"words": _PRICED_WORDS, "refuse": True,   # for a step that refuses instead of asking (the caller asks the customer)
                          "count": "the customer said '%s' but no item uses it as its count; give each item its qty in the customer's words, or ask the customer if it is unclear",
                          "other": "the cell cannot read '%s' in the customer's words; if it is a dish, pass it as that item's name, exactly as said; otherwise ask the customer or hand over to staff"}}
_SUFFIX = ("이", "가", "도", "고", "만", "은", "는", "을", "를", "와", "과", "에", "로", "요")   # one-syllable pieces allowed only right after something read, never standing alone ('콜라 이' is not '콜라이')
_YES = ("네", "예", "넵")   # allowed only as the sentence's first word
def _left_words(q, used, ign):
    """Principle: read the whole sentence, and compute only when nothing unknown is left. Dish names (or prices), counts and
    discounts are used up; every piece left must be made of words on the ignore list (particles, '주세요', '포장' ...).
    Returns the pieces that are not, in the customer's words; the cell does not guess what they mean."""
    t, gaps = _flat(q)
    lt = "".join((" " if gaps[i] else "") + ("|" if any(a <= i < b for a, b in used) else t[i]) for i in range(len(t)))
    lt = _WON.sub("|", lt)   # a price ('7천원짜리') is read by the menu or the item, not a word to understand
    out = []; first = True
    for m in re.finditer(r"[가-힣0-9a-z]+(?: [가-힣0-9a-z]+)*", lt):   # words between two things the cell read ('다 해서요')
        w = m.group(); j = w.replace(" ", ""); alone = m.start() == 0 or lt[m.start() - 1] != "|"
        ok = bool(ign.fullmatch(j)) and not (alone and j in _SUFFIX)
        if first and alone and "|" not in lt[:m.start()]:
            y = w.split(" ")[0]
            ok = ok or (y in _YES and (y == j or bool(ign.fullmatch(j[len(y):]))))
        first = False
        if not ok:
            ws = w.split(" "); bad = [i for i, x in enumerate(ws) if not ign.fullmatch(x) or (i == 0 and alone and x in _SUFFIX)] or [0, len(ws) - 1]
            w = " ".join(ws[bad[0]:bad[-1] + 1])   # the customer's words from the first to the last piece not understood
            if w not in out:
                out.append(w)
    return out
def _spans(v, n):
    if not isinstance(v, list):
        raise ValueError("pass used: a list of [start, end] spans, every part of the question the other steps read")
    out = []
    for s in v:
        if s == []:
            continue
        if isinstance(s, list) and s and all(isinstance(x, list) for x in s):   # a list of span lists, one per step
            out += _spans(s, n); continue
        if not (isinstance(s, list) and len(s) == 2 and all(isinstance(x, int) and not isinstance(x, bool) for x in s) and 0 <= s[0] <= s[1] <= n):
            raise ValueError("each used span is [start, end] in the question with spaces taken out")
        out.append((s[0], s[1]))
    return out
def cell_executor(inp):
    q = inp.get("question")
    if not isinstance(q, str) or not q.strip():
        raise ValueError("pass question: the customer's whole sentence, unchanged")
    extra = sorted(str(k) for k in inp if k not in ("question", "used", "list"))
    if extra:
        raise ValueError("unknown input %s; use question, used, list" % extra[:3])
    lst = inp.get("list", "order")
    if lst not in LISTS:
        raise ValueError("list must be one of %s" % sorted(LISTS))
    L = LISTS[lst]
    ign = re.compile("(?:%s)+" % "|".join(sorted(L["words"], key=len, reverse=True)))
    used = _spans(inp.get("used"), len(norm(q)))
    left = _left_words(q, used, ign); asks = []
    if left and L.get("refuse"):   # a word the cell does not know may change a count or a price: refuse rather than guess
        raise ValueError((L["count"] if _LEFT.search(left[0]) else L["other"]) % left[0])
    for w in left:   # a word the cell does not know: it may change a count or a price, so it asks
        asks.append((L["count"] if _LEFT.search(w) else L["other"]) % (w, _eun(w)))
    return {"answer_ready": not left, "left": left, "asks": asks}
