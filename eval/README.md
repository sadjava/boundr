# Eval

Compares an automatic annotation against a reference one and computes the case
metrics: step-level F1, temporal boundary error, action and object accuracy.

Runs locally, outside Docker: it touches neither the database nor S3.

## Setup

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## Running

Offline only, no API key needed:

```bash
.venv/bin/python eval.py --pred assets/pred --gt assets/gt --out-dir reports --no-judge
```

With the LLM judge, which also accepts synonymous labels:

```bash
OPENROUTER_API_KEY=sk-or-... .venv/bin/python eval.py \
  --pred assets/pred --gt assets/gt --out-dir reports \
  --judge-model openai/gpt-4o-mini
```

On the bundled `assets/` the difference is visible in one number: `both_acc` is
0.8462 offline and 1.0 with the judge, because `grab`/`take`, `mug`/`cup` and
`place`/`put` are then counted as hits.

Files are paired by name: `gt/clip_01.json` ↔ `pred/clip_01.json`. A reference
file with no prediction is not skipped — all of its segments are counted as
misses, otherwise a crashed pipeline would improve the score.

The input format is the Boundr export (`{video_id, duration, fps, segments}`,
seconds); a bare list of segments is accepted too. `assets/` holds six synthetic
clips covering the interesting cases — exact match, shifted boundaries,
synonymous labels, merged steps, a boundary beyond the tolerance, and a missing
prediction. Put your own data in `data/`, which is not tracked by git.

## How it scores

Segments are matched by temporal IoU with the Hungarian algorithm; pairs below
IoU 0.5 are dropped. Surviving pairs are true positives, leftover predictions are
false positives, leftover reference segments are false negatives.

Boundary error and label accuracy are computed over matched pairs only. Alongside
`both_acc` the report prints `both_acc_strict`, which divides by the number of
reference segments and therefore also pays for missed steps — that is the honest
number to quote.

## The judge

Labels are first compared offline after normalisation (lower case, articles and
English endings stripped). Whatever does not match goes to an LLM through
OpenRouter, so `grab` vs `take` counts as a hit.

The key is read from the environment; the script does not load `.env` itself.
Without a key only the offline layer runs and the header says
`judge: disabled (N pairs counted as mismatch)`. `--no-judge` disables the second
layer explicitly, `--judge-model` selects the model.

Verdicts are cached in `.eval_cache.json`, so a repeated run costs nothing and,
more importantly, is reproducible — the number in a presentation will not drift
because the model answered differently this time.

## Output

- `results.csv` — one row per clip plus an `__ALL__` row with the set total;
- `matching.csv` — every segment pair with its status (TP/FP/FN), boundary deltas
  and how each label was decided (`exact` / `judge` / `mismatch`).

Exit codes: `0` — every threshold met, `1` — at least one missed, `2` — the
reference annotation is broken.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```
