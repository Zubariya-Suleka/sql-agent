"""The agent loop: tool calls until submit_answer, at most `max_steps` model calls.

Every step is recorded in a JSONL trace (runs/<run_id>.jsonl): the model's tool calls,
what each tool returned, token usage and the final answer. Week 5's failure analysis reads
these files, so they hold everything needed to see why an answer went wrong.
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from sql_agent.gateway_client import ChatResponse, GatewayError
from sql_agent.guard import SqlRejected, check_sql
from sql_agent.tools import TOOL_DEFINITIONS, ToolBox

# Stable text first and nothing per-request in it: Groq's prompt cache reuses the longest
# identical prefix, so every question shares this part.
SYSTEM_PROMPT = """\
You answer questions about Olist, a Brazilian e-commerce marketplace (orders from \
2016-09 to 2018-10), by querying its PostgreSQL database. Amounts are in BRL.

Rules:
1. Always call describe_table for every table you use before writing SQL that uses it.
2. Base the answer only on rows returned by run_sql. Never invent numbers.
3. If the question is ambiguous (for example "best" without saying by what), submit \
status "needs_clarification" and say what is unclear.
4. If the data cannot answer it (for example costs or profit, which are not in the data), \
submit status "cannot_answer" and say what is missing.
5. Otherwise submit status "answered" with the SQL that produced the answer, a short \
answer, and a plain-words explanation of how the SQL answers the question.
6. Finish by calling submit_answer exactly once."""

_NUDGE = "Use the tools. When you have the answer, call submit_answer."
_UNPARSEABLE = (
    "Your last reply could not be parsed as a tool call. Reply with exactly one tool call "
    "whose arguments are valid JSON."
)

Status = Literal["answered", "cannot_answer", "needs_clarification"]


class FinalAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Status
    sql: str
    answer: str
    explanation: str


class ChatClient(Protocol):
    model: str

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *, trace_id: str
    ) -> ChatResponse: ...


@dataclass
class Usage:
    """Tokens actually sent to the provider: steps the gateway answered from its own
    cache cost nothing, so they are only counted in `gateway_cache_hits`."""

    prompt: int = 0
    completion: int = 0
    cached: int = 0  # prompt tokens served from Groq's prompt cache
    gateway_cache_hits: int = 0

    def add(self, response: ChatResponse) -> None:
        if response.cache == "HIT":
            self.gateway_cache_hits += 1
            return
        usage = response.usage
        self.prompt += usage.get("prompt_tokens") or 0
        self.completion += usage.get("completion_tokens") or 0
        self.cached += (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0


@dataclass
class AgentResult:
    run_id: str
    question: str
    model: str
    status: str  # one of Status, or "error"
    final: FinalAnswer | None
    steps: int
    usage: Usage
    seconds: float
    trace_path: Path
    error: str | None = None
    tool_calls: list[str] = field(default_factory=list)


class Trace:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._file = path.open("w", encoding="utf-8")

    def event(self, kind: str, **data: Any) -> None:
        record = {"ts": datetime.now(UTC).isoformat(timespec="milliseconds"), "type": kind}
        self._file.write(json.dumps(record | data, default=str, ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def new_run_id() -> str:
    return f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"


def validate_final(raw_arguments: str | None) -> FinalAnswer | str:
    """The FinalAnswer, or an error message for the model to fix."""
    try:
        final = FinalAnswer.model_validate_json(raw_arguments or "{}")
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(map(str, e['loc'])) or 'arguments'}: {e['msg']}" for e in exc.errors()
        )
        return f"ERROR: invalid submit_answer arguments ({problems}). Call submit_answer again."
    if final.status == "answered":
        if not final.sql.strip():
            return "ERROR: status answered needs the SQL that produced the answer."
        try:
            check_sql(final.sql)
        except SqlRejected as exc:
            return f"ERROR: the submitted sql is not a valid query: {exc}"
    return final


class Agent:
    def __init__(
        self,
        client: ChatClient,
        tools: ToolBox,
        *,
        max_steps: int = 8,
        runs_dir: Path = Path("runs"),
    ) -> None:
        self._client = client
        self._tools = tools
        self._max_steps = max_steps
        self._runs_dir = runs_dir

    def ask(self, question: str, *, run_id: str | None = None) -> AgentResult:
        run_id = run_id or new_run_id()
        trace = Trace(self._runs_dir / f"{run_id}.jsonl")
        started = time.perf_counter()
        usage = Usage()
        tool_calls: list[str] = []
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        trace.event("start", run_id=run_id, question=question, model=self._client.model)

        def finish(status: str, final: FinalAnswer | None, steps: int, error: str | None):
            result = AgentResult(
                run_id=run_id,
                question=question,
                model=self._client.model,
                status=status,
                final=final,
                steps=steps,
                usage=usage,
                seconds=time.perf_counter() - started,
                trace_path=trace.path,
                error=error,
                tool_calls=tool_calls,
            )
            trace.event(
                "end",
                status=status,
                steps=steps,
                error=error,
                usage=vars(usage),
                seconds=round(result.seconds, 2),
                final=final.model_dump() if final else None,
            )
            trace.close()
            return result

        for step in range(1, self._max_steps + 1):
            try:
                response = self._client.chat(messages, TOOL_DEFINITIONS, trace_id=run_id)
            except GatewayError as exc:
                if not exc.is_unparseable_output:
                    return finish("error", None, step, str(exc))
                # A malformed tool call is a model mistake: record what it wrote, say so,
                # and let it try again (the new message also changes the prompt).
                trace.event(
                    "llm_error",
                    step=step,
                    error=str(exc),
                    failed_generation=exc.details.get("failed_generation"),
                )
                messages.append({"role": "user", "content": _UNPARSEABLE})
                continue
            usage.add(response)
            message = response.message
            calls = message.get("tool_calls") or []
            trace.event(
                "llm",
                step=step,
                content=message.get("content"),
                reasoning=message.get("reasoning"),
                tool_calls=calls,
                finish_reason=response.finish_reason,
                usage=response.usage,
                gateway_cache=response.cache,
            )
            # The reasoning text is kept in the trace but not sent back: Groq's API docs
            # don't say whether past reasoning is accepted as input.
            messages.append(
                {"role": "assistant", "content": message.get("content") or ""}
                | ({"tool_calls": calls} if calls else {})
            )
            if not calls:
                messages.append({"role": "user", "content": _NUDGE})
                continue

            for call in calls:
                name = call["function"]["name"]
                arguments = call["function"].get("arguments")
                tool_calls.append(name)
                if name == "submit_answer":
                    outcome = validate_final(arguments)
                    if isinstance(outcome, FinalAnswer):
                        trace.event("tool", step=step, name=name, arguments=arguments)
                        return finish(outcome.status, outcome, step, None)
                    text, details, error = outcome, {}, True
                else:
                    result = self._tools.call(name, arguments)
                    text, details, error = result.text, result.details, result.error
                trace.event(
                    "tool",
                    step=step,
                    name=name,
                    arguments=arguments,
                    result=text[:2000],
                    details=details,
                    error=error,
                )
                messages.append(
                    {"role": "tool", "tool_call_id": call["id"], "name": name, "content": text}
                )

        return finish(
            "error", None, self._max_steps, f"no answer after {self._max_steps} model calls"
        )
