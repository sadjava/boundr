from __future__ import annotations

import csv
from pathlib import Path

from evallib.loader import Segment
from evallib.report import evaluate_clip, metrics_for, write_results_csv


class StubJudge:
    """Судья с фиксированным вердиктом или списком вердиктов по порядку запросов."""

    def __init__(self, verdict: bool | list[bool] = True) -> None:
        self.verdict = verdict
        self.queries: list = []

    def judge(self, queries: list) -> list[bool]:
        self.queries.extend(queries)
        if isinstance(self.verdict, bool):
            return [self.verdict] * len(queries)
        return list(self.verdict)


def seg(start, end, action="open", object_="drawer", id_="s"):
    return Segment(id_, start, end, action, object_)


def test_perfect_clip_gives_f1_one() -> None:
    gt = [seg(0, 2), seg(2, 4, "take", "knife")]
    rows = evaluate_clip("clip", gt, gt, StubJudge())
    metrics = metrics_for(rows)
    assert metrics["tp"] == 2
    assert metrics["fp"] == 0
    assert metrics["fn"] == 0
    assert metrics["f1@0.5"] == 1.0
    assert metrics["action_acc"] == 1.0
    assert metrics["object_acc"] == 1.0


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


def test_every_label_pair_goes_to_the_judge_raw() -> None:
    judge = StubJudge()
    evaluate_clip("clip", [seg(0, 2, "Opening")], [seg(0, 2, "open")], judge)
    kinds = [(q.kind, q.pred, q.gt) for q in judge.queries]
    assert kinds == [("action", "Opening", "open"), ("object", "drawer", "drawer")]


def test_judge_decides_synonym() -> None:
    judge = StubJudge(verdict=True)
    rows = evaluate_clip("clip", [seg(0, 2, "grab")], [seg(0, 2, "take")], judge)
    assert len(judge.queries) == 2
    assert rows[0].action_ok is True
    assert rows[0].action_via == "judge"


def test_judge_rejection_is_mismatch() -> None:
    rows = evaluate_clip("clip", [seg(0, 2, "wash")], [seg(0, 2, "take")],
                         StubJudge(verdict=False))
    assert rows[0].action_ok is False
    assert rows[0].action_via == "mismatch"
    assert metrics_for(rows)["action_acc"] == 0.0


def test_action_and_object_accuracy_are_independent() -> None:
    pred = [seg(0, 2, "grab", "drawer")]
    gt = [seg(0, 2, "take", "drawer")]
    rows = evaluate_clip("clip", pred, gt, StubJudge(verdict=[False, True]))
    metrics = metrics_for(rows)
    assert metrics["action_acc"] == 0.0
    assert metrics["object_acc"] == 1.0


def test_missed_segment_does_not_lower_label_accuracy() -> None:
    pred = [seg(0, 2)]
    gt = [seg(0, 2), seg(10, 12)]
    metrics = metrics_for(evaluate_clip("clip", pred, gt, StubJudge()))
    assert metrics["action_acc"] == 1.0
    assert metrics["object_acc"] == 1.0
    assert metrics["fn"] == 1
    assert metrics["f1@0.5"] == 2 / 3


def test_results_csv_has_a_total_row(tmp_path: Path) -> None:
    rows_a = evaluate_clip("a", [seg(0, 2)], [seg(0, 2)], StubJudge())
    rows_b = evaluate_clip("b", [], [seg(0, 2)], StubJudge())
    path = tmp_path / "results.csv"
    total = write_results_csv({"a": rows_a, "b": rows_b}, path)

    with path.open(encoding="utf-8") as fh:
        table = list(csv.DictReader(fh))
    assert [r["clip"] for r in table] == ["a", "b", "__ALL__"]
    assert "action_acc" in table[0]
    assert "object_acc" in table[0]
    assert "both_acc" not in table[0]
    assert "keyframe_in_gt_rate" not in table[0]
    assert total["tp"] == 1
    assert total["fn"] == 1
    assert total["f1@0.5"] == 2 / 3


def test_many_mode_does_not_double_count_a_reused_prediction() -> None:
    pred = [seg(0, 9)]
    gt = [seg(0, 3), seg(3, 6), seg(6, 9)]
    metrics = metrics_for(evaluate_clip("clip", pred, gt, StubJudge(), matching="many"))
    assert (metrics["n_pred"], metrics["n_gt"]) == (1, 3)
    assert (metrics["fp"], metrics["fn"]) == (0, 0)
    assert metrics["f1@0.5"] == 1.0


def test_many_mode_still_penalises_a_missed_step() -> None:
    pred = [seg(0, 3)]
    gt = [seg(0, 3), seg(30, 33)]
    metrics = metrics_for(evaluate_clip("clip", pred, gt, StubJudge(), matching="many"))
    assert metrics["fn"] == 1
    assert metrics["f1@0.5"] < 1.0
