"""Generate native Marlin spatial descriptions and timestamped action captions."""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
from peft import PeftModel
from torchcodec.decoders import VideoDecoder

from artifacts import load_run, write_json
from data import HERE, PROMPT, TARGET_MODE, seconds
from model import load_model, load_processor, video_inputs


def load_predictor(adapter=None, device="cuda"):
    """Restore the adapter with its base revision, processor, and preprocessing."""
    adapter = Path(adapter) if adapter is not None else HERE / "adapter"
    assets, run = load_run(adapter)
    if run.get("target_mode") != TARGET_MODE or run.get("prompt") != PROMPT:
        raise ValueError("Adapter must use the caption target format and canonical Marlin prompt")

    processor = load_processor(str(assets), revision=None)
    model = load_model(run["model"], run["revision"], device)
    model = PeftModel.from_pretrained(model, str(adapter))
    return model.eval(), processor, run


def predict(model, processor, run, video, max_new_tokens=2048):
    """Use the canonical prompt and return the generated caption without relabeling."""
    if max_new_tokens < 1:
        raise ValueError("max_new_tokens must be positive")
    if run.get("target_mode") != TARGET_MODE or run.get("prompt") != PROMPT:
        raise ValueError("Expected a native-caption run with the canonical Marlin prompt")

    video = Path(video)
    duration = seconds(float(VideoDecoder(str(video)).metadata.duration_seconds))
    device = model.get_input_embeddings().weight.device
    inputs = video_inputs(processor, str(video), duration, run["preprocess"], prompt=run["prompt"]).to(device)
    if inputs["input_ids"].shape[-1] + max_new_tokens > run["max_length"]:
        raise ValueError("Video prompt plus output budget exceeds training --max-length; "
                         "use a shorter video or lower --max-new-tokens.")

    with torch.inference_mode():
        output = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False,
                                use_cache=True)

    generated = output[0, inputs["input_ids"].shape[-1]:]
    raw = processor.tokenizer.decode(generated, skip_special_tokens=True,
                                     clean_up_tokenization_spaces=False)

    eos = model.generation_config.eos_token_id
    eos = [eos] if isinstance(eos, int) else eos
    truncated = len(generated) == max_new_tokens and int(generated[-1]) not in (eos or [])

    return dict(video=str(video.resolve()), duration=duration, raw=raw,
                target_mode=TARGET_MODE, truncated=truncated)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--adapter", type=Path, help="Adapter directory (default: finetuning/adapter).")
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--output", type=Path, help="Save the raw caption, duration, and truncation status as JSON.")

    args = parser.parse_args()

    model, processor, run = load_predictor(args.adapter, args.device)
    result = predict(model, processor, run, args.video, max_new_tokens=args.max_new_tokens)

    if args.output:
        write_json(args.output, result)
    print(result["raw"])
    if result["truncated"]:
        raise SystemExit("Caption reached --max-new-tokens before EOS; raw text was retained.")


if __name__ == "__main__":
    main()
