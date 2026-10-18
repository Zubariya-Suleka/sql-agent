"""The agent loop with a scripted model and fake tools: no gateway, no database."""

import json

from sql_agent.agent import SYSTEM_PROMPT, Agent
from sql_agent.gateway_client import ChatResponse, GatewayError
from sql_agent.tools import ToolResult


def tool_call(name, arguments, call_id="call_1"):
    return {
        "role": "assistant",
        "content": None,
        "reasoning": "thinking about it",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


def submit(status="answered", sql="SELECT count(*) FROM orders", answer="99441", why="counted"):
    return tool_call(
        "submit_answer", {"status": status, "sql": sql, "answer": answer, "explanation": why}
    )


class ScriptedModel:
    """Returns the scripted assistant messages in order; records what it was sent."""

    model = "fake/model"

    def __init__(self, *messages):
        self.messages = list(messages)
        self.requests = []

    def chat(self, messages, tools, *, trace_id):
        self.requests.append({"messages": [dict(m) for m in messages], "trace_id": trace_id})
        message = self.messages.pop(0)
        if isinstance(message, Exception):
            raise message
        usage = {
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 60},
        }
        return ChatResponse(message, "tool_calls", usage, "MISS")


class FakeTools:
    def __init__(self):
        self.calls = []

    def call(self, name, arguments):
        self.calls.append((name, json.loads(arguments)))
        return ToolResult(f"result of {name}")


def agent_for(model, tmp_path, max_steps=8):
    return Agent(model, FakeTools(), max_steps=max_steps, runs_dir=tmp_path)


def read_trace(result):
    return [json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()]


def test_happy_path_ends_with_a_validated_answer(tmp_path):
    model = ScriptedModel(
        tool_call("list_tables", {}),
        tool_call("describe_table", {"table": "orders"}),
        tool_call("run_sql", {"query": "SELECT count(*) FROM orders"}),
        submit(),
    )
    result = agent_for(model, tmp_path).ask("How many orders are there?")

    assert result.status == "answered"
    assert result.final.answer == "99441"
    assert result.steps == 4
    assert result.tool_calls == ["list_tables", "describe_table", "run_sql", "submit_answer"]
    assert (result.usage.prompt, result.usage.completion, result.usage.cached) == (400, 40, 240)

    first = model.requests[0]["messages"]
    assert first[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert first[1] == {"role": "user", "content": "How many orders are there?"}
    # Tool results are answered by tool_call_id, and past reasoning is not sent back.
    last = model.requests[-1]["messages"]
    assert last[-1]["role"] == "tool" and last[-1]["tool_call_id"] == "call_1"
    assert all("reasoning" not in m for m in last)
    assert {r["trace_id"] for r in model.requests} == {result.run_id}


def test_trace_records_every_step(tmp_path):
    model = ScriptedModel(tool_call("list_tables", {}), submit())
    result = agent_for(model, tmp_path).ask("q")

    events = read_trace(result)
    assert [e["type"] for e in events] == ["start", "llm", "tool", "llm", "tool", "end"]
    assert events[0]["question"] == "q"
    assert events[1]["reasoning"] == "thinking about it"  # kept for failure analysis
    assert events[2]["result"] == "result of list_tables"
    assert events[-1]["status"] == "answered"
    assert events[-1]["final"]["sql"] == "SELECT count(*) FROM orders"


def test_invalid_answer_goes_back_to_the_model(tmp_path):
    model = ScriptedModel(
        tool_call("submit_answer", {"status": "done", "sql": "", "answer": "x"}),
        submit(),
    )
    result = agent_for(model, tmp_path).ask("q")

    assert result.status == "answered"
    assert result.steps == 2
    feedback = model.requests[1]["messages"][-1]["content"]
    assert feedback.startswith("ERROR: invalid submit_answer arguments")
    assert "status" in feedback and "explanation" in feedback


def test_answered_needs_sql_that_passes_the_guard(tmp_path):
    model = ScriptedModel(
        submit(sql=""),
        submit(sql="DELETE FROM orders"),
        submit(),
    )
    result = agent_for(model, tmp_path).ask("q")

    assert result.steps == 3
    replies = [r["messages"][-1]["content"] for r in model.requests[1:]]
    assert "needs the SQL" in replies[0]
    assert "not a valid query" in replies[1]


def test_clarification_and_cannot_answer_need_no_sql(tmp_path):
    for status in ("needs_clarification", "cannot_answer"):
        model = ScriptedModel(submit(status=status, sql="", answer="by what measure?"))
        assert agent_for(model, tmp_path).ask("best seller?").status == status


def test_a_reply_without_tool_calls_gets_a_nudge(tmp_path):
    model = ScriptedModel({"role": "assistant", "content": "The answer is 42."}, submit())
    result = agent_for(model, tmp_path).ask("q")

    assert result.status == "answered"
    assert model.requests[1]["messages"][-1] == {
        "role": "user",
        "content": "Use the tools. When you have the answer, call submit_answer.",
    }


def test_stops_with_an_error_after_max_steps(tmp_path):
    model = ScriptedModel(*[tool_call("list_tables", {}) for _ in range(3)])
    result = agent_for(model, tmp_path, max_steps=3).ask("q")

    assert result.status == "error"
    assert result.final is None
    assert "no answer after 3 model calls" in result.error
    assert read_trace(result)[-1]["status"] == "error"


def test_gateway_failure_ends_the_run_with_its_message(tmp_path):
    model = ScriptedModel(GatewayError("gateway 429: daily tokens budget is used up"))
    result = agent_for(model, tmp_path).ask("q")

    assert result.status == "error"
    assert "daily tokens budget" in result.error
