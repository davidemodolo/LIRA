#!/usr/bin/env python
"""Single-command LIRA finetuning pipeline.

Follows the official Google FunctionGemma finetuning guide:
https://ai.google.dev/gemma/docs/functiongemma/finetuning-with-functiongemma

Just run:
    uv run python -m finetune.run

Steps:
  1. Extract MCP tool schemas from the LIRA codebase
  2. Build dataset, augmenting seed examples via Ollama (reads .env)
  3. Unload Ollama model from VRAM
  4. Full fine-tune FunctionGemma on NVIDIA GPU
  5. Save model to finetune/output/lira-agent/

After training, set in .env:
    LLM_PROVIDER=local
    LOCAL_MODEL_PATH=finetune/output/lira-agent
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lira.core.config import settings  # noqa: E402

# ── Configuration ──────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
BASE_MODEL = "google/functiongemma-270m-it"
OUTPUT_DIR = BASE_DIR / "output" / "lira-agent"
TOOLS_PATH = BASE_DIR / "tools_schema.json"
DATASET_PATH = BASE_DIR / "dataset.json"
EXAMPLES_PATH = BASE_DIR / "examples.yaml"

from lira.core.fg_agent import _SYSTEM_PROMPT as SYSTEM_PROMPT  # noqa: E402

# Hyperparameters from the official Google FunctionGemma finetuning guide
EPOCHS = 8
BATCH_SIZE = 1              # 1 sample per step to fit 3090 24GB with 8k-token sequences
GRAD_ACCUM_STEPS = 4        # effective batch size = BATCH_SIZE * GRAD_ACCUM_STEPS = 4
LEARNING_RATE = 5e-5
LR_SCHEDULER = "constant"
MAX_SEQ_LEN = 6144          # ~5600 tokens per sample; 6144 leaves headroom, avoids 8192 OOM
EVAL_RATIO = 0.1
SEED = 42


# ── Step 1: Extract tool schemas ───────────────────────────────────────────────


def step_extract_tools() -> list[dict[str, Any]]:
    print("\n[1/5] Extracting MCP tool schemas from LIRA server...")
    from lira.db.session import init_database
    from lira.mcp.server import mcp, register_components

    init_database()
    register_components()

    schemas: list[dict[str, Any]] = []
    for tool in mcp._local_provider._components.values():
        if not hasattr(tool, "parameters"):
            continue

        raw_params = tool.parameters or {}
        properties = raw_params.get("properties", {}) if isinstance(raw_params, dict) else {}
        required = raw_params.get("required", []) if isinstance(raw_params, dict) else []

        clean_props: dict[str, Any] = {}
        for name, prop in properties.items():
            if not isinstance(prop, dict):
                continue
            clean: dict[str, Any] = {}
            for key in ("type", "description", "enum", "default"):
                if key in prop:
                    clean[key] = prop[key]
            if "anyOf" in prop:
                for variant in prop["anyOf"]:
                    if isinstance(variant, dict) and variant.get("type") != "null":
                        clean["type"] = variant.get("type", "string")
                        break
            clean_props[name] = clean

        schemas.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": {"type": "object", "properties": clean_props, "required": required},
            },
        })

    TOOLS_PATH.write_text(json.dumps(schemas, indent=2))
    print(f"  Extracted {len(schemas)} tools")
    for s in schemas:
        print(f"    - {s['function']['name']}")
    return schemas


# ── Step 2: Build dataset ──────────────────────────────────────────────────────


def step_build_dataset(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    print(f"\n[2/5] Building dataset (augmenting with {settings.llm_model} via ollama)...")

    import yaml

    raw_examples: list[dict[str, Any]] = yaml.safe_load(EXAMPLES_PATH.read_text())
    tool_names = {t["function"]["name"] for t in tools}

    for idx, ex in enumerate(raw_examples, start=1):
        for call in ex.get("calls", []):
            if call.get("name") not in tool_names:
                raise ValueError(f"Example #{idx} references unknown tool '{call.get('name')}'")

    print(f"  Loaded {len(raw_examples)} seed examples")

    from finetune.ollama_augment import augment_examples_with_ollama

    augmented = augment_examples_with_ollama(
        raw_examples,
        tools,
        model=settings.llm_model,
        host=settings.ollama_base_url,
        paraphrase_variants=8,   # rephrases per seed example (was 3)
        synthetic_per_tool=6,    # generated examples per uncovered tool (was 3)
    )

    rng = random.Random(SEED)
    rng.shuffle(augmented)
    print(f"  After augmentation: {len(augmented)} examples")

    dataset: list[dict[str, Any]] = []
    for ex in augmented:
        tool_calls = [
            {"type": "function", "function": {"name": c["name"], "arguments": c.get("arguments", {})}}
            for c in ex["calls"]
        ]
        messages = [
            {"role": "developer", "content": SYSTEM_PROMPT},
            {"role": "user", "content": ex["query"]},
            {"role": "assistant", "tool_calls": tool_calls},
        ]
        dataset.append({"messages": messages, "tools": tools})

    DATASET_PATH.write_text(json.dumps(dataset, indent=2))
    print(f"  Dataset saved ({len(dataset)} examples)")

    used = {c["name"] for ex in augmented for c in ex["calls"]}
    unused = tool_names - used
    if unused:
        print(f"  WARNING: {len(unused)} tools with no examples: {sorted(unused)}")

    return dataset


# ── Step 3: Unload Ollama from VRAM ───────────────────────────────────────────


def step_unload_ollama() -> None:
    print(f"\n[3/5] Unloading '{settings.llm_model}' from VRAM...")
    import httpx

    try:
        httpx.post(
            f"{settings.ollama_base_url}/api/generate",
            json={"model": settings.llm_model, "keep_alive": 0},
            timeout=15.0,
        ).raise_for_status()
        print("  Ollama model unloaded.")
    except Exception as e:
        print(f"  Warning: could not unload ({e}). Continuing.")


# ── Step 4: Train ──────────────────────────────────────────────────────────────


def step_train(dataset: list[dict[str, Any]]) -> None:
    import os

    # Reduce CUDA allocator fragmentation — helps when sequences vary in length
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

    print(f"\n[4/5] Training FunctionGemma on {len(dataset)} examples...")

    try:
        import torch
        from datasets import Dataset
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from trl import SFTConfig, SFTTrainer
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing training dependencies. Run:\n"
            "  uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124\n"
            "  uv pip install -r finetune/requirements.txt"
        ) from exc

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU not found. Training requires an NVIDIA GPU.")

    print(f"  GPU: {torch.cuda.get_device_name(0)}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load model as recommended in the official Google guide:
    # - dtype="auto" (no forced quantization)
    # - No LoRA, no 4-bit: full fine-tuning
    # attn_implementation: "sdpa" uses PyTorch's memory-efficient scaled dot-product
    # attention (Flash Attention when available on Ampere+ GPUs). The guide recommends
    # "eager" but that causes OOM at 6144-token sequences on a 3090. If sdpa causes
    # correctness issues, fall back to "eager" and reduce MAX_SEQ_LEN further.
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        dtype="auto",
        device_map="auto",
        attn_implementation="sdpa",
    )
    # Gradient checkpointing recomputes activations on the backward pass instead of
    # storing them, halving activation memory at the cost of ~33% extra compute.
    # use_cache must be False otherwise the KV cache conflicts with checkpointing.
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})

    # Tokenize and build samples with completion-only labels.
    # Tokens belonging to the prompt (everything before <start_of_turn>model\n)
    # are masked to -100 so the loss is only computed on the model's tool-call output.
    # This prevents the model from learning to echo system prompt / tool declarations.
    response_template = "<start_of_turn>model\n"
    response_template_ids = tokenizer.encode(response_template, add_special_tokens=False)
    rt_len = len(response_template_ids)

    tokenized_samples: list[dict[str, list[int]]] = []
    skipped = 0
    for idx, entry in enumerate(dataset, start=1):
        text = tokenizer.apply_chat_template(
            entry["messages"],
            tools=entry["tools"],
            tokenize=False,
            add_generation_prompt=False,
        )
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Empty sample at entry #{idx}")

        enc = tokenizer(
            text,
            truncation=True,
            max_length=MAX_SEQ_LEN,
            return_tensors=None,
        )
        input_ids: list[int] = enc["input_ids"]
        labels: list[int] = list(input_ids)

        # Find the last occurrence of the response template token sequence
        # and mask everything before it.
        found = False
        for i in range(len(input_ids) - rt_len, -1, -1):
            if input_ids[i : i + rt_len] == response_template_ids:
                for j in range(i + rt_len):
                    labels[j] = -100
                found = True
                break

        if not found:
            # Response template not in (possibly truncated) sample — skip it,
            # as training on it with full labels would teach prompt-echoing.
            skipped += 1
            continue

        tokenized_samples.append({"input_ids": input_ids, "labels": labels})

    if skipped:
        print(f"  WARNING: {skipped} samples skipped (response template not found, likely truncated)")
    print(f"  Usable samples after masking: {len(tokenized_samples)}")
    if not tokenized_samples:
        raise RuntimeError("No usable training samples — increase MAX_SEQ_LEN or reduce tool count.")

    hf_dataset = Dataset.from_list(tokenized_samples)
    split = hf_dataset.train_test_split(test_size=EVAL_RATIO, seed=SEED) if len(hf_dataset) > 1 else None
    train_ds = split["train"] if split else hf_dataset
    eval_ds = split["test"] if split else None

    print(f"  Train: {len(train_ds)}, Eval: {len(eval_ds) if eval_ds else 0}")

    from transformers import DataCollatorForSeq2Seq

    data_collator = DataCollatorForSeq2Seq(tokenizer=tokenizer, model=model, padding=True, label_pad_token_id=-100)

    # Training args from the official Google FunctionGemma guide
    use_bf16 = torch.cuda.is_bf16_supported()
    training_args = SFTConfig(
        output_dir=str(OUTPUT_DIR),
        dataset_text_field=None,  # we pass pre-tokenized data
        max_length=MAX_SEQ_LEN,
        packing=False,
        num_train_epochs=EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        per_device_eval_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM_STEPS,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        optim="adamw_torch_fused",
        learning_rate=LEARNING_RATE,
        lr_scheduler_type=LR_SCHEDULER,
        bf16=use_bf16,
        fp16=not use_bf16,
        logging_steps=1,
        eval_strategy="epoch" if eval_ds is not None else "no",
        save_strategy="epoch",
        save_total_limit=2,
        report_to="none",
        seed=SEED,
    )

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        processing_class=tokenizer,
        data_collator=data_collator,
    )

    trainer.train()
    trainer.save_model(str(OUTPUT_DIR))
    tokenizer.save_pretrained(str(OUTPUT_DIR))

    metrics = trainer.state.log_history
    (OUTPUT_DIR / "train_metrics.json").write_text(json.dumps(metrics, indent=2))
    print(f"  Model saved to {OUTPUT_DIR}")


# ── Step 5: Usage instructions ─────────────────────────────────────────────────


def step_done() -> None:
    print(f"""
[5/5] Done!

To use the finetuned model with LIRA, add to your .env:

    LLM_PROVIDER=local
    LOCAL_MODEL_PATH={OUTPUT_DIR}

LIRA will load the model directly via transformers (no Ollama needed).
""")


# ── Entrypoint ─────────────────────────────────────────────────────────────────


def main() -> None:
    print("=== LIRA FunctionGemma Finetuning ===")
    print(f"Base model : {BASE_MODEL}")
    print(f"Output dir : {OUTPUT_DIR}")
    print(f"Augmenting with: {settings.llm_model} @ {settings.ollama_base_url}")

    tools = step_extract_tools()
    dataset = step_build_dataset(tools)
    step_unload_ollama()
    step_train(dataset)
    step_done()


if __name__ == "__main__":
    main()
