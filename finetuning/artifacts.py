"""Lightweight JSON artifacts shared by preparation, training, and inference."""

from __future__ import annotations

import json
from pathlib import Path


def read_jsonl(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def write_json(path: str | Path, value: object) -> None:
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_run(path: str | Path) -> tuple[Path, dict]:
    """Selected adapters own their assets; Trainer checkpoints use their parent run."""
    assets = Path(path).resolve()
    if (not (assets / "run.json").is_file() and assets.name.startswith("checkpoint-")
            and (assets / "trainer_state.json").is_file()):
        assets = assets.parent
    return assets, json.loads((assets / "run.json").read_text(encoding="utf-8"))
