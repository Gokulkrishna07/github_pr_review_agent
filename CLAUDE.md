# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A GitHub PR code review bot. GitHub webhook fires on PR open/sync → FastAPI agent parses the diff → sends each file to Groq LLM for review → posts a single aggregated comment back on the PR.

## Commands

```bash
# Install deps (from repo root, not agent/)
pip install -r agent/requirements.txt -r requirements-dev.txt

# Run tests (asyncio_mode=auto via pytest.ini, no flag needed)
pytest tests/ -v
pytest tests/test_diff_parser.py -v          # single file
pytest tests/test_agent.py::test_name -v     # single test

# Lint
ruff check agent/

# Run locally via Docker
cp .env.example .env   # fill in real tokens
docker-compose up --build   # agent on :8000

# Run directly (needs env vars set)
uvicorn agent.agent:app --host 0.0.0.0 --port 8000
```

## Architecture

```
GitHub webhook POST /webhook
  → HMAC signature verification (webhook_verify.py)
  → Rate limiting (in-memory per-IP, 60 req/min)
  → Idempotency check per (owner, repo, pr, commit_sha) in SQLite (idempotency.py)
  → Background task: process_review()
      → Fetch PR details + file list via GitHub API (github_client.py)
      → Parse/filter diffs (diff_parser.py) respecting max_diff_lines
      → For each file (up to 3 concurrent via asyncio.Semaphore):
          fetch full file content, send diff+context to Groq (groq_client.py)
      → Aggregate all file reviews into one markdown comment (_build_review_body)
      → Post comment via GitHub API
```

**LLM integration**: Uses Groq cloud API (not local Ollama despite .env.example references — the code uses `groq` SDK). Model default: `llama-3.3-70b-versatile`. Response is structured JSON with severity categories: critical, major, minor, nit, whats_good.

**Config**: `agent/config.py` — pydantic-settings `BaseSettings` loading from env vars / `.env` file. Key vars: `GH_TOKEN`, `GH_WEBHOOK_SECRET`, `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_TIMEOUT`, `MAX_DIFF_LINES`.

**Metrics**: Prometheus metrics exposed at `/metrics` (restricted to private IPs). Counters for review status and Groq request outcomes, gauge for active reviews, histogram for review duration.

## Deployment

- **Production**: k3s on Ubuntu VM. CI deploys on push to `main` (`.github/workflows/deploy.yml`). Builds Docker image, imports to k3s containerd, applies k8s manifests, rolling restart.
- **K8s namespace**: `ai-reviewer`
- **Security CI**: CodeQL analysis (`.github/workflows/codeql.yml`), Trivy container scanning (`.github/workflows/trivy.yml`), Dependabot for pip updates.

## Workflow Rules

- **No Co-Author tags**: Never add `Co-Authored-By` lines (or any Claude/AI attribution) in commit messages or PR descriptions.
- **Self code review**: After writing or modifying code, always perform a self code review before presenting the result — check for bugs, edge cases, security issues, and code quality.
- **No dummy tests**: Never write placeholder or trivial tests. Every test must cover a real, meaningful case. When writing tests, include all relevant test cases — happy paths, edge cases, error conditions, and boundary values.
- **Do not merge PRs**: Never merge pull requests automatically. PRs must be reviewed and merged by a human.

## Testing Notes

- All tests use `pytest-asyncio` with `auto` mode — async test functions work without `@pytest.mark.asyncio`.
- Tests mock external calls (GitHub API, Groq API) via `pytest-mock`. No real API calls in tests.
- Python 3.12 target (matches Dockerfile and CI).
