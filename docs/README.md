# Boundr Documentation

Everything written down about the project, in reading order.

**A note on language.** Engineering documents are in English; the project overview and
the product documents are in Russian, matching how they are used. Each document is
maintained in one language only — there are no parallel translations to drift apart.

---

## Start here

| Document | What is in it |
|---|---|
| [Project overview](project-overview.md) 🇷🇺 | The single most complete document: problem, approach, what is built, results, limitations, roadmap, team |
| [ML System Design Doc](ml-system-design.md) 🇷🇺 | The same project in the standard ML system design template: goals, methodology, data and evaluation splits, pilot, deployment, throughput, security, costs. Mostly cross-references the documents below |

---

## Engineering

| Document | What is in it |
|---|---|
| [Architecture](architecture.md) | Services, storage, job processing, API surface, design principles |
| [Diagrams](diagrams.md) | Architecture, job lifecycle, ML pipeline (hybrid and single-model), entity relationships |
| [Database schema](database.md) | Every table, column, constraint, index, enum and migration |
| [Object storage](storage.md) | S3/MinIO key layout, presigned URL flows, CORS, deletion, known caveats |
| [Design spec](design_spec.md) | Colour system, typography, components, motion, accessibility |
| [Data examples](data-examples/) | Export formats, the two contracts, format guarantees |

---

## Product

All six are in Russian.

| Document | What is in it |
|---|---|
| [01. Пользователь и проблема](product/01.%20Пользователь%20и%20проблема.md) | Three user types, decomposition of manual work, cost of the problem |
| [02. Гипотеза и ценностное предложение](product/02.%20Гипотеза%20и%20ценностное%20предложение.md) | The main hypothesis and its built-in risk, hypothesis tree, economics |
| [03. Границы MVP и пользовательский сценарий](product/03.%20Границы%20MVP%20и%20пользовательский%20сценарий.md) | What is in and out of the MVP, the scenario step by step, product-to-code trace |
| [04. Критерии успеха](product/04.%20Критерии%20успеха.md) | Case metrics, our product metrics, the speed-up measurement protocol |
| [05. Допущения, риски и план проверки](product/05.%20Допущения,%20риски%20и%20план%20проверки.md) | Seven assumptions, risks by category, verification plan, AI Product contribution |
| [06. Анализ конкурентов](product/06.%20Анализ%20конкурентов.md) | CVAT, Label Studio, Supervisely, LabelMe, TwelveLabs Pegasus: self-hosting, temporal action labelling, VLM auto-annotation |

---

## Research

Model selection and segmentation experiments live in a separate repository,
`itmo-action-markup-exp`: data extraction, LLM provider clients, local segmentation,
video overlays, TW-FINCH diagnostics and tests. Results and conclusions are summarised
in the project overview, §6. This is a record of how the approach was chosen: the
clustering branch is not part of the MVP.

---

## Honest status summary

**Works end to end:** auth, projects with vocabularies, presigned upload, Redis Streams
queue with states and callbacks, per-pipeline result storage, timeline editor, validated
JSON and CSV export.

**Implemented:** `marlin`, `marlin_gpt`, `pegasus_analyze`, and `pegasus_segment` run real inference.
The original `overlap` / `dense` / `sequential` pipelines stay as stubs for exercising
the loop. Still open: a representative benchmark aligned with Boundr's target taxonomy
and granularity.

**Not measured:** step-level F1, temporal boundary error, action and object accuracy,
actual reduction in manual work, per-clip processing cost. We do not quote these numbers
because they do not exist yet — not because they are bad.
