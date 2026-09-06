from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment

from evallib.loader import Segment


@dataclass(frozen=True)
class MatchResult:
    pairs: list[tuple[int, int, float]]
    unmatched_pred: list[int]
    unmatched_gt: list[int]


def iou(a: Segment, b: Segment) -> float:
    intersection = min(a.end, b.end) - max(a.start, b.start)
    if intersection <= 0:
        return 0.0
    union = (a.end - a.start) + (b.end - b.start) - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def match_segments(
    pred: list[Segment],
    gt: list[Segment],
    threshold: float = 0.5,
) -> MatchResult:
    if not pred or not gt:
        return MatchResult([], list(range(len(pred))), list(range(len(gt))))

    matrix = np.array([[iou(p, g) for g in gt] for p in pred])
    # Назначение максимизирует суммарный IoU; порог применяется после, чтобы
    # те же пары можно было пересчитать для другого порога.
    rows, cols = linear_sum_assignment(-matrix)

    pairs = [
        (int(r), int(c), float(matrix[r, c]))
        for r, c in zip(rows, cols)
        if matrix[r, c] >= threshold
    ]
    pairs.sort(key=lambda item: item[1])
    matched_pred = {p[0] for p in pairs}
    matched_gt = {p[1] for p in pairs}
    return MatchResult(
        pairs=pairs,
        unmatched_pred=[i for i in range(len(pred)) if i not in matched_pred],
        unmatched_gt=[i for i in range(len(gt)) if i not in matched_gt],
    )


def containment(a: Segment, b: Segment) -> float:
    """Насколько один сегмент покрыт другим: max(inter/|a|, inter/|b|).

    В отличие от IoU не штрафует за разную зернистость — крупный шаг,
    накрывающий несколько эталонных, засчитывается для каждого из них.
    """
    intersection = min(a.end, b.end) - max(a.start, b.start)
    if intersection <= 0:
        return 0.0
    spans = [a.end - a.start, b.end - b.start]
    spans = [s for s in spans if s > 0]
    if not spans:
        return 0.0
    return max(intersection / s for s in spans)


def match_segments_many(
    pred: list[Segment],
    gt: list[Segment],
    threshold: float = 0.5,
) -> MatchResult:
    """Матчинг many-to-one и one-to-many по покрытию.

    Каждый эталонный сегмент берёт лучший предсказанный и наоборот, поэтому
    один сегмент может участвовать в нескольких парах. Дубликаты пар
    схлопываются.
    """
    if not pred or not gt:
        return MatchResult([], list(range(len(pred))), list(range(len(gt))))

    matrix = np.array([[containment(p, g) for g in gt] for p in pred])

    chosen: set[tuple[int, int]] = set()
    for r in range(len(pred)):
        c = int(matrix[r].argmax())
        if matrix[r, c] >= threshold:
            chosen.add((r, c))
    for c in range(len(gt)):
        r = int(matrix[:, c].argmax())
        if matrix[r, c] >= threshold:
            chosen.add((r, c))

    pairs = [(r, c, float(matrix[r, c])) for r, c in sorted(chosen, key=lambda x: x[1])]
    matched_pred = {p[0] for p in pairs}
    matched_gt = {p[1] for p in pairs}
    return MatchResult(
        pairs=pairs,
        unmatched_pred=[i for i in range(len(pred)) if i not in matched_pred],
        unmatched_gt=[i for i in range(len(gt)) if i not in matched_gt],
    )
