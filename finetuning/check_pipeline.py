"""Check target construction; optionally check real tokenizer supervision using a visual cache."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import tempfile

from data import HERE, PROMPT, TARGET_MODE, action_events, format_caption, prepare, scene_prefix


def check_targets():
    product = ast.parse((HERE.parent / "ml-service/app/inference/marlin/infer.py").read_text())
    original_prompt = next(ast.literal_eval(node.value) for node in product.body
                           if isinstance(node, ast.Assign)
                           and any(isinstance(t, ast.Name) and t.id == "PROMPT" for t in node.targets))
    assert PROMPT == original_prompt

    prefix = "Scene: A drawer and a light switch.  The camera faces the wall."
    raw = prefix + "\n\nEvents:\n<0 - 4> A deliberately incorrect original event."
    annotation = dict(video_id="clip", duration=4, segments=[
        dict(start=1, end=3, action="turn_on", object="ceiling_light"),
        dict(start=1.5, end=2, action="open", object="drawer"),
    ])
    expected = prefix + "\n\nEvents:\n<1.0 - 3.0> turn on | ceiling light\n<1.5 - 2.0> open | drawer"
    assert format_caption(scene_prefix(raw), action_events(annotation)) == expected
    assert format_caption(prefix, action_events(dict(annotation, segments=[]))) == prefix + "\n\nEvents:\n"

    for segments in ([dict(start=-1, end=2, action="open", object="drawer")],
                     [dict(start=1, end=2, action="open\nEvents:", object="drawer")],
                     [dict(start=1, end=2, action="open", object="drawer | door")]):
        try:
            action_events(dict(annotation, segments=segments))
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid annotation was accepted")

    try:
        scene_prefix("Scene: An unfinished description")
    except ValueError:
        pass
    else:
        raise AssertionError("An incomplete scene was accepted")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for split in ("train", "eval"):
            for source_name in ("example", "nested/source"):
                source = root / split / source_name
                for name in ("annotations", "video"):
                    (source / name).mkdir(parents=True)
                (source / "video/clip.mp4").touch()
                (source / "annotations/clip.json").write_text(json.dumps(annotation))

        summary = prepare(root / "train", root / "prepared", root / "eval")
        records = [json.loads(line) for line in (root / "prepared/train.jsonl").read_text().splitlines()]
        assert {record["source"] for record in records} == {"example", "nested/source"}
        for record in records:
            assert "target" not in record and record["target_mode"] == TARGET_MODE
            assert record["reference_actions"][0]["object"] == "ceiling_light"
            assert record["annotation_sha256"]
        assert summary["train"] == summary["val"] == 2

    print("target construction: ok")


def check_supervision(cache, processor_path):
    import torch

    from model import assemble_example, load_processor, render_prompt

    record = json.loads((cache / "train.jsonl").read_text().splitlines()[0])
    original = json.loads(Path(record["annotation"]).read_text())
    visual = torch.load(record["visual_cache"], map_location="cpu", weights_only=True)
    assert record["target"] == format_caption(visual["scene"], action_events(original))

    processor = load_processor(str(processor_path), revision=None)
    rendered = render_prompt(processor, record["video"], record["duration"])
    assert PROMPT in rendered and "Clip duration:" not in rendered

    batch = assemble_example(processor, record, visual)
    saved = torch.load(record["cache"], map_location="cpu", weights_only=True)
    for key in ("input_ids", "attention_mask", "position_ids", "labels"):
        assert torch.equal(saved[key], batch[key]), key

    length = batch["prompt_length"]
    assert torch.all(batch["labels"][:, :length] == -100)
    assert torch.equal(batch["labels"][:, length:], batch["input_ids"][:, length:])

    supervised = processor.tokenizer.decode(batch["labels"][0, length:], skip_special_tokens=False,
                                             clean_up_tokenization_spaces=False)
    assert supervised == record["target"] + "<|im_end|>"
    special_ids = set(processor.tokenizer.all_special_ids)
    markers = [token for token in batch["labels"][0, length:].tolist() if token in special_ids]
    assert processor.tokenizer.convert_ids_to_tokens(markers) == ["<|im_end|>"]

    print("native prompt and full-response supervision: ok")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visual-cache", type=Path)
    parser.add_argument("--processor", type=Path, help="Local native Marlin processor snapshot")

    args = parser.parse_args()
    if bool(args.visual_cache) != bool(args.processor):
        parser.error("Supply --visual-cache and --processor together")

    check_targets()
    if args.visual_cache:
        check_supervision(args.visual_cache, args.processor)
