# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commit Style

Do not add `Co-Authored-By: Claude` or any AI attribution lines to commit messages.

## What This Project Does

An AI-powered GitHub Pull Request code reviewer. It runs as a FastAPI service that:
1. Receives GitHub PR webhook events
2. Fetches PR file diffs via GitHub API
3. Sends diffs to Groq API (llama-3.1-8b-instant) for analysis
4. Posts inline review comments back to the PR

## Running Locally

```bash
# Copy and fill in credentials
cp .env.example .env

# Start with Docker Compose
docker-compose up --build

# Health check
curl http://localhost:8000/health
```

Required env vars (in `.env`): `GH_TOKEN`, `GH_WEBHOOK_SECRET`, `GROQ_API_KEY`

Optional: `LOG_LEVEL` (default: INFO), `MAX_DIFF_LINES` (default: 500), `GROQ_MODEL`, `GROQ_TIMEOUT`

## Manual Webhook Testing

```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: pull_request" \
  -H "X-Hub-Signature-256: sha256=<computed_sig>" \
  -d '{"action":"opened","pull_request":{"number":1},"repository":{"full_name":"owner/repo"}}'
```

## Architecture

```
GitHub Webhook → agent.py (FastAPI) → diff_parser.py → groq_client.py → github_client.py → GitHub PR comment
```

### Key modules (`agent/`)

- **agent.py** — FastAPI app. Validates webhook signatures, queues background review tasks. Semaphore limits to 3 concurrent reviews.
- **webhook_verify.py** — HMAC-SHA256 signature verification.
- **diff_parser.py** — Parses GitHub diff format, filters out binary files, lock files, minified assets, and diffs exceeding `MAX_DIFF_LINES`.
- **groq_client.py** — Calls Groq API. Uses multi-layer response parsing: direct JSON → markdown code block extraction → regex fallback. Returns list of `{line, severity, comment}` objects.
- **github_client.py** — Async httpx GitHub API client. Fetches PR files, posts all review comments as a single API call. Has exponential backoff retry on 403/429.
- **config.py** — Pydantic Settings loading from `.env`.

### Severity levels posted as comments
- `critical` → 🔴
- `warning` → 🟡
- `suggestion` → 🔵

### Files skipped by diff parser
Extensions: `.lock`, `.sum`, `.mod`, `.min.js`, `.min.css`, `.png`, `.jpg`, `.jpeg`, `.gif`, `.ico`, `.svg`, `.woff`, `.woff2`, `.ttf`, `.eot`, `.pdf`

## Deployment

CI/CD via `.github/workflows/deploy.yml` — pushes to `main` trigger SSH deploy to a k3s VM:
1. Builds Docker image from `agent/Dockerfile`
2. Imports into k3s containerd
3. Applies manifests in `k8s/`
4. Rolls out with `kubectl rollout status`

### Kubernetes layout (`k8s/`)
- Namespace: `ai-reviewer`
- Deployment: 1 replica, tolerations for control-plane node, 128Mi/256Mi memory, /health liveness+readiness probes
- Ingress: Traefik routes `/webhook` → agent service (port 80 → container 8000)
- Config: `agent-configmap.yaml` (non-sensitive), `agent-secret.yaml` (credentials template — fill in and apply manually)

To deploy k8s secrets manually:
```bash
kubectl apply -f k8s/agent-secret.yaml  # after filling in base64-encoded values
```
