# --- korean reader 2 begin (shared, byte-identical in the cells that read a customer's own words; tests/test_reader.py checks) ---
import re
from fractions import Fraction
_SINO = {"영": 0, "공": 0, "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "륙": 6, "칠": 7, "팔": 8, "구": 9}
_SMALL = {"십": 10, "백": 100, "천": 1000}
_BIG = {"만": 10000, "억": 100000000}
_NATIVE = [("스무", 20), ("스물", 20), ("열", 10), ("아홉", 9), ("여덟", 8), ("일곱", 7), ("여섯", 6), ("다섯", 5),
           ("하나", 1), ("한", 1), ("둘", 2), ("두", 2), ("셋", 3), ("세", 3), ("석", 3), ("넷", 4), ("네", 4), ("너", 4)]
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
    """'두' 2, '열두' 12, '스물셋' 23 (counting words); None otherwise."""
    s = norm(s); v = 0
    for w, n in _NATIVE[:3]:
        if s.startswith(w) and n >= 10:
            v = n; s = s[len(w):]; break
    if not s:
        return v or None
    for w, n in _NATIVE:
        if s == w and n < 10:
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
# --- korean reader 2 end ---
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
def cell_executor(inp):
    q = inp.get("question")
    if not isinstance(q, str) or not q.strip():
        raise ValueError("pass question: the customer's whole sentence, unchanged")
    extra = sorted(str(k) for k in inp if k not in ("question", "items", "discount_pct", "discount_won"))
    if extra:
        raise ValueError("unknown input %s; use question, items, discount_pct (percent), discount_won (won)" % extra[:3])
    items = inp.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("pass items: a list like [{\"price\": \"4500원\", \"qty\": \"두 잔\"}] with the customer's own words")
    read = []; used = []
    for k, it in enumerate(items, 1):
        if isinstance(it, dict) and any(k in it for k in _DISC) and "price" not in it:
            raise ValueError("a discount is not an item; put it outside items, e.g. {\"items\": [...], \"discount_pct\": \"10%\"}")
        if not isinstance(it, dict) or "price" not in it:
            raise ValueError("each item must be an object like {\"price\": \"4500원\", \"qty\": \"두 잔\"}")
        if any(k in it for k in _DISC):
            raise ValueError("a discount is not part of an item; put it outside items, e.g. {\"items\": [...], \"discount_won\": \"3천원\"}")
        if set(it) - {"price", "qty"}:
            raise ValueError("an item takes only price and qty, e.g. {\"price\": \"4500원\", \"qty\": \"두 잔\"}")
        price = _take(it["price"], q, "item %d price" % k, (("원", ""), "'4500원' or '만이천구백원'"))
        qty = _take(it["qty"], q, "item %d qty" % k, (("",) + COUNTERS, "'두 잔' or '3인분'")) if it.get("qty") not in (None, "") else 1
        read.append([price, qty]); used.append(norm(str(it["price"])))
    for p in set(used):
        if used.count(p) > len(spots(p, q)):
            raise ValueError("each price the customer said belongs to one item; if they gave a unit price (like '1인분 만육천원인데 4인분'), use it once with the ordered quantity ('4인분')")
    pct = inp.get("discount_pct"); won = inp.get("discount_won")
    pct = _take(pct, q, "discount_pct", (("%",), "'10%'")) if pct not in (None, "", 0) else 0
    won = _take(won, q, "discount_won", (("원",), "'3천원'")) if won not in (None, "", 0) else 0
    if pct > 100:
        raise ValueError("discount_pct must be 0..100")
    subtotal = sum(p * n for p, n in read)
    disc = int(Fraction(subtotal) * pct / 100) + won
    capped = disc > subtotal
    disc = min(disc, subtotal)
    return {"subtotal": subtotal, "discount": disc, "total": subtotal - disc, "item_count": sum(n for _, n in read),
            "items_read": read, "discount_capped": capped}
