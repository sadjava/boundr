"""Train language-only LoRA from cached Marlin video features."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

import torch
from transformers import Trainer, TrainingArguments, set_seed

from artifacts import load_run, read_jsonl, write_json
from cache import pipeline_hash
from data import HERE, PROMPT, TARGET_MODE
from model import add_lora, cached_forward, load_model, load_processor


class CachedDataset(torch.utils.data.Dataset):
    def __init__(self, path):
        self.records = read_jsonl(path)
        for record in self.records:
            for key in ("cache", "visual_cache"):
                if not Path(record[key]).is_file():
                    raise FileNotFoundError(record[key])

    def __len__(self):
        return len(self.records)

    def __getitem__(self, index):
        record = self.records[index]
        example = torch.load(record["cache"], map_location="cpu", weights_only=True)
        visual = torch.load(record["visual_cache"], map_location="cpu", weights_only=True)
        return dict(example, video_features=visual["video_features"])


def single_example(examples):
    # ponytail: batch size 1 avoids video padding; add a padded collator if throughput warrants it.
    if len(examples) != 1:
        raise ValueError("Cached video training requires per-device batch size 1.")
    return examples[0]


class CachedTrainer(Trainer):
    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        loss = cached_forward(model, inputs)
        return (loss, {"loss": loss}) if return_outputs else loss


def resume_metadata(checkpoint, output, run):
    """Validate the selected checkpoint's run before restoring any training state."""
    _, previous = load_run(checkpoint)
    if previous != load_run(output)[1]:
        raise ValueError("Resume checkpoint and output directory belong to different runs.")

    expected = dict(run)
    if "continuation" in previous:
        expected["continuation"] = previous["continuation"]
    if previous != expected:
        raise ValueError("Resume requires the same cache and training settings.")

    return previous


def continuation_metadata(checkpoint, metadata, rank, alpha):
    """Require compatible base weights and LoRA dimensions for a new training phase."""
    checkpoint = Path(checkpoint).resolve()
    for name in ("adapter_model.safetensors", "adapter_config.json", "optimizer.pt", "trainer_state.json"):
        if not (checkpoint / name).is_file():
            raise FileNotFoundError(checkpoint / name)

    _, old = load_run(checkpoint)
    config = json.loads((checkpoint / "adapter_config.json").read_text())
    state = json.loads((checkpoint / "trainer_state.json").read_text())
    if any(old.get(key) != metadata.get(key) for key in ("model", "revision", "target_mode", "prompt")):
        raise ValueError("Continuation requires the same base model, revision, prompt, and target format")
    if (old["rank"], old["alpha"], config["r"], config["lora_alpha"]) != (rank, alpha, rank, alpha):
        raise ValueError("Continuation requires the original LoRA rank and alpha")

    return {
        "checkpoint": str(checkpoint),
        "adapter_sha256": hashlib.sha256((checkpoint / "adapter_model.safetensors").read_bytes()).hexdigest(),
        "global_step": state["global_step"], "epoch": state["epoch"],
        "completed_epochs": old.get("continuation", {}).get("completed_epochs", 0) + state["epoch"],
        "optimizer": "restored moments", "schedule": "fresh cosine with warmup",
        "training_clock": "new phase from step zero",
    }


