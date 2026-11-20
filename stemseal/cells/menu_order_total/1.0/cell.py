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
_PAREN = re.compile(r"\([^)]*\)")
def _menu(menu):
    if not isinstance(menu, list) or not menu:
        raise ValueError("pass menu: the store's menu list [{name, price, unit?, min_people?, variants?, aliases?}] from the store's data, not from the customer")
    out = []
    for m in menu:
        if not isinstance(m, dict) or not isinstance(m.get("name"), str) or isinstance(m.get("price"), bool) or not isinstance(m.get("price"), int) or m["price"] < 0:
            raise ValueError("each menu entry needs name (text) and price (whole won)")
        vs = [v for v in m.get("variants") or [] if isinstance(v, dict) and isinstance(v.get("name"), str) and isinstance(v.get("price"), int)]
        brands = [norm(v["name"]) for v in m.get("variants") or [] if isinstance(v, dict) and isinstance(v.get("name"), str) and "price" not in v]   # 콜라 -> 음료
        names = [norm(m["name"]), norm(_PAREN.sub("", m["name"]))] + [norm(a) for a in m.get("aliases") or [] if isinstance(a, str)] + brands
        names += [names[1] + norm(v["name"]) for v in vs]   # "모둠 전 대" names the size with the dish
        out.append({"m": m, "names": names, "variants": vs, "takeout": "포장" in m["name"]})
    return out
def _pick(frag, qtext, menu, question):
    """Menu entries the customer's words point to. Exact name first, then names that contain the words."""
    f = norm(frag)
    exact = [e for e in menu if f == e["names"][0]] or [e for e in menu if f in e["names"]]
    if exact and "포장" in norm(question) and "포장" not in f:   # "직화 쭈꾸미 볶음 ... 포장이요" -> the takeout entry of the same name
        exact = [e for e in menu if e["takeout"] and e["names"][1] == f] or exact
    cands = exact or [e for e in menu if any(f in n for n in e["names"])]
    if len(cands) > 1 and qtext:
        q = norm(qtext)
        hit = [e for e in cands if q and q.rstrip("분") in e["names"][0]]   # "3인분" picks "보배 반상 3인"
        cands = hit or cands
    if len(cands) > 1:
        want_takeout = "포장" in norm(question)
        cands = [e for e in cands if e["takeout"] == want_takeout] or cands
    return cands
def _eun(w):
    """'은' after a final consonant, '는' otherwise (so the question to the customer reads naturally)."""
    ch = w.rstrip("'\" )")[-1:] if w else ""
    return "은" if ch and "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 else "는"
def cell_executor(inp):
    q = inp.get("question")
    if not isinstance(q, str) or not q.strip():
        raise ValueError("pass question: the customer's whole sentence, unchanged")
    extra = sorted(str(k) for k in inp if k not in ("question", "menu", "items"))
    if extra:
        raise ValueError("unknown input %s; use question, menu, items" % extra[:3])
    menu = _menu(inp.get("menu"))
    items = inp.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("pass items: a list like [{\"name\": \"삼겹 쭈꾸미\", \"qty\": \"3인분\"}] with the customer's own words")
    out = {"answer_ready": False, "ask_customer": None, "lines": [], "total": None}
    asks = []
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("name"), str) or set(it) - {"name", "qty"}:
            raise ValueError("each item is {\"name\": the customer's words for the menu, \"qty\": their words for how many}; nothing else")
        name = it["name"].strip(); qt = it.get("qty")
        if not found(name, q):
            raise ValueError("name is not in the question; copy the customer's words for the menu exactly, do not rename it")
        if qt not in (None, "") and (not isinstance(qt, (str, int)) or isinstance(qt, bool) or not found(str(qt), q)):
            raise ValueError("qty is not in the question; copy the customer's words for how many exactly (like '3인분'), do not convert")
        cands = _pick(name, str(qt) if qt not in (None, "") else "", menu, q)
        if not cands:
            asks.append("'%s'%s 메뉴판에서 찾지 못했어요. 메뉴 이름을 다시 말씀해 주시겠어요?" % (name, _eun(name))); continue
        if len(cands) > 1:
            asks.append("'%s'%s %s 중 어느 것인가요?" % (name, _eun(name), ", ".join(e["m"]["name"] for e in cands[:4]))); continue
        e = cands[0]; m = e["m"]; price = m["price"]; label = m["name"]; n = None
        if e["variants"]:
            words = norm(name) + norm(qt or "")
            vs = [v for v in e["variants"] if norm(v["name"]) in words]
            if len(vs) != 1:
                asks.append("%s%s %s 중 어느 것으로 드릴까요?" % (m["name"], _eun(m["name"]), ", ".join(v["name"] for v in e["variants"]))); continue
            price = vs[0]["price"]; label = "%s %s" % (m["name"], vs[0]["name"])
            if qt not in (None, "") and norm(vs[0]["name"]) == norm(qt):
                n = 1   # "4마리" named the size, not a count
        per_person = m.get("unit") == "1인"
        if n is None:
            if qt in (None, ""):
                if per_person:
                    asks.append("%s%s 몇 인분으로 드릴까요?" % (m["name"], _eun(m["name"]))); continue
                n = 1
            else:
                n, u = amount(str(qt))
                if u == "%" or u == "원":
                    raise ValueError("qty reads as an amount of money or a percent; pass the customer's words for how many")
                if norm(m["name"]).endswith(norm(str(qt)).rstrip("분")) and re.search(r"\d+인$", norm(m["name"])):
                    n = 1   # "보배 반상 3인" ordered as "3인분": one set
        mp = m.get("min_people")
        if isinstance(mp, int) and per_person and n < mp:
            asks.append("%s%s %d인 이상 주문하는 메뉴예요. 몇 인분으로 드릴까요?" % (m["name"], _eun(m["name"]), mp)); continue
        out["lines"].append({"name": label, "unit_price": price, "qty": n, "line_total": price * n})
    if asks:
        out["ask_customer"] = " ".join(asks)
        return out
    out["answer_ready"] = True
    out["total"] = sum(x["line_total"] for x in out["lines"])
    return out
