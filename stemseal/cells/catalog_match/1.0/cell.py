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
# --- catalog reader 1 begin (shared, byte-identical in the cells that read a store's list; tests/test_reader.py checks) ---
_PAREN = re.compile(r"\([^)]*\)")
def _catalog(menu):
    if not isinstance(menu, list) or not menu:
        raise ValueError("pass catalog: the store's list [{name, price, unit?, min_people?, variants?, aliases?}] from the store's data, not from the customer")
    out = []
    for m in menu:
        if not isinstance(m, dict) or not isinstance(m.get("name"), str) or isinstance(m.get("price"), bool) or not isinstance(m.get("price"), int) or m["price"] < 0:
            raise ValueError("each catalog entry needs name (text) and price (whole won)")
        vs = [v for v in m.get("variants") or [] if isinstance(v, dict) and isinstance(v.get("name"), str) and isinstance(v.get("price"), int)]
        brands = [norm(v["name"]) for v in m.get("variants") or [] if isinstance(v, dict) and isinstance(v.get("name"), str) and "price" not in v]   # 콜라 -> 음료
        names = [norm(m["name"]), norm(_PAREN.sub("", m["name"]))] + [norm(a) for a in m.get("aliases") or [] if isinstance(a, str)] + brands
        names += [names[1] + norm(v["name"]) for v in vs]   # "모둠 전 대" names the size with the dish
        out.append({"m": m, "names": names, "variants": vs, "takeout": "포장" in m["name"], "brands": brands})
    return out
# --- catalog reader 1 end ---
def _at(qn, a, menu):
    """Catalog entries whose full name the question spells out from position a (longest first): '한상4인' beats '한상'."""
    best = 0; hit = []
    for i, e in enumerate(menu):
        for n in e["names"]:
            if n and qn.startswith(n, a):
                if len(n) > best:
                    best = len(n); hit = [i]
                elif len(n) == best and i not in hit:
                    hit.append(i)
    return best, hit
def cell_executor(inp):
    q = inp.get("question")
    if not isinstance(q, str) or not q.strip():
        raise ValueError("pass question: the customer's whole sentence, unchanged")
    extra = sorted(str(k) for k in inp if k not in ("question", "catalog", "said"))
    if extra:
        raise ValueError("unknown input %s; use question, catalog, said" % extra[:3])
    menu = _catalog(inp.get("catalog"))
    items = inp.get("said")
    if not isinstance(items, list) or not items:
        raise ValueError("pass said: a list like [{\"name\": \"김치찌개\"}] with the customer's own words for each entry")
    qn = norm(q); rows = []
    for k, it in enumerate(items, 1):
        if not isinstance(it, dict) or not isinstance(it.get("name"), str) or set(it) - {"name", "qty"}:
            raise ValueError("each item is {\"name\": the customer's words for the entry}; the count is read from the question")
        name = it["name"].strip()
        sp = spots(name, q)
        if not sp:
            raise ValueError("item %d: name is not in the question; copy the customer's words for it exactly, do not rename or translate it" % k)
        cands = []
        def around(a, b):
            """The longest catalog name the customer said that holds a..b inside it ('계란찜' in '치즈 계란찜'), or None."""
            best = None
            for e in menu:
                for n in e["names"]:
                    if len(n) > b - a:
                        for x, y in spots(n, q):
                            if x <= a and b <= y and (x, y) != (a, b) and (best is None or y - x > best[1] - best[0]):
                                best = (x, y)
            return best
        free = [x for x in sp if around(*x) is None and not any(x[0] < r["span"][1] and r["span"][0] < x[1] for r in rows)]
        if not free:   # every place the words stand is part of a longer name: the customer said that entry
            free = [around(*x) or x for x in sp]
        sp = free
        span = sp[0]
        for a, b in sp:
            L, hit = _at(qn, a, menu)
            if hit and (a + L >= b or _QX.fullmatch(qn[a + L:b], _SKIP.match(qn[a + L:b]).end())):   # "치즈 돈가스 두 개" passed as a name: the count stays in the question
                cands = hit; span = (a, a + L); break
        if len(cands) > 1:
            want_takeout = "포장" in qn
            cands = [i for i in cands if menu[i]["takeout"] == want_takeout] or cands
        rows.append({"name": name, "cands": cands, "span": span, "end": span[1]})
    for r in rows:   # what the name covers: a size said with it, '분' after a set name ('한상 3인분')
        if len(r["cands"]) == 1:
            e = menu[r["cands"][0]]
            if e["names"][0].endswith("인") and qn.startswith("분", r["end"]):
                r["end"] += 1
            if e["variants"]:
                for v in sorted(e["variants"], key=lambda v: -len(norm(v["name"]))):
                    sk = _SKIP.match(qn, r["end"]).end()
                    if norm(v["name"]) and qn.startswith(norm(v["name"]), sk) and not any(x["span"][0] <= sk < x["span"][1] for x in rows):
                        r["end"] = sk + len(norm(v["name"])); break
    covered = [(r["span"][0], r["end"]) for r in rows]
    for e in menu:   # an entry the customer named but no item covers: a total would be short
        for n_ in e["names"]:
            if len(n_) < 2:
                continue
            for a, b in spots(n_, q):
                if n_ in e["brands"] and not _qty_after(qn[b:]):   # '새로' is a soju and also a word; a brand counts only with a count
                    continue
                if not any(x <= a < y or x < b <= y for x, y in covered):
                    raise ValueError("the question names another entry that is not in said; add every entry the customer named as its own item")
    return {"matches": [{"said": r["name"], "start": r["span"][0], "name_end": r["span"][1], "end": r["end"], "candidates": r["cands"]} for r in rows],
            "spans": [[a, b] for a, b in sorted(set(covered))]}
