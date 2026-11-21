import re
def cell_executor(inp):
    q = inp.get("question")
    if not isinstance(q, str) or not q.strip():
        raise ValueError("pass question: the customer's whole sentence, unchanged")
    extra = sorted(str(k) for k in inp if k not in ("question",))
    if extra:
        raise ValueError("unknown input %s; use question" % extra[:3])
    if re.search(r"브레이크|쉬는\s*시간|쉬어요|쉬는데|쉬고|라스트\s*오더|주문\s*마감", q):   # one open and one close only: a break or last order would make the answer wrong
        return {"answer_ready": False, "asks": ["쉬는 시간이나 주문 마감 시간이 따로 있으면 직원이 정확히 안내해 드릴게요."]}
    return {"answer_ready": True, "asks": []}
