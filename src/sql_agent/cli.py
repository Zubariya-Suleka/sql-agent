"""`sql-agent` command line.

    uv run sql-agent ask "Which 5 product categories had the most late deliveries in 2018?"

Needs the Olist Postgres (`just db up`) and llm-gateway running on GATEWAY_URL.
"""

import argparse
import json
import sys

from sql_agent.agent import Agent, AgentResult
from sql_agent.config import get_settings
from sql_agent.db import Database
from sql_agent.gateway_client import GatewayClient
from sql_agent.tools import ToolBox


def run_question(question: str, *, model: str | None = None, max_steps: int | None = None):
    settings = get_settings()
    db = Database(settings.database_url.get_secret_value())
    client = GatewayClient(
        settings.gateway_url,
        model or settings.agent_model,
        timeout_s=settings.gateway_timeout_s,
        max_completion_tokens=settings.max_completion_tokens,
    )
    agent = Agent(
        client,
        ToolBox(db),
        max_steps=max_steps or settings.max_steps,
        runs_dir=settings.runs_dir,
    )
    try:
        return agent.ask(question)
    finally:
        client.close()
        db.close()


def summary(result: AgentResult) -> str:
    u = result.usage
    return (
        f"{result.model} · {result.steps} steps · {result.seconds:.1f} s · tokens: "
        f"{u.prompt:,} prompt ({u.cached:,} cached) + {u.completion:,} completion"
    )


def _ask(args: argparse.Namespace) -> None:
    result = run_question(args.question, model=args.model, max_steps=args.max_steps)
    if args.json:
        print(
            json.dumps(
                {
                    "run_id": result.run_id,
                    "status": result.status,
                    "final": result.final.model_dump() if result.final else None,
                    "error": result.error,
                    "steps": result.steps,
                    "usage": vars(result.usage),
                    "seconds": round(result.seconds, 2),
                    "trace": str(result.trace_path),
                },
                indent=2,
            )
        )
    else:
        print(f"status:      {result.status}")
        if result.final:
            print(f"answer:      {result.final.answer}")
            if result.final.sql:
                print(f"sql:         {result.final.sql}")
            print(f"explanation: {result.final.explanation}")
        if result.error:
            print(f"error:       {result.error}")
        print(f"\n{summary(result)}\ntrace: {result.trace_path}")
    sys.exit(1 if result.status == "error" else 0)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="sql-agent")
    sub = parser.add_subparsers(dest="command", required=True)
    ask = sub.add_parser("ask", help="answer one question about the Olist data")
    ask.add_argument("question")
    ask.add_argument("--model", help="gateway model name, e.g. groq/qwen/qwen3.8-27b")
    ask.add_argument("--max-steps", type=int, help="model calls before giving up (default 8)")
    ask.add_argument("--json", action="store_true", help="print the result as JSON")
    ask.set_defaults(func=_ask)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
