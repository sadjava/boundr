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
