import json
import re

import anthropic

from groundskeeper.env import get_settings


def complete_json(*, model: str, system: str, user: str, max_tokens: int = 4096) -> tuple[str, str]:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required")
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    res = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in res.content if getattr(b, "type", None) == "text")
    return text, model


def extract_json(text: str) -> object:
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    raw = (fenced.group(1) if fenced else text).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("No JSON object in model response")
    return json.loads(raw[start : end + 1])
