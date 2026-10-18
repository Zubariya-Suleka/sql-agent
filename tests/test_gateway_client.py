import json

import httpx
import pytest

from sql_agent.gateway_client import GatewayClient, GatewayError


def client_with(handler) -> GatewayClient:
    return GatewayClient(
        "http://gateway.test/v1", "groq/openai/gpt-oss-20b", transport=httpx.MockTransport(handler)
    )


def test_sends_an_openai_request_with_project_and_trace_headers():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"X-Cache": "MISS"},
            json={
                "choices": [{"message": {"role": "assistant"}, "finish_reason": "tool_calls"}],
                "usage": {"prompt_tokens": 5},
            },
        )

    response = client_with(handler).chat(
        [{"role": "user", "content": "hi"}], [{"type": "function"}], trace_id="run-1"
    )

    assert seen["url"] == "http://gateway.test/v1/chat/completions"
    assert seen["headers"]["x-project"] == "sql-agent"
    assert seen["headers"]["x-trace-id"] == "run-1"
    body = seen["body"]
    assert body["model"] == "groq/openai/gpt-oss-20b"
    assert (body["tool_choice"], body["temperature"]) == ("required", 0)
    assert response.cache == "MISS"
    assert response.finish_reason == "tool_calls"
    assert response.usage == {"prompt_tokens": 5}


def test_error_responses_carry_the_gateway_message():
    def handler(request):
        return httpx.Response(429, json={"error": {"message": "daily tokens budget used up"}})

    with pytest.raises(GatewayError, match="429: daily tokens budget used up"):
        client_with(handler).chat([], [], trace_id="t")


def test_unreachable_gateway_says_where_it_looked():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(GatewayError, match="cannot reach llm-gateway at http://gateway.test/v1"):
        client_with(handler).chat([], [], trace_id="t")
