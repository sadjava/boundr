# Data Examples

**Status: the format is real, the content is illustrative.**
The temporal boundaries come from an actual run of
`videomae-ssv2, fps 8, TW-FINCH lvl0` on `clip_03_30s`; action and object names were
filled in by hand, since the labelling branch does not produce results yet (see the
[project overview](../project-overview.md), §6).

## Files

| File | What it is |
|---|---|
| `export_example.json` | Output of `GET /api/videos/{id}/export?format=json` |
| `export_example.csv` | Output of `GET /api/videos/{id}/export?format=csv` |

## Two formats, and why

Inside the research repository we use a contract in **milliseconds** with `confidence` and
`model_version` fields — convenient for comparing models and tracking whose result this
is.

The product's output uses **seconds** and a flat structure: this is what the user drops
into their training pipeline, and extra fields only get in the way there. The conversion
happens in `ml-service` during post-processing.

## Format guarantees

Exports pass `AnnotationData` / `AnnotationSegment` validation on the backend:

- `start ≤ end` — otherwise the record is rejected;
- `start ≤ keyframe ≤ end` — the value is clamped into the interval;
- a missing `keyframe` is replaced by the interval midpoint;
- an empty object (`""`, `"none"`, `null`) is written as an empty cell in CSV and as
  `null` in JSON;
- the legacy `objects: [{label: ...}]` shape is coerced into a single `object`.

This is why the case criterion "export valid in 100 % of cases" already holds: an invalid
annotation cannot reach the export step.
