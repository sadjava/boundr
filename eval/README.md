# Eval

Compares an automatic annotation against a reference one and computes the case
metrics: step-level F1, temporal boundary error, action accuracy, object accuracy.

Runs locally, outside Docker: it touches neither the database nor S3.

## Setup

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## Running

Segmentation only, no API key. Label gates are skipped because every label pair
goes to the judge:

```bash
.venv/bin/python eval.py --pred assets/pred --gt assets/gt --out-dir reports --no-judge
```

With the LLM judge (needed to score actions and objects):

```bash
OPENROUTER_API_KEY=sk-or-... .venv/bin/python eval.py \
  --pred assets/pred --gt assets/gt --out-dir reports \
  --judge-model openai/gpt-4o-mini
```

Files are paired by name: `gt/clip_01.json` ↔ `pred/clip_01.json`. A reference
file with no prediction is not skipped — all of its segments are counted as
misses, otherwise a crashed pipeline would improve the score.

The input format is the Boundr export (`{video_id, duration, fps, segments}`,
seconds); a bare list of segments is accepted too. `keyframe` in the export is
ignored. `assets/` holds six synthetic clips covering the interesting cases —
exact match, shifted boundaries, synonymous labels, merged steps, a boundary
beyond the tolerance, and a missing prediction. Put your own data in `data/`,
which is not tracked by git.

## How it scores

Segments are matched by temporal IoU with the Hungarian algorithm; pairs below
IoU 0.5 are dropped. Surviving pairs are true positives, leftover predictions are
false positives, leftover reference segments are false negatives. F1 does not
look at labels.

### Matching mode

`--matching onetoone` (default) is the strict 1:1 assignment described above and
is what the case thresholds are defined on.

`--matching many` allows many-to-one and one-to-many pairs: each reference
segment takes its best prediction and each prediction takes its best reference,
so one coarse predicted step may cover several reference steps and vice versa.
Pairs are scored by containment — `max(inter/|pred|, inter/|gt|)` — instead of
IoU, and the `iou` column of `matching.csv` holds that containment value.
Precision and recall are counted over distinct segments, so a segment reused in
several pairs is not counted twice; on 1:1 data both modes give identical
numbers.

Use it when the reference is annotated at a finer granularity than the product
produces (EPIC-KITCHENS is): strict 1:1 turns every uncovered reference step into
a false negative even when the prediction is not wrong. It measures coverage, not
boundary precision — read it together with `within_2s_rate`, which gets stricter
in this mode because loosely aligned pairs now count as true positives.

Boundary error and label accuracy are computed over matched pairs only.
`within_2s_rate` is the share of TP pairs where both start and end are within
2 seconds of the reference. `action_acc` and `object_acc` are scored separately.

## Success gates

| Metric | Threshold | What it measures |
|---|---|---|
| `f1@0.5` | ≥ 0.75 | step-level segmentation |
| `within_2s_rate` | ≥ 0.75 | temporal boundaries |
| `action_acc` | ≥ 0.80 | action labels, judged independently |
| `object_acc` | ≥ 0.80 | object labels, judged independently |

Label gates apply only when the judge is enabled.

## The judge

Every matched action and every matched object is sent to an LLM through
OpenRouter as written. The judge treats synonyms, hyphen vs underscore, verb
particles (`pour` / `pour-into`) and a head noun inside a longer phrase
(`empty frying pan` / `pan`) as a match. Requests go in small batches; a
malformed reply is retried in halves instead of zeroing the whole clip.
Changing the prompt invalidates the cache automatically.

The key is read from the environment; the script does not load `.env` itself.
Without a key, or with `--no-judge`, every label pair is counted as a mismatch
and the header says `judge: disabled`. `--judge-model` selects the model.

Verdicts are cached in `.eval_cache.json`, so a repeated run costs nothing and
is reproducible.

## Output

- `results.csv` — one row per clip plus an `__ALL__` row with the set total;
- `matching.csv` — every segment pair with its status (TP/FP/FN), boundary deltas
  and how each label was decided (`judge` / `mismatch`).

Exit codes: `0` — every threshold met, `1` — at least one missed, `2` — the
reference annotation is broken.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```
