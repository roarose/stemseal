# stemseal (lite)

<!-- mcp-name: io.github.roarose/stemseal -->

**Small LLMs guess at calculations. stemseal gives them verified cells to call instead.**
작은 LLM은 계산을 어림짐작합니다. stemseal은 그 대신 부를 수 있는 검증된 세포를 줍니다.

A *cell* is one small, deterministic function. It enters the bank only after it passes a purity check (no I/O, no clock, no randomness) and at least 20 ground-truth cases. Then it is locked by sha256. A locked cell never changes. A fix becomes a new version. If no cell fits, the model gets an honest "not available" instead of an invented answer.

세포는 작고 결정적인 함수 하나입니다. 순수성 검사와 정답 사례 20개 이상을 통과해야 들어오고, sha256으로 잠깁니다. 잠긴 세포는 바뀌지 않으며, 고치면 새 버전이 됩니다. 맞는 세포가 없으면 지어낸 답 대신 "없음"을 정직하게 돌려줍니다.

This lite version runs entirely on your machine. There is no server, no account, no dependencies, and no telemetry. Only `stemseal update`, when you run it, downloads new cells.
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
pip install stemseal
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

Language: guides answer in Korean when the request contains Hangul and in English otherwise. Set `STEMSEAL_LANG=ko` or `en` to fix it. The numbers above were measured with the Korean wording; the English wording is a translation and has not been re-measured yet.
안내 문구는 요청에 한글이 있으면 한국어, 없으면 영어로 나갑니다. 위 수치는 한국어 문구로 잰 것이고, 영어 문구는 아직 따로 재지 않았습니다.

## Command line

```
stemseal list
stemseal find 연평균 성장률
stemseal call currency_convert '{"amount": 100, "rate": 1385.5}'
stemseal request 대출 원리금 균등상환 월 납입액
stemseal demand           # unmet needs on this machine, alike requests counted together
stemseal demand --open 1  # show the cell-request issue text for the top one, then open it if you agree
stemseal update           # get cells made since you installed
stemseal savings          # tokens the cells saved on this machine
```

## Cells

