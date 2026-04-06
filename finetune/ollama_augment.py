import json
import httpx
from typing import Any


def generate_ollama_examples_for_tool(
    tool: dict[str, Any], model: str, host: str, count: int = 3
) -> list[dict[str, Any]]:
    prompt = f"""
You are an intelligent data generator for tool-calling models.
Generate {count} realistic, varied user requests and the exact corresponding JSON arguments to call this tool.
The output MUST be a JSON object with a single key "examples" containing a list of objects.
Each object must have a "query" (string) and "arguments" (object) containing the correct tool parameters.
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
) -> list[dict[str, Any]]:
    print(f"  Augmenting with Ollama ({model} @ {host})...")
    augmented = list(examples)
    total = len(examples)

    print(f"  Paraphrasing {total} seed examples (2 variants each)...")
    for i, ex in enumerate(examples, start=1):
        print(f"    [{i}/{total}] {ex['query'][:70]}", end="", flush=True)
        prompt = f"""
Rephrase the following user query in 2 different realistic ways.
The output MUST be a JSON object with a single key "phrases" containing a list of strings.

Original Query: "{ex['query']}"

Example format:
{{
  "phrases": [
    "I need to query X",
    "Show me X"
  ]
}}
"""
        req = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.8},
        }
        try:
            resp = httpx.post(f"{host}/api/chat", json=req, timeout=30.0)
            data = json.loads(resp.json()["message"]["content"])
            phrases = data.get("phrases", [])
            for p in phrases:
                augmented.append(
                    {
                        **ex,
                        "query": p,
                        "tags": list(set(ex.get("tags", []) + ["ollama_generated"])),
                    }
                )
            print(f" → +{len(phrases)} variants")
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
            print(f"\n  Generating synthetic examples for {len(unused)} uncovered tools...")
            for j, tool_name in enumerate(sorted(unused), start=1):
                print(f"    [{j}/{len(unused)}] {tool_name}...", end="", flush=True)
                new_exs = generate_ollama_examples_for_tool(
                    all_tools[tool_name], model, host, count=3
                )
                augmented.extend(new_exs)
                print(f" → +{len(new_exs)} examples")

    return augmented
