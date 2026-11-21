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
_DISC = ("discount_pct", "discount_won", "discount", "coupon")
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
_QCNT = "|".join(sorted([c for c in COUNTERS if c not in ("명", "인")], key=len, reverse=True))   # order counters; '명', '분', '인' count people
_BARE = "(?:%s)(?:%s)?|%s" % ("|".join(w for w, n in _TENS), "하나|둘|셋|넷|다섯|여섯|일곱|여덟|아홉", "하나|둘|셋|넷|다섯|여섯|일곱|여덟|아홉")
_QX = re.compile("|".join((   # a count word with its counter first, so '두 세트' is two sets, not the range '두세'
    r"\d+(?:%s)" % _QCNT, r"(?:%s)(?:%s)" % (NATIVE_RE, _QCNT), r"[일이삼사오육칠팔구십백천만]+(?:%s)" % _QCNT,
    r"(?:한두|두세|두셋|서너|세네|네다섯|너댓|대여섯|예닐곱|두어)(?:%s)?|(?:몇|여러|반)(?:%s)" % (_QCNT, _QCNT),
    r"(?:%s)(?=$|[^가-힣0-9a-z]|요|이요|에|로|으로|인데|만|씩|이랑|랑|하고|이고|주세요|줘|더)" % _BARE,   # '둘에 오천원짜리 셋', '둘로'
    r"(?P<spaced>%s)" % _BARE)))   # '만원짜리 둘 오천원짜리 셋': a count word with a space after it (kept only then, see _counts)
_GAP = re.compile(r"(?:짜리|씩|에|은|는|을|를|이|가|도|으로|로|꼭|딱|각각|각|총|모두|다(?!섯))*")
_EACH = re.compile(r"각각|각(?!자)")
_ALL = re.compile(r"총|모두|다(?!섯)")
_PEOPLE = re.compile(r"(?:%s|\d+)(?:명|사람|번)|(?<!인)(?:%s|\d+)분|(?:둘|셋|넷|다섯|여섯|일곱|여덟|아홉|열)이서" % (NATIVE_RE, NATIVE_RE))
_PEOPLE_SAID = re.compile(r"(?:%s|\d+)\s*(?:명|사람|분)(?:이서|이|서)?|(?:둘|셋|넷|다섯|여섯|일곱|여덟|아홉|열)이서" % NATIVE_RE)
_UNITS = "|".join(COUNTERS + ("통", "번", "가지", "사람", "봉지", "박스", "배"))
_LEFT = re.compile("|".join((   # a number word that could be a count: if one is left over, the cell does not guess
    r"\d",
    r"한두|두세(?!요)|두셋|서너|세네|네다섯|너댓|대여섯|예닐곱|두어|몇|여러|하나|둘|셋(?!트)|(?<!터)넷|다섯|여섯|일곱|여덟|아홉|스물|스무|서른|마흔|예순|일흔|여든|아흔",
    r"(?<![가-힣])(?:열|쉰)(?![가-힣])|(?<![가-힣])(?:열|쉰)(?=[한두세네하둘셋넷다여일아]|요|이|에|로|씩|%s)" % _UNITS,
    r"(?<![가-힣])(?:한(?!\s*번)|두|세|석|너|네|[일이삼사오육칠팔구십백천만]+)\s*(?:%s)" % _UNITS,
    r"(?<!\S)(?:한(?!\s*번)|두|세|석|일|삼|사|육|칠|팔|구|십)(?:요|이요|개)?(?=\s|$|[,.?!~])")))
# words right after a thing and its count that change what was read: taken away, cancelled, corrected, half more, more.
# With one of these the part gives no number for it: it asks, even when called on its own (the unread-word step is a second net).
_CHANGE = re.compile(r"빼|빠|취소|제외|말고|아니|대신|반(?!값|찬|반)|더(?!운|워|위)|추가|두\s*배|곱하기|x\d|\*\d")
_NEXT_OK = ("요", "이요", "예요", "이에요", "에요", "입니다", "이랑", "랑", "하고", "이고", "고", "와", "과", "도", "은", "는", "을", "를", "이", "가", "에", "에다", "에다가", "로", "으로", "만", "짜리", "주세요", "주시고", "줘", "주실래요", "할게요", "할께요", "해", "해요", "부탁해요", "부탁드려요", "부탁합니다", "드릴게요", "시킬게요", "주문", "주문할게요", "갈게요", "먹고", "가져갈게요", "그리고", "포장", "포장해", "포장할게요", "그냥", "일단", "우선", "얼마", "얼마예요", "얼마에요", "얼마죠", "얼마인가요", "여기요", "저기요", "사장님", "총", "다해서", "전부해서", "합쳐서", "인데", "인데요", "있어요", "있는데", "있는데요", "있고", "해서", "주문하는데", "주문하는데요")   # the words that may follow a thing said without a count (the priced order's list of plain words)
_NEXT_RE = re.compile("(?:%s)+" % "|".join(sorted(_NEXT_OK, key=len, reverse=True)))
_OTHER_STEP = re.compile(r"[\d일이삼사오육칠팔구십백천만,.]+원|할인|쿠폰|깎|반값|반액|\d+%")   # a word the discount step reads, or the next price
def _next_word(qn, gaps, i):
    """The customer's word starting at i in norm(question): up to the next space."""
    j = i
    while j < len(qn) and not (j > i and gaps[j]):
        j += 1
    return qn[i:j]
