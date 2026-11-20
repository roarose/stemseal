#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The exact MCP replies for a fixed set of requests, to compare two stemseal trees byte for byte.
  python scripts/reply_snapshot.py <tree> > replies.json
Set: find (10), call that succeeds (10), call that is refused (5), need with no cell (5)."""
import json, os, sys, tempfile
sys.path.insert(0, sys.argv[1]); os.environ["STEMSEAL_HOME"] = tempfile.mkdtemp()
from stemseal import mcp, savings
FIND = ["부가세 포함 금액에서 공급가액", "시급으로 월급 계산", "연차 일수 근속", "환율 원화 환산", "연평균 성장률", "목표 마진 판매가",
        "백분위 순위", "퍼센트포인트 차이", "음식 칼로리", "영업시간 지금 열었나"]
OK = [("vat_supply_price", {"total": 11000}), ("vat_supply_price", {"total": 55000}), ("annual_leave_days", {"years": 3}),
      ("annual_leave_days", {"years": 21}), ("percentage_point_diff", {"before_pct": 12.5, "after_pct": 15}), ("food_calories", {"kcal_per_100g": 130, "grams": 210}),
      ("price_for_target_margin", {"cost": 3000, "margin_pct": 40}), ("geometric_mean_growth", {"rates": [0.1, 0.1]}),
      ("monthly_wage_from_hourly", {"hourly_wage": 10030}), ("store_hours", {"now": "20:20", "open": "10:00", "close": "21:00"})]
BAD = [("vat_supply_price", {}), ("no_such_cell", {"x": 1}), ("annual_leave_days", {"years": "many"}), ("vat_supply_price", {"total": "abc"}), ("wages", {"hourly_wage": 10030})]
NONE = ["대출 원리금 균등상환 월 납입액", "복리 이자 계산", "BMI 계산", "주휴수당 계산", "택배비 계산"]
out = {"find": [mcp.handle("find_cell", {"need": n}) for n in FIND],
       "call_ok": [mcp.handle("call_cell", {"cell": c, "input": i}) for c, i in OK],
       "call_refused": [mcp.handle("call_cell", {"cell": c, "input": i}) for c, i in BAD],
       "no_cell": [mcp.handle("request_cell", {"need": n}) for n in NONE]}
out["tokens"] = {k: savings.text_cost([json.dumps(r, ensure_ascii=False, sort_keys=True) for r in v], None) for k, v in out.items()}
print(json.dumps(out, ensure_ascii=False, sort_keys=True, indent=1))
