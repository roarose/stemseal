import re
# words that say the usual one-open-one-close hours may not hold today: a break, last order, a day off, other hours on some days,
# hours moved or extended, a second opening. Then the hours are not computed: staff tells the customer.
_BREAK_W = r"브레이크|쉬는\s*시간|쉬어요|쉬는데|쉬고|라스트\s*오더|주문\s*마감"   # store_hours 7.0's words
_BREAK = re.compile(_BREAK_W)
_CAVEAT = re.compile("|".join((
    _BREAK_W, r"휴식|준비\s*시간|청소",
    r"휴무|휴업|쉬는\s*날|정기\s*휴일|문\s*닫는\s*날|공휴일|명절|휴일",
    r"(?:오늘은|오늘만|내일은|주말|토요일|일요일|평일|월요일|화요일|수요일|목요일|금요일)[^.?!]{0,14}?(?:닫|마감|열|오픈|문|영업|까지|부터)",
    r"연장|일찍|늦게\s*(?:열|닫|문)|당겨|미뤄|다시\s*열|재오픈|다시\s*오픈|임시",
)))
def cell_executor(inp):
    q = inp.get("question")
    if not isinstance(q, str) or not q.strip():
        raise ValueError("pass question: the customer's whole sentence, unchanged")
    extra = sorted(str(k) for k in inp if k not in ("question",))
    if extra:
        raise ValueError("unknown input %s; use question" % extra[:3])
    hits = [[len(re.sub(r"\s", "", q[:m.start()])), len(re.sub(r"\s", "", q[:m.end()]))] for m in _CAVEAT.finditer(q)]
    if hits:   # one open and one close only: a break, a day off or other hours today would make the answer wrong
        ask = "쉬는 시간이나 주문 마감 시간이 따로 있으면 직원이 정확히 안내해 드릴게요." if _BREAK.search(q) else "오늘 영업시간이 평소와 다를 수 있어서, 직원이 정확히 안내해 드릴게요."
        return {"answer_ready": False, "asks": [ask], "spans": hits}
    return {"answer_ready": True, "asks": [], "spans": []}
