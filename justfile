set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

default:
    @just --list

# install deps and git hooks
setup:
    uv sync
    uv run pre-commit install

test:
    uv run pytest

lint:
    uv run ruff check .
    uv run ruff format --check .

# auto-fix lint and formatting
fmt:
    uv run ruff check --fix .
    uv run ruff format .

# Olist Postgres (Docker Engine in the issue-radar WSL distro on G:): up | down | status | logs | psql
db command="status":
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/db.ps1 {{command}}

# (re)load the Olist CSVs from data/raw and (re)create the read-only agent_ro role
load:
    uv run python scripts/load_olist.py data/raw

# row counts as agent_ro, plus proof that agent_ro can only read
check-db:
    uv run python scripts/check_db.py
