#!/usr/bin/env python3
"""Prepare videos and ground-truth action events for Marlin fine-tuning."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import unicodedata
from pathlib import Path


HERE = Path(__file__).resolve().parent
DATASET = Path(os.environ.get("MARLIN_DATASET_DIR", HERE.parents[1] / "dataset")).expanduser().resolve()

PROMPT = (
    "Provide a spatial description of this clip followed by time-ranged events.\n"
    "For each event, give the time range as <start - end> and a short description."
)
TARGET_MODE = "caption"


def scene_prefix(text: str) -> str:
    """Keep the spatial paragraph verbatim, including its Scene: header."""
    text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.S)
    text = re.sub(r"^\s*<think>\s*", "", text).strip()

    header = re.search(r"^Events:[ \t]*$", text, re.M)
    if header is None or not text.startswith("Scene:"):
        raise ValueError("Expected Scene: followed by Events:")

    prefix = text[:header.start()].rstrip()
    if not prefix.removeprefix("Scene:").strip():
        raise ValueError("Scene description must not be empty")
    return prefix


def format_caption(prefix: str, events: list[dict]) -> str:
    def timestamp(value):
        text = f"{value:.6f}".rstrip("0").rstrip(".")
        return text if "." in text else text + ".0"

    return prefix + "\n\nEvents:\n" + "\n".join(
        f"<{timestamp(event['start'])} - {timestamp(event['end'])}> "
        f"{event['action'].replace('_', ' ')} | {event['object'].replace('_', ' ')}"
        for event in events
    )


def seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Expected finite numeric seconds, got {value!r}")
    return float(value)


def label(value):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"Expected a nonempty label without surrounding whitespace: {value!r}")
    if any(marker in value for marker in ("<", ">", "|", "Scene:", "Events:")) or any(
        unicodedata.category(char).startswith("C") or char in "\u2028\u2029" for char in value
    ):
        raise ValueError(f"Label contains a reserved delimiter, marker, or control character: {value!r}")
    return value


def action_events(annotation):
    """Keep annotated intervals and labels; unannotated time has no invented target."""
    duration = round(seconds(annotation["duration"]), 6)
    if duration <= 0 or not isinstance(annotation["segments"], list):
        raise ValueError("Expected a positive duration and a segments list")

    actions = []
    for segment in annotation["segments"]:
        start, end = seconds(segment["start"]), seconds(segment["end"])
        # Source annotations round to milliseconds, while clip durations retain microseconds.
        if duration < end <= duration + 0.0005:
            end = duration
        if not 0 <= start < end <= duration:
            raise ValueError(f"Action is outside [0, {duration}] or has zero length: {segment!r}")
        start, end = round(start, 6), round(end, 6)
        if start == end:
            raise ValueError(f"Action is shorter than the supported microsecond precision: {segment!r}")

        action, obj = label(segment["action"]), label(segment["object"])
        actions.append({"start": start, "end": end, "action": action, "object": obj})

    actions.sort(key=lambda event: event["start"])
    return actions


def read_records(dataset, split):
    """Pair videos with validated annotation events using the common dataset layout."""
    dataset = Path(dataset).resolve()
    annotations = sorted(dataset.rglob("annotations/*.json"))
    if not annotations:
        raise ValueError(f"No annotations/*.json found under {dataset}")

    records, seen = [], set()
    for path in annotations:
        raw = path.read_bytes()
        annotation = json.loads(raw)
        video_id = annotation["video_id"]
        if video_id != path.stem:
            raise ValueError(f"video_id does not match annotation filename: {path}")

        video = path.parent.parent / "video" / f"{video_id}.mp4"
        if not video.is_file():
            raise FileNotFoundError(video)

        source = path.parent.parent.relative_to(dataset).as_posix()
        record_id = f"{split}/{source}/{video_id}"
        if record_id in seen:
            raise ValueError(f"Duplicate video: {record_id}")
        seen.add(record_id)

        events = action_events(annotation)
        records.append({
            "id": record_id, "video_id": video_id, "video": str(video), "split": split,
            "duration": annotation["duration"], "source": source,
            "target_mode": TARGET_MODE, "reference_actions": events,
            "annotation": str(path), "annotation_sha256": hashlib.sha256(raw).hexdigest(),
        })

    return records


def review_sample(records):
    """Select four representative target examples per source for a text review."""
    if not records or len({record["id"] for record in records}) != len(records):
        raise ValueError("Review records must be nonempty with unique IDs")

    sources = sorted({record["source"] for record in records})
    count = min(4, min(sum(record["source"] == source for record in records) for source in sources))

    panel = []
    for source in sources:
        candidates = sorted((record for record in records if record["source"] == source), key=lambda record: (
            len(record["reference_actions"]) / record["duration"], record["id"],
        ))
        panel.extend(candidates[(2 * index + 1) * len(candidates) // (2 * count)] for index in range(count))

    return panel


def prepare(dataset, output, validation_dataset=None):
    dataset, output = Path(dataset).resolve(), Path(output).resolve()
    validation_dataset = Path(validation_dataset or dataset.parent / "eval").resolve()
    if dataset == validation_dataset:
        raise ValueError("Training and validation must use different dataset directories")

    splits = {"train": read_records(dataset, "train"), "val": read_records(validation_dataset, "eval")}
    videos = [{Path(record["video"]).resolve() for record in split_records} for split_records in splits.values()]
    if not videos[0].isdisjoint(videos[1]):
        raise ValueError("A video is present in both training and validation")

    records = splits["train"] + splits["val"]

    output.mkdir(parents=True, exist_ok=True)
    for split, split_records in splits.items():
        (output / f"{split}.jsonl").write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in split_records),
            encoding="utf-8",
        )

    summary = {"dataset": str(dataset), "validation_dataset": str(validation_dataset),
               "videos": len(records),
               "train": len(splits["train"]), "val": len(splits["val"]),
               "hours": sum(record["duration"] for record in records) / 3600,
               "sources": {source: {
                   split: sum(record["source"] == source for record in split_records)
                   for split, split_records in splits.items()
               } for source in sorted({record["source"] for record in records})}}
    summary["target_mode"] = TARGET_MODE
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    return summary


def write_review(records, output):
    lines = ["# Marlin target review", "",
             "Targets combine scenes generated by base Marlin during caching with ground-truth events.",
             "Scene paragraphs retain the model descriptions, including any inaccuracies.", ""]

    for record in records:
        lines.extend([f"## {record['id']}", "",
                      "```text", record["target"], "```", ""])

    Path(output).write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("prepare", help="Prepare videos and ground-truth action events")
    command.add_argument("--dataset", type=Path, default=DATASET / "train",
                         help="Training directory (default: $MARLIN_DATASET_DIR/train or ../../dataset/train)")
    command.add_argument("--validation-dataset", type=Path,
                         help="Validation directory (default: eval beside --dataset)")
    command.add_argument("--output", type=Path, default=HERE / "prepared")

    args = parser.parse_args()

    print(json.dumps(prepare(args.dataset, args.output, args.validation_dataset), indent=2))


if __name__ == "__main__":
    main()
