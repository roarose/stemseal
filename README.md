# stemseal (lite)

**Small LLMs guess at calculations. stemseal gives them verified cells to call instead.**
작은 LLM은 계산을 어림짐작합니다. stemseal은 그 대신 부를 수 있는 검증된 세포를 줍니다.

A *cell* is one small, deterministic function. It enters the bank only after it passes a purity check (no I/O, no clock, no randomness) and at least 20 ground-truth cases. Then it is locked by sha256. A locked cell never changes. A fix becomes a new version. If no cell fits, the model gets an honest "not available" instead of an invented answer.

세포는 작고 결정적인 함수 하나입니다. 순수성 검사와 정답 사례 20개 이상을 통과해야 들어오고, sha256으로 잠깁니다. 잠긴 세포는 바뀌지 않으며, 고치면 새 버전이 됩니다. 맞는 세포가 없으면 지어낸 답 대신 "없음"을 정직하게 돌려줍니다.

This lite version runs entirely on your machine. There is no server, no account, no dependencies, and no telemetry.
이 판은 전부 내 컴퓨터에서 돕니다. 서버, 계정, 의존성, 원격 수집이 없습니다.

## What we measured / 측정 결과

52 held-out tasks, 3 runs each (156), local models through Ollama:

| Model | Alone | With stemseal + model guide |
|---|---|---|
| EXAONE 3.5 7.8B | 23% | 78% |
| qwen2.5:3b | 11% | 66% |
| llama3.2:3b | 7% | 50% |

Caveats, honestly / 솔직한 한계:
- One test set, written by us, mostly Korean business arithmetic. Your tasks will differ.
- 우리가 만든 시험 하나, 주로 한국어 업무 계산입니다. 여러분의 일과는 다를 수 있습니다.
- Cells help only where a cell exists. Writing, translation and judgment stay with the model.
- 세포가 있는 계산에서만 돕습니다. 글쓰기, 번역, 판단은 모델 몫입니다.

## Install / 설치

```
pip install git+https://github.com/roarose/stemseal
stemseal verify          # re-checks every lock and ground-truth case
```

## Connect to your model (MCP) / 모델에 연결

Any MCP client (LM Studio, Claude Desktop, Ollama front-ends that speak MCP, ...):

```json
{
  "mcpServers": {
    "stemseal": {
      "command": "stemseal-mcp",
      "env": { "STEMSEAL_MODEL": "qwen2.5:3b" }
    }
  }
}
```

`STEMSEAL_MODEL` is optional. When set, `find_cell` returns a short selection guide written for that model family's known weak spots (too many candidates, wrapped arguments, renamed keys), and `call_cell` repairs those input mistakes before running the cell.
`STEMSEAL_MODEL`을 넣으면 그 모델 계열의 약점에 맞춘 고르기 안내가 함께 오고, 흔한 입력 실수를 고친 뒤 실행합니다.

Tools: `find_cell`, `call_cell`, `list_cells`, `request_cell`.

## Command line

```
stemseal list
stemseal find 연평균 성장률
stemseal call currency_convert '{"amount": 100, "rate": 1385.5}'
stemseal request 대출 원리금 균등상환 월 납입액
stemseal demand
```

## Cells in 0.1.0

| cell | computes | inputs |
|---|---|---|
| annual_leave_days | 근속 연수로 연차 일수 (15일, 2년마다 +1, 최대 25) | years |
| currency_convert | 외화를 원화로 환산 (원 미만 버림) | amount, rate |
| food_calories | 100g당 열량과 먹은 양으로 섭취 열량 | kcal_per_100g, grams |
| geometric_mean_growth | 기간별 성장률의 기하평균 성장률 (%) | rates |
| monthly_wage_from_hourly | 시급을 월 209시간 기준 월급으로 | hourly_wage |
| percentage_point_diff | 두 비율의 차이 (%p) | before_pct, after_pct |
| percentile_rank | 값이 목록에서 몇 % 위치인지 | values, value |
| price_for_target_margin | 원가와 목표 마진율로 판매가 | cost, margin_pct |

## Need a cell that isn't here? / 필요한 세포가 없나요?

When `find_cell` comes back empty, the model can call `request_cell`. The need is saved only on your machine (`~/.stemseal/ledger.jsonl`), and the reply carries a link to open a GitHub issue. Nothing is sent unless you open it. Requested cells are built as demand gathers and ship in the next version.

`request_cell`은 필요를 내 컴퓨터에만 기록하고, GitHub 이슈를 여는 링크를 돌려줍니다. 링크를 직접 열기 전에는 아무것도 보내지 않습니다. 요청이 모이는 순서대로 세포를 만들어 다음 버전에 담습니다.

## Safety

Cells run in a separate `python -I` process with a timeout, and only after the purity gate. This is process isolation, not an OS sandbox. Every cell here was reviewed before locking, and `stemseal verify` lets you check that none changed.

## License

MIT. See [LICENSE](LICENSE).
