"""A chat model behind an OpenAI-compatible endpoint (POST {base}/chat/completions), with plain aiohttp.

Zhipu (glm-4-flash, GLM-4.7-Flash), Groq and most others speak this protocol, so WXBOT_LLM_BASE, _KEY and
_MODEL pick the provider and nothing else knows which it is. Only free models are used.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

import aiohttp

from . import config


class LLMError(Exception):
    pass


@dataclass
class Reply:
    text: str
    prompt_tokens: int
    completion_tokens: int
    seconds: float


# Reasoning models (qwen3, GLM-4.7) may put their thinking in front of the answer.
_THINK = re.compile(r"<think>.*?</think>", re.S)


def extra_fields() -> dict:
    try:
        extra = json.loads(config.LLM_EXTRA) if config.LLM_EXTRA else {}
    except ValueError:
        raise LLMError("WXBOT_LLM_EXTRA is not valid JSON")
    return extra if isinstance(extra, dict) else {}


async def chat(http: aiohttp.ClientSession, messages: list[dict], *, timeout: float, model: str | None = None,
               max_tokens: int = 300, base: str | None = None, key: str | None = None,
               extra: dict | None = None) -> Reply:
    """base, key and extra default to the WXBOT_LLM_* settings (eval's judge passes its own)."""
    key = key if key is not None else config.LLM_KEY
    if not key:
        raise LLMError("WXBOT_LLM_KEY is not set")
    body = {"model": model or config.LLM_MODEL, "messages": messages, "temperature": 0, "max_tokens": max_tokens,
            **(extra_fields() if extra is None else extra)}
    start = time.monotonic()
    try:
        async with http.post(f"{(base or config.LLM_BASE).rstrip('/')}/chat/completions", json=body,
                             headers={"Authorization": f"Bearer {key}"},
                             timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            if resp.status != 200:
                # The body says why (bad key, rate limit, content filter); never the key itself.
                raise LLMError(f"HTTP {resp.status}: {(await resp.text())[:200]}")
            data = await resp.json(content_type=None)
    except TimeoutError:
        raise
    except aiohttp.ClientError as exc:
        raise LLMError(f"{type(exc).__name__}: {exc}") from exc
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"unexpected reply: {str(data)[:200]}")
    usage = data.get("usage") or {}
    return Reply(_THINK.sub("", text).strip(), int(usage.get("prompt_tokens") or 0),
                 int(usage.get("completion_tokens") or 0), time.monotonic() - start)
