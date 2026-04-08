import json
import httpx
from typing import Any


def generate_ollama_examples_for_tool(
    tool: dict[str, Any], model: str, host: str, count: int = 3
) -> list[dict[str, Any]]:
    prompt = f"""You are a data generator for a personal finance AI tool-calling model.
Generate {count} realistic, highly diverse user requests and the exact corresponding JSON arguments to call this tool.
The output MUST be a JSON object with a single key "examples" containing a list of objects.
Each object must have a "query" (string) and "arguments" (object) containing the correct tool parameters.

CRITICAL: Every example must use COMPLETELY DIFFERENT concrete values (names, amounts, tickers, dates, merchants, etc.).
Do NOT repeat values between examples. Use realistic, varied data from different domains of personal finance.
Vary the phrasing style too: casual, formal, brief, verbose.
Only output valid JSON.

Tool Name: {tool['function']['name']}
Description: {tool['function']['description']}
Schema: {json.dumps(tool['function']['parameters'])}

Example format:
{{
  "examples": [
    {{"query": "Help me with X ...", "arguments": {{"param1": "foo", "param2": 123}}}},
    {{"query": "Another request", "arguments": {{"param1": "bar", "param2": 456}}}}
  ]
}}
"""
    req = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.7},
    }

    try:
        resp = httpx.post(f"{host}/api/chat", json=req, timeout=60.0)
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        data = json.loads(content)
        items = data.get("examples", [])

        results = []
        for item in items:
            results.append(
                {
                    "query": item["query"],
                    "calls": [
                        {
                            "name": tool["function"]["name"],
                            "arguments": item.get("arguments", {}),
                        }
                    ],
                    "tags": ["ollama_generated", "single"],
                }
            )
        return results
    except Exception as e:
        print(f"  [!] Error generating for {tool['function']['name']}: {e}")
        return []


def augment_examples_with_ollama(
    examples: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str,
    host: str,
    generate_missing: bool = True,
    paraphrase_variants: int = 8,
    synthetic_per_tool: int = 6,
) -> list[dict[str, Any]]:
    print(f"  Augmenting with Ollama ({model} @ {host})...")
    augmented = list(examples)
    total = len(examples)

    print(
        f"  Generating {total} seed example variants "
        f"({paraphrase_variants} each, with varied arguments)..."
    )
    for i, ex in enumerate(examples, start=1):
        print(f"    [{i}/{total}] {ex['query'][:70]}", end="", flush=True)

        # Build a description of the calls so the LLM knows which args to vary
        calls_desc = json.dumps(ex["calls"], indent=2)

        prompt = f"""You are a data augmentation assistant for a personal finance AI.
Given an example user query and its corresponding tool call(s), generate {paraphrase_variants} NEW and DIVERSE variants.

CRITICAL RULES:
- Each variant MUST have a completely different query AND different argument values.
- Vary ALL concrete values: names, amounts, tickers, dates, merchants, categories, descriptions, etc.
- Keep the same tool name(s) and argument keys — only change the VALUES.
- Use realistic, varied data: different stock tickers (TSLA, AMZN, VOO, VWCE, CSPX, etc.), different merchants (Carrefour, Amazon, IKEA, etc.), different amounts, different dates, different account names, etc.
- Do NOT repeat values from the original example or between variants.
- The query text must naturally match the argument values (if the query says "Tesla", the ticker should be "TSLA").

Original query: "{ex['query']}"
Original tool calls: {calls_desc}

Output MUST be a JSON object with key "variants" containing a list of objects, each with "query" (string) and "calls" (same structure as above).

Example format:
{{
  "variants": [
    {{
      "query": "I purchased 25 shares of AMZN at 178.30 on Degiro",
      "calls": [{{"name": "create_investment", "arguments": {{"date": "2026-03-15", "ticker": "AMZN", "units": 25.0, "price_per_unit": 178.30, "trade_type": "buy", "broker": "Degiro", "currency": "USD"}}}}]
    }}
  ]
}}
"""
        req = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.9},
        }
        try:
            resp = httpx.post(f"{host}/api/chat", json=req, timeout=60.0)
            data = json.loads(resp.json()["message"]["content"])
            variants = data.get("variants", [])
            added = 0
            for v in variants:
                if not isinstance(v, dict) or "query" not in v or "calls" not in v:
                    continue
                # Validate that calls have the expected structure
                valid = True
                for call in v["calls"]:
                    if not isinstance(call, dict) or "name" not in call:
                        valid = False
                        break
                if not valid:
                    continue
                augmented.append(
                    {
                        "query": v["query"],
                        "calls": v["calls"],
                        "tags": list(set(ex.get("tags", []) + ["ollama_generated"])),
                    }
                )
                added += 1
            print(f" → +{added} variants")
        except Exception as e:
            print(f" → skipped ({e})")

    if generate_missing:
        used_tools = set()
        for ex in augmented:
            for call in ex["calls"]:
                used_tools.add(call["name"])

        all_tools = {t["function"]["name"]: t for t in tools}
        unused = set(all_tools.keys()) - used_tools

        if unused:
            print(
                f"\n  Generating synthetic examples for {len(unused)} uncovered tools..."
            )
            for j, tool_name in enumerate(sorted(unused), start=1):
                print(f"    [{j}/{len(unused)}] {tool_name}...", end="", flush=True)
                new_exs = generate_ollama_examples_for_tool(
                    all_tools[tool_name], model, host, count=synthetic_per_tool
                )
                augmented.extend(new_exs)
                print(f" → +{len(new_exs)} examples")

    return augmented
