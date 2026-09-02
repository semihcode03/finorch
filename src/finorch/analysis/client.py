"""OpenAI istemcisi ve ortak JSON sohbet yardimcisi."""

from __future__ import annotations

import json
import logging

from tenacity import retry, stop_after_attempt, wait_exponential

from finorch.config import settings

logger = logging.getLogger(__name__)


def get_client():
    from openai import OpenAI

    return OpenAI(api_key=settings.openai_api_key)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
def chat_json(system_prompt: str, user_prompt: str, max_chars: int = 12000) -> dict:
    """LLM'e JSON modu ile cagri yapar ve parse edilmis sozluk doner."""
    client = get_client()
    resp = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt[:max_chars]},
        ],
    )
    return json.loads(resp.choices[0].message.content or "{}")


def is_enabled() -> bool:
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY tanimli degil; LLM cikarimi atlaniyor.")
        return False
    return True


def _to_float(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
