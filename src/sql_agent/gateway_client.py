"""Calls models through llm-gateway's OpenAI-compatible endpoint, never Groq directly.

The gateway does rate limiting, retries, caching and metrics, so this client does none of
them: it sends one request and reports what came back. X-Trace-Id ties the gateway's
metrics rows to this agent's trace file.
"""

from dataclasses import dataclass
from typing import Any

import httpx


class GatewayError(Exception):
    pass


@dataclass
class ChatResponse:
    message: dict[str, Any]
    finish_reason: str | None
    usage: dict[str, Any]
    cache: str | None  # the gateway's X-Cache: HIT, MISS or BYPASS


class GatewayClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        project: str = "sql-agent",
        timeout_s: float = 300.0,
        max_completion_tokens: int = 2048,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self._base_url = base_url
        self._max_completion_tokens = max_completion_tokens
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout_s,
            headers={"X-Project": project},
            transport=transport,
        )

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *, trace_id: str
    ) -> ChatResponse:
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            # Every step must be a tool call; the answer itself is the submit_answer tool.
            "tool_choice": "required",
            # Deterministic as far as the model allows, and cacheable by the gateway.
            "temperature": 0,
            "max_completion_tokens": self._max_completion_tokens,
        }
        try:
            response = self._client.post(
                "chat/completions", json=payload, headers={"X-Trace-Id": trace_id}
            )
        except httpx.HTTPError as exc:
            raise GatewayError(f"cannot reach llm-gateway at {self._base_url}: {exc!r}") from exc
        if response.status_code != 200:
            try:
                message = response.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                message = response.text[:300]
            raise GatewayError(f"gateway {response.status_code}: {message}")
        body = response.json()
        choice = body["choices"][0]
        return ChatResponse(
            message=choice["message"],
            finish_reason=choice.get("finish_reason"),
            usage=body.get("usage") or {},
            cache=response.headers.get("x-cache"),
        )

    def close(self) -> None:
        self._client.close()
