from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from statistics import mean

from evallib.judge import JudgeQuery
from evallib.loader import Segment
from evallib.matching import match_segments, match_segments_many

IOU_POINTS = (0.5, 0.25, 0.1)
BOUNDARY_TOLERANCE = 2.0


@dataclass
class PairRow:
    clip: str
    status: str
    iou: float | None
    pred_id: str
    gt_id: str
    pred_start: float | None
    pred_end: float | None
    gt_start: float | None
    gt_end: float | None
    d_start: float | None
    d_end: float | None
    within_2s: bool | None
    pred_action: str
    gt_action: str
    action_ok: bool | None
    action_via: str
    pred_object: str
    gt_object: str
    object_ok: bool | None
    object_via: str


MATCHING_COLUMNS = [f.name for f in fields(PairRow)]

RESULTS_COLUMNS = [
    "clip", "n_gt", "n_pred", "tp", "fp", "fn",
    "f1@0.5", "f1@0.25", "f1@0.1",
    "mae_start", "mae_end", "p95_start", "p95_end", "within_2s_rate",
    "action_acc", "object_acc",
]


def evaluate_clip(
    clip: str,
    pred: list[Segment],
    gt: list[Segment],
    judge,
    matching: str = "onetoone",
) -> list[PairRow]:
    matcher = match_segments_many if matching == "many" else match_segments
    result = matcher(pred, gt, threshold=min(IOU_POINTS))

    rows: list[PairRow] = []
    queries: list[JudgeQuery] = []
    slots: list[tuple[int, str]] = []

    for pred_index, gt_index, score in result.pairs:
        p, g = pred[pred_index], gt[gt_index]
        matched = score >= 0.5
        row = PairRow(
            clip=clip,
            status="TP" if matched else "FP",
            iou=round(score, 4),
            pred_id=p.id,
            gt_id=g.id,
            pred_start=p.start, pred_end=p.end,
            gt_start=g.start, gt_end=g.end,
            d_start=round(p.start - g.start, 3),
            d_end=round(p.end - g.end, 3),
            within_2s=(abs(p.start - g.start) <= BOUNDARY_TOLERANCE
                       and abs(p.end - g.end) <= BOUNDARY_TOLERANCE),
            pred_action=p.action, gt_action=g.action,
            action_ok=None, action_via="",
            pred_object=p.object, gt_object=g.object,
            object_ok=None, object_via="",
        )
        rows.append(row)
        if not matched:
            continue
        for kind, pred_label, gt_label in (
            ("action", p.action, g.action),
            ("object", p.object, g.object),
        ):
            queries.append(JudgeQuery(kind, pred_label, gt_label))
            slots.append((len(rows) - 1, kind))

    for (row_index, kind), verdict in zip(slots, judge.judge(queries)):
        setattr(rows[row_index], f"{kind}_ok", bool(verdict))
        setattr(rows[row_index], f"{kind}_via", "judge" if verdict else "mismatch")

    below = [r for r in rows if r.status == "FP"]
    rows = [r for r in rows if r.status == "TP"]
    for row in below:
        rows.append(_lone_pred_row(clip, row))
        rows.append(_lone_gt_row(clip, row))

    for index in result.unmatched_pred:
        rows.append(_pred_only(clip, pred[index]))
    for index in result.unmatched_gt:
        rows.append(_gt_only(clip, gt[index]))
    return rows


def _blank(clip: str, status: str) -> PairRow:
    return PairRow(
        clip=clip, status=status, iou=None, pred_id="", gt_id="",
        pred_start=None, pred_end=None, gt_start=None, gt_end=None,
        d_start=None, d_end=None, within_2s=None,
        pred_action="", gt_action="", action_ok=None, action_via="",
        pred_object="", gt_object="", object_ok=None, object_via="",
    )


def _pred_only(clip: str, segment: Segment) -> PairRow:
    row = _blank(clip, "FP")
    row.pred_id = segment.id
    row.pred_start, row.pred_end = segment.start, segment.end
    row.pred_action, row.pred_object = segment.action, segment.object
    return row


def _gt_only(clip: str, segment: Segment) -> PairRow:
    row = _blank(clip, "FN")
    row.gt_id = segment.id
    row.gt_start, row.gt_end = segment.start, segment.end
    row.gt_action, row.gt_object = segment.action, segment.object
    return row


def _lone_pred_row(clip: str, row: PairRow) -> PairRow:
    out = _blank(clip, "FP")
    out.pred_id = row.pred_id
    out.pred_start, out.pred_end = row.pred_start, row.pred_end
    out.pred_action, out.pred_object = row.pred_action, row.pred_object
    out.iou = row.iou
    return out


