"""Generate base Marlin scenes and cache frozen video features and training targets."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import inspect
import json
from pathlib import Path

import torch
from transformers import AutoConfig

from artifacts import read_jsonl, write_json
from data import HERE, PROMPT, TARGET_MODE, format_caption, review_sample, scene_prefix, write_review
from model import (MODEL, PREPROCESS, REVISION, assemble_example, encode_visual,
                   load_model, load_processor, render_prompt, video_inputs)


def pipeline_hash(prompt=PROMPT):
    code = (HERE / "model.py").read_bytes() + (HERE / "data.py").read_bytes()
    return hashlib.sha256(code + prompt.encode()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def visual_fingerprint(record, metadata):
    video = Path(record["video"]).resolve()
    stat = video.stat()
    return digest(dict(video=str(video), size=stat.st_size, mtime_ns=stat.st_mtime_ns, metadata=metadata))


def save_tensors(path, value):
    temporary = path.with_suffix(".pt.tmp")
    torch.save(value, temporary)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, default=HERE / "prepared")
    parser.add_argument("--output", type=Path, default=HERE / "cache")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--revision", default=REVISION)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--fps", type=float, default=PREPROCESS["fps"])
    parser.add_argument("--max-frames", type=int, default=PREPROCESS["max_frames"])
    parser.add_argument("--max-pixels", type=int, default=PREPROCESS["max_pixels"])
    parser.add_argument("--max-length", type=int, default=32768)
    parser.add_argument("--scene-max-new-tokens", type=int, default=1024,
                        help="Base Marlin scene token budget; generation stops at the Events: header.")
    parser.add_argument("--reuse-visual-cache", type=Path,
                        help="Reuse matching frozen features and generated scenes; fail if any are missing.")
    parser.add_argument("--limit", type=int, help="First N examples per split; use a separate smoke cache.")

    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if min(args.max_length, args.scene_max_new_tokens) < 1:
        parser.error("--max-length and --scene-max-new-tokens must be positive")
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; run in a GPU-enabled environment or use --device cpu.")

    settings = dict(PREPROCESS, fps=args.fps, max_frames=args.max_frames, max_pixels=args.max_pixels)
    config = AutoConfig.from_pretrained(args.model, revision=args.revision, trust_remote_code=False)
    revision = config._commit_hash or args.revision
    processor = load_processor(args.model, revision)

    visual_metadata = dict(
        model=args.model, revision=revision, preprocess=settings,
        transformers=importlib.metadata.version("transformers"), torch=torch.__version__,
        video_packages={name: importlib.metadata.version(name) for name in ("torchvision", "torchcodec")},
        processor=processor.to_dict(), chat_template=processor.chat_template, model_config=config.to_dict(),
        dtype="bfloat16" if args.device.startswith("cuda") else "float32",
        scene_prompt=PROMPT, scene_max_new_tokens=args.scene_max_new_tokens,
        code_sha256=hashlib.sha256("".join(inspect.getsource(function) for function in
                                 (load_model, load_processor, render_prompt, video_inputs,
                                  scene_prefix, encode_visual)).encode()).hexdigest(),
    )
    if Path(args.model).is_dir():
        # Local base weights have no immutable Hub commit: file stats invalidate their features.
        visual_metadata["local_weights"] = [
            [str(path.resolve()), path.stat().st_size, path.stat().st_mtime_ns]
            for path in sorted(Path(args.model).iterdir()) if path.suffix in (".safetensors", ".bin")
        ]

    prompt = PROMPT
    if args.reuse_visual_cache:
        if (args.reuse_visual_cache / ".building").exists():
            raise ValueError("The visual cache to reuse is still being built")
        old = json.loads((args.reuse_visual_cache / "metadata.json").read_text())
        if digest(old["visual_metadata"]) != digest(visual_metadata):
            raise ValueError("Reused visual cache has different weights, preprocessing, dtype, or code")

    metadata = dict(model=args.model, revision=revision, preprocess=settings,
                    max_length=args.max_length, pipeline_sha256=pipeline_hash(prompt), prompt=prompt,
                    transformers=importlib.metadata.version("transformers"), schema=4,
                    target_mode=TARGET_MODE,
                    dtype=visual_metadata["dtype"], visual_metadata=visual_metadata)

    args.output.mkdir(parents=True, exist_ok=True)
    for directory in ("visual", "examples"):
        (args.output / directory).mkdir(exist_ok=True)
    metadata_path = args.output / "metadata.json"
    building = args.output / ".building"
    building.write_text("Cache refresh is incomplete; rerun cache.py before training.\n")

    model = None
    for split in ("train", "val"):
        records = read_jsonl(args.prepared / f"{split}.jsonl")
        if any(record.get("target_mode") != TARGET_MODE for record in records):
            raise ValueError("Expected caption targets; rerun data.py prepare")
        if args.limit is not None:
            records = records[:args.limit]

        index = []
        for number, record in enumerate(records, 1):
            visual_key = visual_fingerprint(record, visual_metadata)
            visual_path = args.output / "visual" / f"{visual_key}.pt"
            if args.reuse_visual_cache:
                visual_path = args.reuse_visual_cache / "visual" / f"{visual_key}.pt"
                if not visual_path.is_file():
                    raise FileNotFoundError(f"Matching visual cache is missing: {visual_path}")

            reused = visual_path.exists()
            if reused:
                visual = torch.load(visual_path, map_location="cpu", weights_only=True)
            else:
                if model is None:
                    model = load_model(args.model, revision, args.device)
                    model.requires_grad_(False).eval()
                visual = encode_visual(model, processor, record, settings,
                                       max_new_tokens=args.scene_max_new_tokens, max_length=args.max_length)
                save_tensors(visual_path, visual)

            record = dict(record, target=format_caption(visual["scene"], record["reference_actions"]))
            fingerprint = digest(dict(record=record, visual=visual_key, pipeline=metadata["pipeline_sha256"],
                                      max_length=args.max_length))
            destination = args.output / "examples" / f"{fingerprint}.pt"

            if destination.exists():
                example = torch.load(destination, map_location="cpu", weights_only=True)
            else:
                example = assemble_example(processor, record, visual, args.max_length, prompt=prompt)
                save_tensors(destination, example)

            entry = dict(record, cache=str(destination.resolve()), fingerprint=fingerprint,
                         visual_cache=str(visual_path.resolve()), visual_fingerprint=visual_key,
                         tokens=example["input_ids"].shape[-1], prompt_length=example["prompt_length"])
            index.append(entry)
            print(f"{split} {number}/{len(records)} {record['id']}: "
                  f"{entry['tokens']} tokens, scene/vision {'reused' if reused else 'generated'} "
                  f"({visual_path.stat().st_size / 2**20:.1f} MiB)", flush=True)

        index_path = args.output / f"{split}.jsonl"
        temporary = index_path.with_suffix(".jsonl.tmp")
        temporary.write_text("".join(json.dumps(entry) + "\n" for entry in index))
        temporary.replace(index_path)
        if split == "train":
            write_review(review_sample(index), args.output / "target-review.md")

    write_json(metadata_path, metadata)
    building.unlink()


if __name__ == "__main__":
    main()
