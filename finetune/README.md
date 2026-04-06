# FunctionGemma Finetuning

Fine-tunes [`google/functiongemma-270m-it`](https://huggingface.co/google/functiongemma-270m-it)
on LIRA's MCP tool registry, following the
[official Google finetuning guide](https://ai.google.dev/gemma/docs/functiongemma/finetuning-with-functiongemma).

## Files

| File | Purpose |
|---|---|
| `run.py` | Full pipeline: extract tools → augment → train |
| `ollama_augment.py` | Ollama-based data augmentation helpers |
| `examples.yaml` | Seed tool-calling examples (add one per new tool) |
| `requirements.txt` | Training dependencies |

## Quick start

### 1) Install GPU dependencies

```bash
uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
uv pip install -r finetune/requirements.txt
```

### 2) Train

```bash
uv run python -m finetune.run
```

The script reads `LLM_MODEL` and `OLLAMA_BASE_URL` from `.env` to augment the seed
examples with Ollama, unloads the Ollama model from VRAM, then runs full fine-tuning
on your NVIDIA GPU. The model is saved to `finetune/output/lira-agent/`.

### 3) Use with LIRA

Add to your `.env`:

```
LLM_PROVIDER=local
LOCAL_MODEL_PATH=finetune/output/lira-agent
```

No conversion needed — LIRA loads the HF model directly via transformers.

## Training approach

Follows the official Google guide exactly:
- Full fine-tuning (no LoRA, no quantization during training)
- `attn_implementation="eager"` required for Gemma 3
- `lr=5e-5`, `epochs=8`, `batch=4`, `scheduler=constant`, `max_length=512`
- Inference settings: `top_k=64`, `top_p=0.95`, `temperature=1.0`

## Updating the dataset

When you add new MCP tools, add at least one example to `examples.yaml` then re-run:

```bash
uv run python -m finetune.run
```
