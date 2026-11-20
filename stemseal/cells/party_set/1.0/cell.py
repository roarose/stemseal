# --- korean reader 1 begin (shared, byte-identical in korean_amount, order_total, store_hours; tests/test_reader.py checks) ---
import re
from fractions import Fraction
_SINO = {"영": 0, "공": 0, "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "륙": 6, "칠": 7, "팔": 8, "구": 9}
_SMALL = {"십": 10, "백": 100, "천": 1000}
_BIG = {"만": 10000, "억": 100000000}
_NATIVE = [("스무", 20), ("스물", 20), ("열", 10), ("아홉", 9), ("여덟", 8), ("일곱", 7), ("여섯", 6), ("다섯", 5),
           ("하나", 1), ("한", 1), ("둘", 2), ("두", 2), ("셋", 3), ("세", 3), ("석", 3), ("넷", 4), ("네", 4), ("너", 4)]
COUNTERS = ("인분", "그릇", "공기", "접시", "세트", "마리", "잔", "개", "병", "캔", "판", "장", "컵", "명", "인")
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
def found(fragment, question):
    """Is the fragment really in the customer's words (spaces and commas ignored, not inside a longer number)?"""
    f = norm(fragment); q = norm(question)
    if not f:
        return False
    for m in re.finditer(re.escape(f), q):
        a, b = m.start(), m.end()
        if (f[0].isdigit() and a > 0 and q[a - 1].isdigit()) or (f[-1].isdigit() and b < len(q) and q[b].isdigit()):
            continue
        return True
    return False
# --- korean reader 1 end ---
_ALONE = ("혼자", "혼자서", "혼밥", "나혼자")
def _people(words):
    s = norm(words)
    if s in _ALONE or s.rstrip("요") in _ALONE or s.rstrip("이요") in _ALONE:
        return 1
    s = re.sub(r"(이서요|이서|서요|이에요|이요|명이요|명이서|명|사람|인분|인이요|인)$", "", s)
    return amount(s)[0] if s else None
def cell_executor(inp):
    q = inp.get("question")
    if not isinstance(q, str) or not q.strip():
        raise ValueError("pass question: the customer's whole sentence, unchanged")
    extra = sorted(str(k) for k in inp if k not in ("question", "people", "sets"))
    if extra:
        raise ValueError("unknown input %s; use question, people, sets" % extra[:3])
    sets = inp.get("sets")
    if not isinstance(sets, list) or not sets or not all(isinstance(x, dict) and isinstance(x.get("name"), str) and isinstance(x.get("people"), int) and not isinstance(x.get("price"), bool) and isinstance(x.get("price"), int) for x in sets):
        raise ValueError("pass sets: the store's list [{name, people (whole number), price (whole won)}] from the store's data")
    p = inp.get("people")
    if not isinstance(p, str) or not p.strip():
        raise ValueError("pass people: the customer's words for how many people, e.g. '둘이서' or '4명'")
    if not found(p, q):
        raise ValueError("people is not in the question; copy the customer's words for how many people exactly, do not convert")
    try:
        n = _people(p)
    except ValueError:
        n = None
    out = {"answer_ready": False, "ask_customer": None, "people": n, "sets": []}
    if not n:
        out["ask_customer"] = "몇 분이 드실 건가요?"
        return out
    fit = [{"name": x["name"], "price": x["price"]} for x in sets if x["people"] == n]
    if not fit:
        out["ask_customer"] = "%d분께 딱 맞는 세트는 없어요. 직원이 메뉴를 맞춰 드릴게요." % n
        return out
    out.update(answer_ready=True, sets=fit)
    return out
