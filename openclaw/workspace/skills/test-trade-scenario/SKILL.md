---
name: test-trade-scenario
description: Log a test call (a simulated trade) so code can score it later. Use when the user says "test trade XRP 24h", "/predict", "log this call", or asks for the details of a logged call.
---

# Test trade scenario

A test call is a prediction, not a trade: nothing is bought and no money is set aside. It is stored in the DynamoDB table `sentinel-sim`; code scores it later against what the market did. You only log calls; you never score or review them. Run `sentinel` by its full path, `/home/ubuntu/sentinel/venv/bin/sentinel`.

## "Test trade XRP 24h"

1. If `memory/prediction_lessons.md` exists, read it first: lessons from scored calls.
2. Run `sentinel snapshot XRP` and decide as you would for any analysis (BTC first). The horizon is the one asked for: 1, 4 or 12 hours for a scalp, 24, 72 or 168 hours (1, 3 or 7 days) for a trade (24 if none is given). Calls for a month or longer are investments, not test calls: do not log them. A FLAT call (HOLD) says the price stays within ±1 % over the horizon.
3. Write the call as JSON and log it, with the model you run on as `--model`:

```bash
sentinel predict log --symbol XRP --model <your model> --format telegram --json '{"btc_context": "BTC +1.2% in 24 h, above both averages: neutral", "action": "BUY", "direction": "UP", "confidence": 0.64, "horizon_h": 24, "entry": 1.183, "target": 1.21, "stop": 1.12, "reasons": ["funding neutral", "RSI 54, room to run"], "risk_note": "weekend in 2 days"}'
```

- `action` is BUY, SELL or HOLD; `direction` is UP, DOWN or FLAT; `confidence` is 0 to 1.
- `entry` is the snapshot's price. BUY needs `target > entry > stop`, SELL the reverse; HOLD needs no target or stop.
- `btc_context` is one line on BTC from the snapshot; `reasons` are 2 or 3 short ones.

4. Reply with your call in the usual short form, then the command's line as it is. Example output:

```text
Logged XRP BUY 24h (01K8...): entry 1.183, target 1.21, stop 1.12.
```

If the line says `Invalid: ...`, the call is still logged and counted as invalid: tell your human why in a few words, and do not log it again.

## "Details" of a logged call

```bash
sentinel predict show <id> --format telegram
```

Reply with it as it is; without `--format telegram` you get every stored field.

## Errors

If a command prints `{"error": ...}`, report it in a few words and stop. `bad prediction: ...` names the field that is wrong in the JSON: fix it and log once more.
