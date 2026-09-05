from __future__ import annotations

import json
from pathlib import Path

from eval import main

SEG = {"id": "a", "start": 0.0, "end": 2.0, "action": "open",
       "object": "drawer", "keyframe": 1.0}


def _dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    pred, gt, out = tmp_path / "pred", tmp_path / "gt", tmp_path / "out"
    pred.mkdir()
    gt.mkdir()
    return pred, gt, out


def _write(directory: Path, name: str, segments: list[dict]) -> None:
    (directory / name).write_text(json.dumps({"segments": segments}), encoding="utf-8")


def test_perfect_run_exits_zero(tmp_path: Path, capsys) -> None:
    pred, gt, out = _dirs(tmp_path)
    _write(pred, "clip.json", [SEG])
    _write(gt, "clip.json", [SEG])
    code = main(["--pred", str(pred), "--gt", str(gt), "--out-dir", str(out),
                 "--no-judge"])
    assert code == 0
    assert (out / "matching.csv").exists()
    assert (out / "results.csv").exists()
    assert "PASS" in capsys.readouterr().out


def test_failing_thresholds_exit_one(tmp_path: Path) -> None:
    pred, gt, out = _dirs(tmp_path)
    _write(pred, "clip.json", [])
    _write(gt, "clip.json", [SEG])
    code = main(["--pred", str(pred), "--gt", str(gt), "--out-dir", str(out),
                 "--no-judge"])
    assert code == 1


def test_missing_prediction_is_counted_as_failure(tmp_path: Path, capsys) -> None:
    pred, gt, out = _dirs(tmp_path)
    _write(gt, "clip.json", [SEG])
    code = main(["--pred", str(pred), "--gt", str(gt), "--out-dir", str(out),
                 "--no-judge"])
    assert code == 1
    assert "missing" in capsys.readouterr().out


def test_broken_gt_exits_two(tmp_path: Path) -> None:
    pred, gt, out = _dirs(tmp_path)
    _write(pred, "clip.json", [SEG])
    (gt / "clip.json").write_text("{not json", encoding="utf-8")
    assert main(["--pred", str(pred), "--gt", str(gt), "--out-dir", str(out),
                 "--no-judge"]) == 2


def test_reversed_gt_bounds_exit_two(tmp_path: Path) -> None:
    pred, gt, out = _dirs(tmp_path)
    _write(pred, "clip.json", [SEG])
    _write(gt, "clip.json", [{**SEG, "start": 5.0, "end": 1.0}])
    assert main(["--pred", str(pred), "--gt", str(gt), "--out-dir", str(out),
                 "--no-judge"]) == 2


def test_empty_gt_directory_exits_two(tmp_path: Path) -> None:
    pred, gt, out = _dirs(tmp_path)
    assert main(["--pred", str(pred), "--gt", str(gt), "--out-dir", str(out),
                 "--no-judge"]) == 2


def test_disabled_judge_is_reported(tmp_path: Path, capsys) -> None:
    pred, gt, out = _dirs(tmp_path)
    _write(pred, "clip.json", [{**SEG, "action": "grab"}])
    _write(gt, "clip.json", [SEG])
    main(["--pred", str(pred), "--gt", str(gt), "--out-dir", str(out), "--no-judge"])
    assert "judge: disabled" in capsys.readouterr().out