def _lone_gt_row(clip: str, row: PairRow) -> PairRow:
    out = _blank(clip, "FN")
    out.gt_id = row.gt_id
    out.gt_start, out.gt_end = row.gt_start, row.gt_end
    out.gt_action, out.gt_object = row.gt_action, row.gt_object
    out.iou = row.iou
    return out


def _f1(tp: int, fp: int, fn: int) -> float:
    denominator = 2 * tp + fp + fn
    return 0.0 if denominator == 0 else 2 * tp / denominator


def _f1_pr(hit_pred: int, hit_gt: int, n_pred: int, n_gt: int) -> float:
    """F1 из точности по предсказаниям и полноты по эталону.

    В режиме 1:1 совпадает с обычной формулой; в режиме many пара сегментов
    засчитывается обеим сторонам, поэтому precision и recall считаются
    раздельно.
    """
    if not n_pred or not n_gt:
        return 0.0
    precision, recall = hit_pred / n_pred, hit_gt / n_gt
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return ordered[index]


def _keys(rows: list[PairRow], side: str) -> set[tuple]:
    # id может быть пустым (синтетические данные), поэтому в ключ идут и границы.
    return {
        (r.clip, getattr(r, f"{side}_id"),
         getattr(r, f"{side}_start"), getattr(r, f"{side}_end"))
        for r in rows
    }


def metrics_for(rows: list[PairRow]) -> dict[str, float | int]:
    matched = [r for r in rows if r.status == "TP"]
    # Считаем по уникальным сегментам, а не по строкам: в режиме many один
    # сегмент участвует в нескольких парах и иначе бы удваивал счётчики.
    gt_rows = [r for r in rows if r.status in {"TP", "FN"}]
    pred_rows = [r for r in rows if r.status in {"TP", "FP"}]
    n_gt = len(_keys(gt_rows, "gt"))
    n_pred = len(_keys(pred_rows, "pred"))
    tp = len(matched)
    fp = n_pred - len(_keys(matched, "pred"))
    fn = n_gt - len(_keys(matched, "gt"))

    metrics: dict[str, float | int] = {
        "n_gt": n_gt, "n_pred": n_pred, "tp": tp, "fp": fp, "fn": fn,
    }
    for point in IOU_POINTS:
        hits = [r for r in rows
                if r.status in {"TP", "FP"} and r.iou is not None and r.iou >= point]
        metrics[f"f1@{point}"] = _f1_pr(
            min(len(_keys(hits, "pred")), n_pred),
            min(len(_keys(hits, "gt")), n_gt),
            n_pred, n_gt,
        )

    starts = [abs(r.d_start) for r in matched if r.d_start is not None]
    ends = [abs(r.d_end) for r in matched if r.d_end is not None]
    metrics["mae_start"] = round(mean(starts), 3) if starts else 0.0
    metrics["mae_end"] = round(mean(ends), 3) if ends else 0.0
    metrics["p95_start"] = round(_p95(starts), 3)
    metrics["p95_end"] = round(_p95(ends), 3)
    metrics["within_2s_rate"] = round(
        mean([1.0 if r.within_2s else 0.0 for r in matched]), 4) if matched else 0.0

    action_hits = sum(1 for r in matched if r.action_ok)
    object_hits = sum(1 for r in matched if r.object_ok)
    metrics["action_acc"] = round(action_hits / tp, 4) if tp else 0.0
    metrics["object_acc"] = round(object_hits / tp, 4) if tp else 0.0
    return metrics


def fmt_metric(value: float | int) -> str:
    if isinstance(value, bool) or isinstance(value, int):
        return str(value)
    text = f"{value:.4g}"
    return text if "." in text or "e" in text else f"{text}.0"


def write_matching_csv(rows: list[PairRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MATCHING_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: "" if v is None else v for k, v in asdict(row).items()})


def write_results_csv(
    per_clip: dict[str, list[PairRow]],
    path: Path,
) -> dict[str, float | int]:
    all_rows = [row for rows in per_clip.values() for row in rows]
    total = metrics_for(all_rows)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=RESULTS_COLUMNS)
        writer.writeheader()
        for clip, rows in per_clip.items():
            writer.writerow(_formatted(clip, metrics_for(rows)))
        writer.writerow(_formatted("__ALL__", total))
    return total


def _formatted(clip: str, metrics: dict[str, float | int]) -> dict[str, str]:
    return {"clip": clip, **{k: fmt_metric(v) for k, v in metrics.items()}}
