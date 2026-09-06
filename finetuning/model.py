"""Native Marlin preprocessing, frozen vision features, and language-only LoRA."""

from __future__ import annotations

import math

import torch
from transformers import AutoProcessor, Qwen3_5ForConditionalGeneration

from data import PROMPT, TARGET_MODE, scene_prefix

MODEL = "NemoStation/Marlin-2B"
REVISION = "fd111fca4fc7897876fb0d7e9df22ca5ac8ab965"
PREPROCESS = {
    "fps": 2.0,
    "min_frames": 4,
    "max_frames": 240,
    "min_pixels": 4096,
    "max_pixels": 25_165_824,
}


def load_model(model_id=MODEL, revision=REVISION, device="cuda"):
    # Marlin's remote class only adds caption/find wrappers; its forward is native.
    model = Qwen3_5ForConditionalGeneration.from_pretrained(
        model_id,
        revision=revision,
        trust_remote_code=False,
        dtype=torch.bfloat16 if str(device).startswith("cuda") else torch.float32,
        device_map={"": device},
        attn_implementation="sdpa",
    )
    model.model.visual.requires_grad_(False)
    return model.eval()


def load_processor(model_id=MODEL, revision=REVISION):
    return AutoProcessor.from_pretrained(model_id, revision=revision, trust_remote_code=False)


def render_prompt(processor, video, duration, prompt=PROMPT):
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Video duration must be finite and positive")

    messages = [{"role": "user", "content": [
        {"type": "video", "video": str(video)},
        {"type": "text", "text": prompt},
    ]}]

    return processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
    )


def video_inputs(processor, video, duration, settings=PREPROCESS, *, prompt=PROMPT, **kwargs):
    """Process a video once, keeping native frame timestamps and explicit limits."""
    settings = {**PREPROCESS, **settings}
    if settings["fps"] <= 0 or settings["min_frames"] < 2 or settings["max_frames"] < settings["min_frames"]:
        raise ValueError("Invalid frame sampling limits")

    video_processor = processor.video_processor
    if not 0 < settings["min_pixels"] <= settings["max_pixels"]:
        raise ValueError("Invalid total video pixel limits")

    for key in ("fps", "min_frames", "max_frames"):
        setattr(video_processor, key, settings[key])
    video_processor.size = {
        "shortest_edge": settings["min_pixels"],
        "longest_edge": settings["max_pixels"],
    }
    video_processor.cap_pixels_per_frame = False

    return processor(
        text=render_prompt(processor, video, duration, prompt),
        videos=[str(video)], return_tensors="pt", add_special_tokens=False, **kwargs,
    )


@torch.no_grad()
def encode_visual(model, processor, record, settings=PREPROCESS, *,
                  max_new_tokens=1024, max_length=32_768):
    """Generate a base-model scene and capture its vision features in the same forward pass."""
    if max_new_tokens < 1:
        raise ValueError("Scene generation needs a positive token budget")

    inputs = video_inputs(processor, record["video"], record["duration"], settings,
                          return_text_replacement_offsets=True)
    replacements = inputs.pop("text_replacement_offsets")[0]
    if len(replacements) != 1 or replacements[0]["type"] != "video":
        raise ValueError("Expected exactly one native video placeholder replacement")
    length = inputs["input_ids"].shape[1]
    if length + max_new_tokens > max_length:
        raise ValueError("Video prompt plus scene budget exceeds --max-length; lower video limits "
                         "or --scene-max-new-tokens, or raise --max-length")

    device = model.get_input_embeddings().weight.device
    features = []

    def capture_features(module, args, output):
        features.append(output.pooler_output.cpu().contiguous())

    model.eval()
    with model.model.visual.register_forward_hook(capture_features):
        output = model.generate(
            **{key: value.to(device) for key, value in inputs.items()},
            max_new_tokens=max_new_tokens, do_sample=False, use_cache=True,
            stop_strings=["\nEvents:"], tokenizer=processor.tokenizer,
        )

    raw = processor.tokenizer.decode(output[0, length:], skip_special_tokens=True,
                                     clean_up_tokenization_spaces=False)
    try:
        scene = scene_prefix(raw)
    except ValueError as error:
        raise ValueError(f"{record['video']}: base Marlin did not complete a Scene: paragraph "
                         "followed by Events:; check the clip or increase --scene-max-new-tokens") from error

    if len(features) != 1:
        raise ValueError("Scene generation must encode the video exactly once")
    features = features[0]
    video_indices = torch.where(inputs["input_ids"][0] == model.config.video_token_id)[0]
    if features.shape[0] != len(video_indices) or not len(video_indices):
        raise ValueError("Video placeholder count does not match cached vision features")

    position_ids, _ = model.model.get_rope_index(
        input_ids=inputs["input_ids"],
        mm_token_type_ids=inputs["mm_token_type_ids"],
        video_grid_thw=inputs["video_grid_thw"],
        attention_mask=inputs["attention_mask"],
    )

    prefix_length = video_indices[-1].item() + 1
    visual = {
        "scene": scene,
        "video_text": replacements[0]["replacement"],
        "video_features": features.cpu().contiguous(),
        "video_grid_thw": inputs["video_grid_thw"].cpu(),
        "prefix_input_ids": inputs["input_ids"][:, :prefix_length].cpu().contiguous(),
        "prefix_position_ids": position_ids[:, :, :prefix_length].cpu().contiguous(),
    }

    # Verify native tokenization and every mRoPE coordinate before persisting the reusable artifact.
    rebuilt = assemble_example(processor, dict(record, target=""), visual, max_length=None)
    if not torch.equal(rebuilt["input_ids"][:, :length], inputs["input_ids"]):
        raise ValueError("Reassembled video prompt differs from native tokenization")
    if not torch.equal(rebuilt["position_ids"][:, :, :length], position_ids):
        raise ValueError("Reassembled video positions differ from native multimodal RoPE")

    return visual


