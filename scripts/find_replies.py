#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Byte length and digest of every find_cell and list_cells reply a model gets for a fixed set of needs, to compare two trees.
  python scripts/find_replies.py <tree> > digests.json
Part cells are hidden from models, so adding one must leave every reply here unchanged (tests/test_parts.py)."""
import hashlib, json, os, sys, tempfile
sys.path.insert(0, os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STEMSEAL_HOME", tempfile.mkdtemp())
from stemseal import mcp
NEEDS = ["지금 영업 중이에요?", "몇 시까지 해요?", "마감까지 몇 분 남았어요", "지금 밤 9시 반인데 몇 시까지 해요", "오전 오후", "시각 읽기",
         "떡볶이 두 개 얼마예요", "김밥 하나 라면 둘 주세요 얼마", "4500원짜리 두 개 10% 할인", "할인 얼마나 돼요", "만이천구백원", "합계 계산",
         "메뉴판에서 찾기", "세 명이서 먹을 세트", "둘이서 뭐 먹어요", "넷이서 왔는데 어떤 세트가 좋아요", "인원 몇 명",
         "부가세 포함 공급가", "연차 며칠", "환율 계산", "칼로리", "주차 되나요", "맵기 어때요", "시급으로 월급", "기하평균 성장률",
         "is the store open now", "order total with discount", "how many people set", "minutes until closing", "convert dollars to won",
         "대출 원리금 균등상환 월 납입액", "읽지 못한 말", "할인 적용", "단가 곱하기 수량", "영업 시간 창", "세트 고르기"]
def digest(r):
    b = json.dumps(r, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {"bytes": len(b), "sha": hashlib.sha256(b).hexdigest()[:16]}
out = {}
for model in (None, "exaone3.5:2.4b"):
    mcp.MODEL = model; tag = model or "default"
    out["%s/list_cells" % tag] = digest(mcp.handle("list_cells", {}))
    for n in NEEDS:
        out["%s/find/%s" % (tag, n)] = digest(mcp.handle("find_cell", {"need": n}))
print(json.dumps(out, ensure_ascii=False, indent=0, sort_keys=True))