def _counts(q, qn):
    """Every count the customer said, as (start, end) in norm(question). A bare count word followed by other words counts only with a space after it."""
    gaps = _flat(q)[1]
    return [(m.start(), m.end()) for m in _QX.finditer(qn) if not m.group("spaced") or (gaps[m.end()] and not re.match(r"명|사람|분|이서", qn[m.end():]))]
def cell_executor(inp):
    q = inp.get("question")
    if not isinstance(q, str) or not q.strip():
        raise ValueError("pass question: the customer's whole sentence, unchanged")
    extra = sorted(str(k) for k in inp if k not in ("question", "items"))
    if extra:
        raise ValueError("unknown input %s; use question, items (a discount goes to the discount step)" % extra[:3])
    items = inp.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("pass items: a list like [{\"price\": \"4500원\", \"qty\": \"두 잔\"}] with the customer's own words")
    qn = norm(q); names = []; counts = _counts(q, qn); used_counts = set(); taken = []; read = []; used = []; prices = []; qtys = []; cnt = {}; dflt = []
    def claim(frag, after=None):
        """The position of the customer's words frag, preferring one not taken yet (and the first after `after`)."""
        sp = [x for x in spots(frag, q) if x not in taken]
        if after is not None:
            sp = [x for x in sp if x[0] >= after] or sp
        if sp:
            taken.append(sp[0])
            for c in counts:
                if c[0] < sp[0][1] and sp[0][0] < c[1]:
                    used_counts.add(c)
        return sp[0] if sp else None
    for k, it in enumerate(items, 1):
        if isinstance(it, dict) and any(k in it for k in _DISC) and "price" not in it:
            raise ValueError("a discount is not an item; put it outside items, e.g. {\"items\": [...], \"discount_pct\": \"10%\"}")
        if not isinstance(it, dict) or "price" not in it:
            raise ValueError("each item must be an object like {\"price\": \"4500원\", \"qty\": \"두 잔\"}")
        if any(k in it for k in _DISC):
            raise ValueError("a discount is not part of an item; put it outside items, e.g. {\"items\": [...], \"discount_won\": \"3천원\"}")
        if set(it) - {"price", "qty", "name"}:
            raise ValueError("an item takes only price, qty and name, e.g. {\"name\": \"떡볶이\", \"price\": \"4500원\", \"qty\": \"두 개\"}")
        if "name" in it:   # the customer's words for the dish: read as a name, never as a count
            nm = it["name"]
            if not isinstance(nm, str) or not nm.strip() or not found(nm, q):
                raise ValueError("item %d name is not in the question; copy the customer's words for the dish exactly, or leave name out" % k)
            if re.search(r"[,/&+·]|이랑|랑|하고|및|그리고|(?:와|과)\s", nm):   # '라면이랑 떡볶이' is two dishes
                raise ValueError("item %d name joins several dishes; give each dish its own item with its own price" % k)
            if _LEFT.search(norm(nm)):
                raise ValueError("item %d name has a number in it; pass only the dish words as name, and the count as qty" % k)
            names.append((nm, k))
        price = _take(it["price"], q, "item %d price" % k, (("원", ""), "'4500원' or '13900원'"))
        used.append(norm(str(it["price"])))
        ps = claim(str(it["price"])); prices.append((ps, k))
        if it.get("qty") not in (None, ""):
            qty = _take(it["qty"], q, "item %d qty" % k, (("",) + COUNTERS, "'두 잔' or '3인분'"))
            qtys.append((claim(str(it["qty"]), ps[1] if ps else None), k, str(it["qty"])))
            if qtys[-1][0]:
                cnt[k] = qtys[-1][0]
        else:   # no qty passed: the cell reads the count said right after the price, or right before it ('두 개 2000원씩')
            g = _GAP.match(qn, ps[1]).end() if ps else -1
            c = None
            for x in counts:
                if x not in used_counts and x[0] == g:
                    c = x; break
            for x in counts:
                if c is None and ps and x not in used_counts and x[1] == ps[0]:
                    c = x; break
            if c:
                cnt[k] = c
                used_counts.add(c)
                try:
                    qty = amount(qn[c[0]:c[1]])[0]
                except ValueError:
                    raise ValueError("item %d: the customer's count '%s' is not one number; ask the customer how many" % (k, qn[c[0]:c[1]]))
            else:
                qty = 1; dflt.append(k)
        read.append([price, qty])
    for p in set(used):
        if used.count(p) > len(spots(p, q)):
            raise ValueError("each price the customer said belongs to one item; if they gave a unit price (like '1인분 만육천원인데 4인분'), use it once with the ordered quantity ('4인분')")
    for sq, k, w in qtys:   # a count belongs to the price said just before it ('떡볶이 4천원 세 개, 순대 5천원': '세 개' is the 떡볶이's)
        before = [(ps, j) for ps, j in prices if ps and sq and ps[1] <= sq[0]]
        if before and max(before)[1] != k:
            raise ValueError("item %d qty '%s' follows item %d's price; give each item the count the customer said with its own price" % (k, w, max(before)[1]))
    order = sorted([(ps[0], j) for ps, j in prices if ps])
    for pos, (a, k) in enumerate(order):   # '만원짜리랑 오천원짜리 두 개씩': a count said 'each' covers the prices before it that had no count
        c = cnt.get(k)
        if not c:
            continue
        gap = qn[a:c[0]]
        each = qn.startswith("씩", c[1]) or bool(_EACH.search(gap))
        group = []
        for b, j in reversed(order[:pos]):
            if j not in dflt:
                break
            group.append(j)
        if (each or _ALL.search(gap)) and _PEOPLE.search(qn):
            raise ValueError("the customer said a count per person or per time ('하나씩 두 명'); ask the customer how many in all")
        if each:
            for j in group:
                read[j - 1][1] = read[k - 1][1]; dflt.remove(j)
        elif _ALL.search(gap) and group:
            raise ValueError("'모두/다/총' before a count can mean each or in all; ask the customer how many of each")
    if dflt and (re.search(r"씩|각각|똑같이|같은\s*걸로", q)):
        raise ValueError("item %d has no count, but the customer said counts for several items ('씩', '각각', '똑같이'); give each item its qty, or ask the customer" % dflt[0])
    unit_ones = []
    for c in counts:   # a count no item uses would leave the total short
        if c in used_counts:
            continue
        unit = any(ps and ps[0] == _GAP.match(qn, c[1]).end() for ps, j in prices)
        try:
            one = amount(qn[c[0]:c[1]])[0] == 1
        except ValueError:
            one = False
        if unit and one:   # 'one' right before a price is the unit it is for ('1인분 만육천원')
            unit_ones.append(c); continue
        if unit:
            raise ValueError("the customer gave a price for '%s' (a price for several); this cell takes the price of one, so work out the price of one only if the customer said it, or ask" % qn[c[0]:c[1]])
        raise ValueError("the customer said '%s' but no item uses it; give each item its qty in the customer's words, or ask the customer if it is unclear" % qn[c[0]:c[1]])
    spent = list(taken) + list(used_counts) + unit_ones   # read the whole sentence: nothing that could be a count may be left over
    for ps, k in prices:
        c = cnt.get(k)
        if ps and c:
            spent.append((ps[1], c[1]) if c[0] >= ps[1] else (c[0], ps[0]))
    spent += [(c[1], c[1] + 1) for c in used_counts if qn.startswith("씩", c[1])]   # '두 개씩' was read above
    spent += [(ps[1], ps[1] + 1) for ps, k in prices if ps and qn.startswith("씩", ps[1])]   # '2000원씩': the price of each
    for nm, k in names:   # the dish words the model passed are understood; any other word left over is not
        for x in spots(nm, q):
            if not any(a < x[1] and x[0] < b for a, b in taken):
                ps = prices[k - 1][0]
                if k in dflt and ps and x[0] == _GAP.match(qn, ps[1]).end():   # '만원짜리 너이': the words stand where its count goes
                    raise ValueError("item %d name stands where the count goes ('%s'); ask the customer how many" % (k, nm))
                taken.append(x); spent.append(x); break
    if not dflt:   # every item has its count: '세 명이서' only says who it is for
        spent += [(x.start(), x.end()) for x in _PEOPLE_SAID.finditer(qn)]
    gaps = _flat(q)[1]; starts = sorted(ps[0] for ps, k in prices if ps); asks = []
    for ps, k in prices:   # read on its own, a count can still be changed by the words after it ('두 그릇 빼 주세요', '두 개 반', '만원짜리 너이')
        if not ps:
            continue
        c = cnt.get(k); at = max(ps[1], c[1] if c else 0)
        nxt = min([s for s in starts if s > ps[0]] + [at + 12, len(qn)])
        w = _next_word(qn, gaps, _GAP.match(qn, ps[1]).end()) if k in dflt else ""
        if _CHANGE.search(qn[at:nxt]) or (w and not _NEXT_RE.fullmatch(w) and not _OTHER_STEP.match(w) and not any(x[0] == _GAP.match(qn, ps[1]).end() for x, j in prices if x) and not any(norm(nm) == w or w.startswith(norm(nm)) for nm, j in names)):
            asks = ["주문하신 수량을 품목마다 한 번 더 말씀해 주시겠어요?"]
    if asks:   # no numbers when a count's meaning changed: the caller asks instead of computing
        read = []; dflt = []
    lines = [{"unit_price": p, "qty": n} for p, n in read]
    return {"answer_ready": not asks, "asks": asks, "items_read": read, "lines": lines, "qty_assumed": sorted(dflt), "spans": [[a, b] for a, b in sorted(set(spent))]}
