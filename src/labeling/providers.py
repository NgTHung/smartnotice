"""Call Gemini or Featherless for one prepared notice at a time."""

import os
import re
from pathlib import Path

import httpx
from smartnotice.labeling.llm import (
    MAX_OUTPUT_TOKENS,
    TEMPERATURE,
    DraftResponse,
    build_prompt,
    require_provider_approval,
)
from smartnotice.schemas import Notice, Provider

ENV_NAMES = ("GEMINI_MODEL", "GEMINI_KEY", "FEATHERLESS_MODEL", "FEATHERLESS_KEY")


def load_local_env(path: Path = Path(".env")) -> None:
    """Load only labeling configuration from a local UTF-8 .env file.

    Existing process environment values win. This intentionally supports simple
    KEY=value lines only; it does not evaluate shell expansions or commands.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key not in ENV_NAMES or key in os.environ:
            continue
        value = value.strip()
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[0] != value[-1]:
                raise ValueError(f"Unclosed quoted value for {key} in .env")
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        os.environ[key] = value


def configured_model(provider: Provider) -> str:
    """Return the configured model ID without exposing any credential."""
    name = "GEMINI_MODEL" if provider == "gemini" else "FEATHERLESS_MODEL"
    model = os.environ.get(name, "").strip()
    if not model:
        raise ValueError(f"Set {name} in the environment or .env")
    return model


def generate_draft(
    notice: Notice,
    *,
    provider: Provider,
    model: str,
    approvals: list[dict] | None = None,
    client: httpx.Client | None = None,
) -> str:
    """Return model JSON text; raise on missing keys or invalid provider responses.

    Real notices require matching privacy and provider approval. Responses with
    missing content, refusal, or truncated generation fail without body logging.
    """
    if provider not in ("gemini", "featherless"):
        raise ValueError(f"Unsupported provider: {provider}")
    require_provider_approval(notice, provider, approvals or [])
    key_name = "GEMINI_KEY" if provider == "gemini" else "FEATHERLESS_KEY"
    key = os.environ.get(key_name, "").strip()
    if not key:
        raise ValueError(f"Set {key_name} in the environment or .env")
    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=90)
    try:
        if provider == "gemini":
            model = model.removeprefix("models/")
            if not re.fullmatch(r"[A-Za-z0-9._-]+", model):
                raise ValueError("Invalid Gemini model ID")
            response = client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key},
                json={
                    "contents": [{"parts": [{"text": build_prompt(notice)}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "responseJsonSchema": DraftResponse.model_json_schema(),
                        "temperature": TEMPERATURE,
                        "maxOutputTokens": MAX_OUTPUT_TOKENS,
                    },
                },
            )
        else:
            response = client.post(
                "https://api.featherless.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "Return only valid JSON. No markdown."},
                        {"role": "user", "content": build_prompt(notice)},
                    ],
                    "temperature": TEMPERATURE,
                    "max_tokens": MAX_OUTPUT_TOKENS,
                },
            )
        response.raise_for_status()
        payload = response.json()
        if provider == "gemini":
            candidate = payload["candidates"][0]
            if candidate.get("finishReason") != "STOP":
                raise ValueError(f"{provider} generation did not finish normally")
            content = "".join(
                part.get("text", "")
                for part in candidate["content"]["parts"]
                if not part.get("thought")
            )
        else:
            choice = payload["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError(f"{provider} generation did not finish normally")
            content = choice["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Provider returned empty text")
        return content
    except httpx.HTTPStatusError as exc:
        raise ValueError(
            f"{provider} HTTP {exc.response.status_code} for {notice.doc_id}"
        ) from None
    except httpx.RequestError:
        raise ValueError(f"{provider} connection failed for document {notice.doc_id}") from None
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError(
            f"{provider} returned incomplete or invalid content for {notice.doc_id}"
        ) from None
    finally:
        if own_client:
            client.close()
