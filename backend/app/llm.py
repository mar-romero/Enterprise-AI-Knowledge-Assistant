"""Bedrock Converse wrapper.

Offline-testable: unit tests inject a fake ``LLMClient`` and require no
boto3 installation and no network access. No identity material is handled
in this unit; the underlying runtime client configuration is an
integration-stage concern documented in ``backend/README.md``.
"""

import os
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMResult:
    """Normalized result of a Bedrock Converse call."""

    text: str
    model_id: str
    usage: dict[str, int]


class LLMClient(Protocol):
    """Duck-typed contract mirroring boto3 bedrock-runtime ``converse``.

    The response shape follows the boto3 bedrock-runtime Converse API:

    ``{"output": {"message": {"content": [{"text": ...}, ...]}},
      "usage": {"inputTokens": int, "outputTokens": int, "totalTokens": int},
      "stopReason": ...}``
    """

    def converse(self, model_id: str, messages: list) -> dict:
        ...


@dataclass(frozen=True)
class LLMSettings:
    """Environment-backed LLM settings (no identity material stored)."""

    model_id: str
    region: str

    @classmethod
    def from_env(cls) -> "LLMSettings":
        """Read settings from the environment.

        ``model_id`` defaults to ``""``: an unset value means the caller
        must set ``BEDROCK_MODEL_ID`` before real use.
        """
        return cls(
            model_id=os.environ.get("BEDROCK_MODEL_ID", ""),
            region=os.environ.get("AWS_REGION", "us-east-1"),
        )


def integration_enabled() -> bool:
    """Whether the opt-in AWS integration test is enabled (default off)."""
    return os.environ.get("AWS_INTEGRATION") == "1"


def build_default_client():
    """Create the default boto3 bedrock-runtime client (lazy import).

    boto3 is imported only inside this function so that the module (and its
    unit tests) work in a boto3-free environment. See the "LLM wrapper"
    section of ``backend/README.md`` for the integration-stage setup.
    """
    try:
        import boto3
    except ImportError as exc:
        raise ImportError(
            "boto3 is required for real Bedrock integration; see the 'LLM "
            "wrapper (backend/app/llm.py)' section of backend/README.md"
        ) from exc
    settings = LLMSettings.from_env()
    return boto3.client("bedrock-runtime", region_name=settings.region)


class BedrockLLM:
    """Thin wrapper over a bedrock-runtime ``converse`` client."""

    def __init__(self, client: LLMClient, settings: LLMSettings | None = None):
        self._client = client
        self._settings = settings or LLMSettings.from_env()

    def answer(self, prompt: str) -> LLMResult:
        """Send ``prompt`` as a single user message and normalize the response."""
        messages = [{"role": "user", "content": [{"text": prompt}]}]
        response = self._client.converse(
            model_id=self._settings.model_id, messages=messages
        )
        return self._parse_converse_response(response, self._settings.model_id)

    @staticmethod
    def _parse_converse_response(response: dict, model_id: str) -> LLMResult:
        """Extract text parts and normalize usage from a Converse response."""
        content = response.get("output", {}).get("message", {}).get("content", [])
        text_parts = [part["text"] for part in content if "text" in part]
        if not text_parts:
            raise ValueError("Bedrock converse response has no text content")

        usage_map = {
            "inputTokens": "input_tokens",
            "outputTokens": "output_tokens",
            "totalTokens": "total_tokens",
        }
        usage_raw = response.get("usage") or {}
        usage: dict[str, int] = {}
        for camel, snake in usage_map.items():
            value = usage_raw.get(camel)
            if value is not None:
                usage[snake] = value

        return LLMResult(text="".join(text_parts), model_id=model_id, usage=usage)
