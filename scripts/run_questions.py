"""Run the agent on a list of questions; report status, steps, tokens and time per question.

    uv run python scripts/run_questions.py scripts/smoke_questions.txt [--model M]

Used to measure what one question costs before the 100-question golden set is written:
the free tier allows ~200K tokens per model per day, and prompt-cached tokens don't count.
Needs the Olist Postgres and llm-gateway running (see README).
"""

import argparse
import statistics
from collections import Counter
from pathlib import Path

from sql_agent.cli import run_question

DAILY_TOKENS = 200_000  # free tier, gpt-oss models (llm-gateway config/limits.yaml)


def load_questions(path: Path) -> list[str]:
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("questions", type=Path)
    parser.add_argument("--model", help="gateway model name (default: AGENT_MODEL)")
    args = parser.parse_args()

    results = []
    for i, question in enumerate(load_questions(args.questions), 1):
        r = run_question(question, model=args.model)
        u = r.usage
        counted = u.prompt - u.cached + u.completion  # what the rate limits see
        print(f"{i:>2}. {question}")
        answer = r.final.answer if r.final else r.error
        print(f"    -> {r.status}: {' '.join(str(answer).split())[:150]}")
        print(
            f"    {r.steps} steps, {', '.join(r.tool_calls)} | {counted:,} counted tokens "
            f"({u.prompt:,} prompt, {u.cached:,} prompt-cached, {u.completion:,} output) "
            f"| {r.seconds:.0f}s | {r.trace_path}"
        )
        results.append((r, counted))

    counted = [c for _, c in results]
    prompt = sum(r.usage.prompt for r, _ in results)
    cached = sum(r.usage.cached for r, _ in results)
    mean = statistics.fmean(counted)
    print(f"\n{len(results)} questions, statuses: {dict(Counter(r.status for r, _ in results))}")
    print(
        f"per question: {mean:,.0f} counted tokens on average (max {max(counted):,}), "
        f"{statistics.fmean(r.steps for r, _ in results):.1f} steps; "
        f"prompt-cached share {100 * cached / prompt if prompt else 0:.0f}%"
    )
    print(
        f"100 questions ~ {100 * mean:,.0f} counted tokens = "
        f"{100 * mean / DAILY_TOKENS:.1f} x one model's free daily budget"
    )


if __name__ == "__main__":
    main()
