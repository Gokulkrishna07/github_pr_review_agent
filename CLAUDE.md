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
  → Queue depth check (max 20 queued reviews, returns 503 if full)
  → Extract installation_id from payload
  → Background task: process_review() (tracked in _active_tasks set)
      → Get installation token via GitHub App JWT auth (github_app.py)
      → Fetch PR details + file list via GitHub API (github_client.py)
      → Parse/filter diffs (diff_parser.py) respecting max_diff_lines
      → For each file (up to 3 concurrent via asyncio.Semaphore):
          fetch full file content, send diff+context to Groq (groq_client.py)
      → Aggregate all file reviews into one markdown comment (_build_review_body)
      → Post comment via GitHub API
  Graceful shutdown: lifespan handler waits up to 120s for active tasks before cancelling.
```

**LLM integration**: Uses Groq cloud API (`groq` SDK). Model default: `llama-3.3-70b-versatile`. Prompt template lives in `agent/prompts.py`. Response is structured JSON validated by Pydantic (`ReviewResponse` in `groq_client.py`) with severity categories: critical, major, minor, nit, whats_good. The parser (`_parse_response`) tries three extraction strategies: direct JSON → markdown code block → regex fallback. If Pydantic validation fails, it falls back to manual field extraction rather than discarding the response.

**Types**: `agent/types.py` defines `FileReview` and `ReviewComment` TypedDicts used as the internal data contract. `groq_client.py` also has `ReviewResponse` (Pydantic BaseModel) for LLM output validation — these mirror each other.

**Exceptions**: `agent/exceptions.py` has a hierarchy rooted at `AgentError`. Note: `github_client.py` defines its own `GitHubAPIError(RuntimeError)` separate from `exceptions.GitHubAPIError(AgentError)` — these are different classes used in different contexts.

**Auth**: GitHub App authentication (`agent/github_app.py`). JWT signed with App private key → exchanged for per-installation access tokens (auto-cached in `_token_cache`, refreshed 5 min before expiry). Installation ID extracted from webhook payload at runtime — supports multi-account installs.

**GitHub client**: `agent/github_client.py` uses `httpx.AsyncClient` with retry logic (`_request_with_retry`) — exponential backoff on 403/429/5xx, up to 3 attempts. File list pagination fetches pages 2-4 in parallel speculatively.

**Config**: `agent/config.py` — pydantic-settings `BaseSettings` loading from env vars / `.env` file. Key vars: `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GH_WEBHOOK_SECRET`, `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_TIMEOUT`, `MAX_DIFF_LINES`. `Settings()` is instantiated at module load time — env vars must be set before importing.

**Metrics**: Prometheus metrics exposed at `/metrics` (restricted to private IPs). All metrics defined in `agent/metrics.py`. Includes: review counters (success/failed/skipped/duplicate), Groq request outcomes, active reviews gauge, queue depth gauge, review duration histogram, GitHub API duration by endpoint, files skipped by reason, LLM token usage, retry attempts.

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
- `tests/conftest.py` sets dummy env vars (`GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, etc.) via `os.environ.setdefault` **before** any agent imports. This is required because `Settings()` runs at import time. If adding new required config fields, update conftest.py too or tests will fail on import.
