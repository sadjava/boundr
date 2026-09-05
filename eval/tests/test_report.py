from __future__ import annotations

import csv
from pathlib import Path

from evallib.loader import Segment
from evallib.report import evaluate_clip, metrics_for, write_results_csv


class StubJudge:
    """Судья, который признаёт синонимом всё, что ему дали."""

    def __init__(self, verdict: bool = True) -> None:
        self.verdict = verdict
        self.queries: list = []

    def judge(self, queries: list) -> list[bool]:
        self.queries.extend(queries)
        return [self.verdict] * len(queries)


def seg(start, end, action="open", object_="drawer", id_="s", keyframe=None):
    return Segment(id_, start, end, action, object_, keyframe)


def test_perfect_clip_gives_f1_one() -> None:
    gt = [seg(0, 2), seg(2, 4, "take", "knife")]
    rows = evaluate_clip("clip", gt, gt, StubJudge())
    metrics = metrics_for(rows)
    assert metrics["tp"] == 2
    assert metrics["fp"] == 0
    assert metrics["fn"] == 0
    assert metrics["f1@0.5"] == 1.0
    assert metrics["both_acc"] == 1.0


def test_extra_and_missing_segments_are_counted() -> None:
    pred = [seg(0, 2), seg(10, 12)]
    gt = [seg(0, 2), seg(20, 22), seg(30, 32)]
    metrics = metrics_for(evaluate_clip("clip", pred, gt, StubJudge()))
    assert (metrics["tp"], metrics["fp"], metrics["fn"]) == (1, 1, 2)
    assert metrics["f1@0.5"] == 2 / 5


def test_empty_prediction_gives_zero_f1() -> None:
    metrics = metrics_for(evaluate_clip("clip", [], [seg(0, 2)], StubJudge()))
    assert metrics["f1@0.5"] == 0.0
    assert metrics["fn"] == 1


def test_boundary_error_and_within_2s() -> None:
    pred = [seg(0.5, 2.0)]
    gt = [seg(0.0, 2.0)]
    metrics = metrics_for(evaluate_clip("clip", pred, gt, StubJudge()))
    assert metrics["mae_start"] == 0.5
    assert metrics["mae_end"] == 0.0
    assert metrics["within_2s_rate"] == 1.0


def test_boundary_beyond_2s_is_not_counted() -> None:
    pred = [seg(0.0, 10.0)]
    gt = [seg(3.0, 10.0)]
    metrics = metrics_for(evaluate_clip("clip", pred, gt, StubJudge()))
    assert metrics["within_2s_rate"] == 0.0


def test_exact_label_match_does_not_call_the_judge() -> None:
    judge = StubJudge()
    evaluate_clip("clip", [seg(0, 2, "Opening")], [seg(0, 2, "open")], judge)
    assert judge.queries == []


def test_judge_decides_synonym() -> None:
    judge = StubJudge(verdict=True)
    rows = evaluate_clip("clip", [seg(0, 2, "grab")], [seg(0, 2, "take")], judge)
    assert len(judge.queries) == 1
    assert rows[0].action_ok is True
    assert rows[0].action_via == "judge"


def test_judge_rejection_is_mismatch() -> None:
    rows = evaluate_clip("clip", [seg(0, 2, "wash")], [seg(0, 2, "take")],
                         StubJudge(verdict=False))
    assert rows[0].action_ok is False
    assert rows[0].action_via == "mismatch"
    assert metrics_for(rows)["action_acc"] == 0.0


def test_keyframe_inside_gt_interval() -> None:
    pred = [seg(0, 2, keyframe=1.0)]
    gt = [seg(0, 2, keyframe=0.5)]
    assert metrics_for(evaluate_clip("clip", pred, gt, StubJudge()))["keyframe_in_gt_rate"] == 1.0


def test_strict_accuracy_counts_missed_segments() -> None:
    pred = [seg(0, 2)]
    gt = [seg(0, 2), seg(10, 12)]
    metrics = metrics_for(evaluate_clip("clip", pred, gt, StubJudge()))
    assert metrics["both_acc"] == 1.0
    assert metrics["both_acc_strict"] == 0.5


def test_results_csv_has_a_total_row(tmp_path: Path) -> None:
    rows_a = evaluate_clip("a", [seg(0, 2)], [seg(0, 2)], StubJudge())
    rows_b = evaluate_clip("b", [], [seg(0, 2)], StubJudge())
    path = tmp_path / "results.csv"
    total = write_results_csv({"a": rows_a, "b": rows_b}, path)

    with path.open(encoding="utf-8") as fh:
        table = list(csv.DictReader(fh))
    assert [r["clip"] for r in table] == ["a", "b", "__ALL__"]
    assert total["tp"] == 1
    assert total["fn"] == 1
    assert total["f1@0.5"] == 2 / 3
