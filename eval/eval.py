from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from evallib.judge import Judge
from evallib.loader import LoadError, load_annotation, partition_valid
from evallib.report import (
    PairRow,
    evaluate_clip,
    fmt_metric,
    metrics_for,
    write_matching_csv,
    write_results_csv,
)

THRESHOLDS = [("f1@0.5", 0.75), ("within_2s_rate", 0.75), ("both_acc", 0.80)]

_ROOT = Path(__file__).resolve().parent


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare predicted annotations against reference ones.")
    parser.add_argument("--pred", required=True, type=Path)
    parser.add_argument("--gt", required=True, type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("reports"))
    parser.add_argument("--judge-model", default="openai/gpt-4o-mini")
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--cache", type=Path, default=_ROOT / ".eval_cache.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)

    gt_files = sorted(args.gt.glob("*.json"))
    if not gt_files:
        print(f"error: no reference json files in {args.gt}", file=sys.stderr)
        return 2

    api_key = None if args.no_judge else os.environ.get("OPENROUTER_API_KEY")
    judge = Judge(
        model=args.judge_model,
        api_key=api_key,
        cache_path=args.cache,
        base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
    )

    per_clip: dict[str, list[PairRow]] = {}
    missing: list[str] = []

    for gt_path in gt_files:
        clip = gt_path.stem
        try:
            gt_segments = load_annotation(gt_path)
        except LoadError as exc:
            print(f"error: broken reference annotation — {exc}", file=sys.stderr)
            return 2
        valid_gt, invalid_gt = partition_valid(gt_segments)
        if invalid_gt:
            print(f"error: {gt_path}: start > end in {len(invalid_gt)} segments",
                  file=sys.stderr)
            return 2

        pred_path = args.pred / gt_path.name
        if not pred_path.exists():
            missing.append(clip)
            pred_segments: list = []
        else:
            try:
                pred_segments, _ = partition_valid(load_annotation(pred_path))
            except LoadError as exc:
                print(f"warning: unreadable prediction, treated as empty — {exc}")
                pred_segments = []

        per_clip[clip] = evaluate_clip(clip, pred_segments, valid_gt, judge)

    judge.save_cache()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    all_rows = [row for rows in per_clip.values() for row in rows]
    write_matching_csv(all_rows, args.out_dir / "matching.csv")
    total = write_results_csv(per_clip, args.out_dir / "results.csv")

    _print_report(per_clip, total, judge, missing, args.out_dir)
    return 0 if all(total[name] >= limit for name, limit in THRESHOLDS) else 1


def _print_report(per_clip, total, judge: Judge, missing: list[str],
                  out_dir: Path) -> None:
    if judge.disabled:
        print(f"judge: disabled ({judge.mismatch_count} "
              f"{'pair' if judge.mismatch_count == 1 else 'pairs'} "
              f"counted as mismatch)")
    else:
        print(f"judge: {judge.model}")
    if missing:
        print(f"missing predictions: {', '.join(missing)}")

    print(f"\n{'clip':<24}{'tp':>4}{'fp':>4}{'fn':>4}{'F1@0.5':>9}"
          f"{'within2s':>10}{'both_acc':>10}")
    for clip, rows in per_clip.items():
        _print_row(clip, metrics_for(rows))
    _print_row("__ALL__", total)

    print()
    for name, limit in THRESHOLDS:
        verdict = "PASS" if total[name] >= limit else "FAIL"
        print(f"{verdict}  {name} = {fmt_metric(total[name])} (threshold {limit})")
    print(f"\nreports: {out_dir / 'results.csv'}, {out_dir / 'matching.csv'}")


def _print_row(clip: str, metrics: dict[str, float | int]) -> None:
    print(f"{clip:<24}{metrics['tp']:>4}{metrics['fp']:>4}{metrics['fn']:>4}"
          f"{fmt_metric(metrics['f1@0.5']):>9}"
          f"{fmt_metric(metrics['within_2s_rate']):>10}"
          f"{fmt_metric(metrics['both_acc']):>10}")


if __name__ == "__main__":
    raise SystemExit(main())