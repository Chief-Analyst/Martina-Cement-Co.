"""A small client for Groq's OpenAI-compatible chat API.

Returns None when no key is set or the call fails, so every caller has a
demo fallback and the dashboard never breaks because the AI is offline.
"""
from __future__ import annotations

import logging
import re

import requests

from ..config import SETTINGS

log = logging.getLogger("martina.ai")
URL = "https://api.groq.com/openai/v1/chat/completions"


def enabled() -> bool:
    return bool(SETTINGS.groq_api_key)


def chat(system: str, user: str, max_tokens=900, temperature=0.2, history=None):
    if not enabled():
        return None
    messages = [{"role": "system", "content": system}]
    for h in history or []:
        messages.append({"role": h["role"], "content": h["content"][:4000]})
    messages.append({"role": "user", "content": user})
    try:
        r = requests.post(URL, timeout=45, headers={"Authorization": f"Bearer {SETTINGS.groq_api_key}"},
                          json={"model": SETTINGS.groq_model, "messages": messages,
                                "max_tokens": max_tokens, "temperature": temperature})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:                                   # noqa: BLE001
        # never log the key or the full URL with query strings
        log.warning("Groq call failed: %s", re.sub(r"gsk_\w+", "gsk_***", str(e))[:200])
        return None