def assemble_example(processor, record, visual, max_length=32_768, prompt=PROMPT):
    """Rebuild task/target tensors using cached native video text; no video decoding or model needed."""
    if record.get("target_mode") != TARGET_MODE:
        raise ValueError("Expected caption targets; prepare the data again")

    rendered = render_prompt(processor, record["video"], record["duration"], prompt)
    if rendered.count(processor.video_token) != 1:
        raise ValueError("Expected one video placeholder in the rendered chat template")

    expanded, _ = processor.get_text_with_replacements([rendered], videos_replacements=[visual["video_text"]])
    prompt_ids = processor.tokenizer(expanded, add_special_tokens=False, return_tensors="pt")["input_ids"]
    target = processor.tokenizer(record["target"] + "<|im_end|>",
                                 add_special_tokens=False, return_tensors="pt")["input_ids"]
    input_ids = torch.cat((prompt_ids, target), dim=1)
    if max_length is not None and input_ids.shape[1] > max_length:
        raise ValueError(f"{record['video']}: {input_ids.shape[1]} tokens exceeds max_length={max_length}; "
                         "lower video pixel/frame limits or raise max_length")

    prefix = visual["prefix_input_ids"]
    if not torch.equal(input_ids[:, :prefix.shape[1]], prefix):
        raise ValueError("Chat prefix changed before the last video token; rebuild the visual cache")

    native_positions = visual["prefix_position_ids"]
    suffix = torch.arange(input_ids.shape[1] - prefix.shape[1]) + native_positions.max().item() + 1
    position_ids = torch.cat((native_positions, suffix.view(1, 1, -1).expand(3, 1, -1)), dim=2)

    labels = input_ids.clone()
    labels[:, :prompt_ids.shape[1]] = -100

    return {
        "input_ids": input_ids, "attention_mask": torch.ones_like(input_ids),
        "position_ids": position_ids, "labels": labels, "prompt_length": prompt_ids.shape[1],
    }


def cached_forward(model, batch):
    """Assistant-only next-token loss without re-running vision or projecting prompt logits."""
    embedding = model.get_input_embeddings()
    input_ids = batch["input_ids"].to(embedding.weight.device)
    labels = batch["labels"].to(input_ids.device)
    if input_ids.ndim != 2 or input_ids.shape[0] != 1 or labels.shape != input_ids.shape:
        raise ValueError("Cached training expects one unpadded video per microbatch")

    embeds = embedding(input_ids)
    features = batch["video_features"].to(device=embeds.device, dtype=embeds.dtype)
    video_mask = input_ids == model.config.video_token_id
    if features.ndim != 2 or features.shape != (video_mask.sum().item(), embeds.shape[-1]):
        raise ValueError("Cached features do not match video placeholders and hidden dimension")
    embeds = embeds.masked_scatter(video_mask.unsqueeze(-1), features)

    supervised = torch.where(labels[0] != -100)[0]
    if not len(supervised) or supervised[0].item() == 0:
        raise ValueError("Missing assistant labels or no prefix preceding the first target")

    outputs = model(
        inputs_embeds=embeds,
        attention_mask=batch["attention_mask"].to(embeds.device),
        position_ids=batch["position_ids"].to(embeds.device),
        logits_to_keep=supervised - 1,
        use_cache=False,
        return_dict=True,
    )

    return torch.nn.functional.cross_entropy(outputs.logits[0].float(), labels[0, supervised])


def add_lora(model, rank=16, alpha=32):
    from peft import LoraConfig, get_peft_model

    if rank <= 0 or alpha <= 0:
        raise ValueError("LoRA rank and alpha must be positive")

    targets = [
        name for name, module in model.named_modules()
        if name.startswith("model.language_model.layers.") and isinstance(module, torch.nn.Linear)
    ]
    if not targets:
        raise ValueError("No native Qwen3.5 language projections found")

    return get_peft_model(model, LoraConfig(
        task_type="CAUSAL_LM", r=rank, lora_alpha=alpha,
        lora_dropout=0.0, bias="none", target_modules=targets,
    ))