| cell | computes | inputs |
|---|---|---|
| annual_leave_days | 근속 연수로 연차 일수 (15일, 2년마다 +1, 최대 25) | years |
| currency_convert | 외화를 원화로 환산 (원 미만 버림) | amount, rate |
| food_calories | 100g당 열량과 먹은 양으로 섭취 열량 | kcal_per_100g, grams |
| geometric_mean_growth | 기간별 성장률의 기하평균 성장률 (%) | rates |
| order_total | 주문 항목(가격×수량) 합계, 할인, 결제 금액 · built from a store kiosk test | items, discount_pct, discount_won |
| monthly_wage_from_hourly | 시급을 월 209시간 기준 월급으로 | hourly_wage |
| percentage_point_diff | 두 비율의 차이 (%p) | before_pct, after_pct |
| percentile_rank | 값이 목록에서 몇 % 위치인지 | values, value |
| price_for_target_margin | 원가와 목표 마진율로 판매가 | cost, margin_pct |
| store_hours | 지금 영업 중인지, 마감·오픈까지 남은 분 (자정 넘는 영업 포함) · built from a store kiosk test | now, open, close |
| vat_supply_price | 부가세 포함 금액을 공급가액과 부가세로 (부가세 원 미만 절사) · first cell built from a request (#4) | total, vat_pct |

## Need a cell that isn't here? / 필요한 세포가 없나요?

When nothing fits, the need is saved without the model having to do anything: a `find_cell` that comes back empty, or a call to a cell name that does not exist, is written to your own ledger (`~/.stemseal/ledger.jsonl`) with the time, the words searched, the model name (`STEMSEAL_MODEL`) and the closest cell. The model can also ask on purpose with `request_cell` (just `need`, one sentence; `example` is optional). Either way the reply is not a refusal: it says the request is saved and counted, to answer on its own for now and say so, and to look again next time, and it points at the closest cell when one comes near.

Requests for the same calculation are counted together (numbers, word order, spacing and words like "계산" or "amount" aside; a different word such as 복리/단리 keeps them apart); the count is how strong the demand is. `stemseal demand` lists them, most asked first. Nothing is sent anywhere: `stemseal demand --open <n>` first shows the GitHub cell-request issue it would open (the need, other wordings, the example, how often it was asked), with phone numbers, e-mail addresses, ID numbers and long number runs hidden, and opens it only if you agree. The repository is public, so check the text for names or anything private before you submit. Requested cells are built as demand gathers. Run `stemseal update` to get them: it downloads only new locked cells and re-checks each one on your machine (sha256, purity gate, every ground-truth case) before it can be used, and the requests a new cell answers drop off your list. Update is the only command that reaches the internet, and it only downloads. (`stemseal measure` talks only to the Ollama on your own machine.)

세포가 없으면 모델이 따로 하지 않아도 요청이 남습니다. `find_cell`이 빈손으로 돌아오거나 없는 세포 이름을 부르면, 시각, 찾던 말, 모델 이름, 가장 가까운 세포가 내 컴퓨터의 장부에만 기록됩니다. 모델이 `request_cell`로 직접 요청할 수도 있습니다(`need` 한 문장이면 되고 `example`은 선택). 돌려주는 말은 거절이 아니라 "기록했고 곧 그 물길을 만든다, 다음에 다시 찾아 달라"이고, 가까운 세포가 있으면 함께 알려 줍니다. 같은 계산의 요청은 숫자, 낱말 순서, 띄어쓰기, "계산" 같은 말이 달라도 한 건으로 묶어 횟수를 셉니다(복리/단리처럼 낱말이 다르면 따로 둡니다). `stemseal demand`로 쌓인 요청을 보고, `stemseal demand --open <번호>`로 GitHub 세포 요청 이슈의 내용을 먼저 확인한 뒤 동의하면 엽니다. 전화번호, 이메일, 주민번호, 긴 숫자열은 가려지지만 저장소는 공개이니 이름 같은 개인 정보가 없는지 보고 제출하세요. 요청이 모이는 순서대로 세포를 만들고 `stemseal update`로 받습니다. 새 잠금 세포만 내려받아 내 컴퓨터에서 sha256, 순수성, 정답 사례를 모두 다시 확인한 뒤에 쓰고, 그 세포가 답한 요청은 목록에서 빠집니다. 인터넷을 쓰는 명령은 update 하나뿐이고, 내려받기만 합니다(`stemseal measure`는 내 컴퓨터의 Ollama에만 붙습니다).

## Tokens saved / 아낀 토큰

Every cell call records, in the same local ledger, what it cost and what it saved. It is always on and never leaves your machine.

- **cost**: the call the model wrote plus the reply it read, estimated from the text (1 token per 4 ASCII characters, 1 per Hangul or other character). stemseal never sees your model's tokenizer.
- **baseline**: the tokens the same model spends doing the job without the cell, measured per cell and per model.
- **saved** = baseline − cost. Negative stays negative. A refused call saves nothing (saved = −cost), and the tokens spent on `find_cell` are subtracted from the total.

Measured and estimated numbers are kept apart. A model with no measurement of its own gets the smallest baseline measured on any other model, marked `estimate`. A cell with no measurement at all gets no number (`none`), never a guess.

```
stemseal savings --days 30                      # totals by cell, model and day
stemseal measure vat_supply_price qwen2.5:3b    # measure a baseline with your local Ollama model (5 cases)
```

세포를 부를 때마다 든 토큰과 아낀 토큰이 같은 장부에 저절로 남습니다. 끄는 옵션은 없고, 내 컴퓨터 밖으로 나가지 않습니다. 아낀 양은 "세포 없이 같은 일을 할 때 그 모델이 쓰는 토큰(기준값)"에서 이번 호출에 든 토큰을 뺀 값입니다. 기준값은 세포마다, 모델마다 `stemseal measure`로 잽니다. 실측과 추정은 섞지 않고, 잰 적 없는 세포에는 숫자를 지어내지 않습니다.

## Safety

Cells run in a separate `python -I` process with a timeout, and only after the purity gate. This is process isolation, not an OS sandbox. Every cell here was reviewed before locking, and `stemseal verify` lets you check that none changed.

## License

MIT. See [LICENSE](LICENSE).
