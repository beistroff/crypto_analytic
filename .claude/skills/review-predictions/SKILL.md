---
name: review-predictions
description: Review the agent's scored test calls from a `sentinel predict export` and draft lessons for it.
disable-model-invocation: true
---

# Review predictions

The agent (Oleg) logs test calls with `sentinel predict log`; code scores each one at its horizon. This review turns those results into **lessons**: short rules the agent reads before its next call. It runs here, in Claude Code or any Claude chat, never on the agent's own token budget.

## 1. Get the export

The user runs this (keys come from aws-vault) and pastes the output, or it is already in the chat:

```powershell
$env:Path = "$PWD\.venv\Scripts;$env:Path"
aws-vault exec sentinel-deploy -- sentinel predict export --days 14
```

The export is JSON:
- `summary` has calls, graded, open and invalid counts, plus `by_horizon`, `by_model` and `by_call` (BUY, SELL, HOLD), each with `n`, `hits` and `hit_pct`, and `wait_baseline_pct`.
- `rows` are arrays named by `columns`. `ret` and `hit` are at the call's own horizon (null while it is open). `first` is `target`, `stop` or `neither`. `adverse` is the worst move against the call in percent, `btc` is BTC's regime when the call was made, and `reasons` is the agent's reasoning.

How a call is graded:
- BUY is a hit when the price is above the entry at the horizon.
- SELL is a hit when the price is below the entry.
- HOLD means "wait, do not buy now": a hit when buying would not have paid (the price is not more than 1 % above the entry). Judge it apart from BUY and SELL (`by_call`): a right wait is not a right direction. Waiting is right on most quiet or falling days, so compare the HOLD rate with `wait_baseline_pct` (what always waiting would have scored on the same calls), not with 50 %.

Done when the export is in hand and its date range is known.

## 2. Read the numbers

Start from `summary`, which code computed: quote it rather than recounting rows.
- Say how much the sample can carry: with fewer than about 10 graded calls in a group, call any pattern a hint.
- Compare each horizon's and each model's `hit_pct` with 50 %, a coin flip.
- `first` and `adverse` show whether a "hit" was tradable: a hit that touched its stop first would have been stopped out.

Done when every horizon and model in `summary` has a sentence.

## 3. Find where the reasoning failed

Group the misses by what they share: BTC regime (`btc`), horizon, action, coin, the reasons cited, a stop placed too close (`first = stop` with a small `adverse`). For a miss worth a closer look, `sentinel predict show <id>` prints the full call. Invalid calls (`valid` false) are graded by price like the rest; `summary.invalid` counts them, and their errors show where the agent misread the snapshot.

Done when each recurring miss pattern is named with its count and two or three example ids.

## 4. Draft lessons

Write at most 5 lessons, each one line:
- the situation, then the action;
- concrete enough to check against a snapshot ("in a `neutral` BTC regime, 4 h buys on coins with RSI over 65 missed 5 of 6: wait for a pullback or skip");
- backed by the counts from step 3.

A pattern seen once is noted for the next review, not turned into a lesson.

Done when the user has approved, edited or rejected each lesson.

## 5. Hand them to the agent

Give the approved lessons as one block the user can send to the agent in Telegram:

```text
Add these to memory/prediction_lessons.md (dated 2026-10-24):
- ...
```

The agent reads `memory/prediction_lessons.md` before each test call (the `test-trade-scenario` skill). Real-trade lessons stay in `memory/lessons_learned.md`.
