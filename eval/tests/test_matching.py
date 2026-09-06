from __future__ import annotations

from evallib.loader import Segment
from evallib.matching import iou, match_segments


def seg(start: float, end: float, id_: str = "x") -> Segment:
    return Segment(id_, start, end, "open", "drawer")


def test_iou_identical_is_one() -> None:
    assert iou(seg(0, 2), seg(0, 2)) == 1.0


def test_iou_disjoint_is_zero() -> None:
    assert iou(seg(0, 1), seg(2, 3)) == 0.0


def test_iou_touching_is_zero() -> None:
    assert iou(seg(0, 1), seg(1, 2)) == 0.0


def test_iou_nested() -> None:
    # пересечение 1 с, объединение 4 с
    assert iou(seg(0, 4), seg(1, 2)) == 0.25


def test_iou_zero_length_segments_do_not_divide_by_zero() -> None:
    assert iou(seg(1, 1), seg(5, 5)) == 0.0


def test_perfect_match() -> None:
    result = match_segments([seg(0, 2), seg(2, 4)], [seg(0, 2), seg(2, 4)])
    assert result.pairs == [(0, 0, 1.0), (1, 1, 1.0)]
    assert result.unmatched_pred == []
    assert result.unmatched_gt == []


def test_low_iou_pair_is_dropped_by_threshold() -> None:
    result = match_segments([seg(0, 10)], [seg(9, 10)])
    assert result.pairs == []
    assert result.unmatched_pred == [0]
    assert result.unmatched_gt == [0]


def test_extra_prediction_becomes_unmatched() -> None:
    result = match_segments([seg(0, 2), seg(5, 7)], [seg(0, 2)])
    assert [p[:2] for p in result.pairs] == [(0, 0)]
    assert result.unmatched_pred == [1]


def test_empty_prediction_leaves_all_gt_unmatched() -> None:
    result = match_segments([], [seg(0, 2), seg(2, 4)])
    assert result.pairs == []
    assert result.unmatched_gt == [0, 1]


def test_global_assignment_beats_greedy() -> None:
    # Жадный по наибольшему IoU взял бы пару (pred0, gt0) с IoU 0.5 и остался
    # бы с одной парой (pred1 с gt1 не пересекаются, IoU 0); оптимальное
    # назначение даёт две пары с IoU 0.5 — суммарный IoU выше.
    pred = [seg(0, 20), seg(0, 5)]
    gt = [seg(0, 10), seg(5, 15)]
    result = match_segments(pred, gt, threshold=0.5)
    assert sorted(p[:2] for p in result.pairs) == [(0, 1), (1, 0)]