def restore_optimizer(trainer, checkpoint):
    """Retain Adam moments while resetting the completed schedule's zero learning rate."""
    if trainer.lr_scheduler is not None:
        raise ValueError("Restore continuation optimizer before creating its fresh scheduler")

    optimizer = trainer.create_optimizer()
    saved = torch.load(Path(checkpoint) / "optimizer.pt", map_location="cpu", weights_only=True)
    if len(saved["param_groups"]) != len(optimizer.param_groups):
        raise ValueError("Continuation optimizer parameter groups do not match")

    for old, new in zip(saved["param_groups"], optimizer.param_groups):
        if len(old["params"]) != len(new["params"]):
            raise ValueError("Continuation optimizer parameter counts do not match")
        for index, parameter in zip(old["params"], new["params"]):
            state = saved["state"].get(index, {})
            if any(key not in state or state[key].shape != parameter.shape for key in ("exp_avg", "exp_avg_sq")):
                raise ValueError("Continuation optimizer moments do not match the adapter")

    optimizer.load_state_dict(saved)
    for group in optimizer.param_groups:
        group["lr"] = group["initial_lr"] = trainer.args.learning_rate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=HERE / "cache")
    parser.add_argument("--output", type=Path, default=HERE / "adapter")
    parser.add_argument("--epochs", type=float, default=3)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--alpha", type=int, default=32)
    parser.add_argument("--accumulation", type=int, default=4)
    parser.add_argument("--max-steps", type=int, default=-1)
    parser.add_argument("--seed", type=int, default=42)
    start = parser.add_mutually_exclusive_group()
    start.add_argument("--resume", type=str, help="Resume an interrupted phase with identical data/settings.")
    start.add_argument("--continue-from", type=Path,
                       help="Start --epochs additional epochs from this adapter and optimizer, with a fresh schedule.")
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")

    args = parser.parse_args()
    if min(args.rank, args.alpha, args.accumulation, args.epochs, args.learning_rate) <= 0:
        parser.error("Training hyperparameters must be positive")
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable. Run in a GPU-enabled environment.")
    if (args.cache / ".building").exists():
        raise ValueError("Cache preparation is incomplete; rerun cache.py before training.")

    metadata = json.loads((args.cache / "metadata.json").read_text())
    if (metadata.get("schema") != 4 or metadata.get("target_mode") != TARGET_MODE or
            metadata.get("prompt") != PROMPT or
            metadata["pipeline_sha256"] != pipeline_hash(metadata["prompt"]) or
            metadata["transformers"] != importlib.metadata.version("transformers")):
        raise ValueError("Cache code/Transformers version mismatch; rebuild the cache.")

    train = CachedDataset(args.cache / "train.jsonl")
    val = CachedDataset(args.cache / "val.jsonl")
    if not len(train):
        raise ValueError("Empty training cache")

    run = dict(metadata, rank=args.rank, alpha=args.alpha, seed=args.seed,
               learning_rate=args.learning_rate, accumulation=args.accumulation,
               epochs=args.epochs, max_steps=args.max_steps,
               train_fingerprints=[r["fingerprint"] for r in train.records],
               val_fingerprints=[r["fingerprint"] for r in val.records])
    if args.continue_from:
        run["continuation"] = continuation_metadata(args.continue_from, metadata, args.rank, args.alpha)

    if args.output.exists() and any(args.output.iterdir()) and not args.resume:
        raise ValueError("Output is not empty; choose a new --output or use --resume CHECKPOINT.")
    if args.resume:
        run = resume_metadata(args.resume, args.output, run)

    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output / "run.json", run)

    set_seed(args.seed)
    model = load_model(metadata["model"], metadata["revision"], "cpu")
    # The complete tower (including merger) is already cached. Restore it from the base at inference.
    model.model.visual = None
    if args.device == "cuda":
        model.to(dtype=torch.bfloat16)
    if args.continue_from:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, str(args.continue_from), is_trainable=True)
    else:
        model = add_lora(model, args.rank, args.alpha)
    model.print_trainable_parameters()

    processor = load_processor(metadata["model"], metadata["revision"])
    processor.save_pretrained(args.output)

    training_args = TrainingArguments(
        output_dir=str(args.output), num_train_epochs=args.epochs, max_steps=args.max_steps,
        per_device_train_batch_size=1, per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.accumulation, learning_rate=args.learning_rate,
        lr_scheduler_type="cosine", warmup_steps=0.05, weight_decay=0.01,
        bf16=args.device == "cuda", use_cpu=args.device == "cpu",
        gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False},
        eval_strategy="epoch" if len(val) else "no", save_strategy="epoch",
        load_best_model_at_end=bool(len(val)),
        metric_for_best_model="eval_loss",
        greater_is_better=False, save_total_limit=2, logging_steps=1,
        remove_unused_columns=False, label_names=["labels"], prediction_loss_only=True,
        report_to="none", seed=args.seed, dataloader_num_workers=0,
    )

    trainer = CachedTrainer(model=model, args=training_args, train_dataset=train,
                            eval_dataset=val if len(val) else None, data_collator=single_example)
    trainer.model_accepts_loss_kwargs = False
    if args.continue_from:
        restore_optimizer(trainer, args.continue_from)
        print(f"Continuing {args.continue_from}: adapter and optimizer restored; "
              f"{args.epochs} new epochs with a fresh learning-rate schedule.", flush=True)

    result = trainer.train(resume_from_checkpoint=args.resume)

    trainer.save_model(str(args.output))
    trainer.save_state()
    trainer.save_metrics("train", result.metrics)
    if len(val):
        trainer.save_metrics("eval", trainer.evaluate())


if __name__ == "__main__":
    main()
