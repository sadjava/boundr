"""Check Marlin caption target construction from ground-truth annotations."""

from __future__ import annotations

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


if __name__ == "__main__":
    check_targets()
