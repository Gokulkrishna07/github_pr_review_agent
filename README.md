# GitHub PR Code Review Agent

AI-powered code review agent that automatically reviews pull requests using the Groq API (llama-3.1-8b-instant).

> **Status**: Active — deployed on k3s, triggered via GitHub webhooks.
> **Model**: Groq llama-3.1-8b-instant (free tier)

## Architecture

```
GitHub Webhook → FastAPI Agent → Groq API → GitHub Review Comments
```

- **Webhook handler** receives PR events, verifies HMAC signature
- **Diff parser** extracts and filters changed files
- **Groq client** sends diffs for review with structured JSON output
- **GitHub client** posts inline review comments back to the PR

## Prerequisites

- Docker & Docker Compose (local dev)
- Ubuntu VM with k3s (production)
- GitHub personal access token with `repo` scope
- GitHub webhook secret
- Groq API key (free at console.groq.com)

## Local Development

1. Copy environment file and fill in your tokens:
   ```bash
   cp .env.example .env
   ```

2. Start the agent:
   ```bash
   docker-compose up --build
   ```

3. Verify:
   ```bash
   curl http://localhost:8000/health
   ```

## VM Deployment (k3s)

### Initial Setup

1. Install k3s on the VM:
   ```bash
   curl -sfL https://get.k3s.io | sh -
   ```

2. Create the k8s secret with your credentials:
   ```bash
   kubectl create secret generic agent-secret \
     --from-literal=GH_TOKEN=your_github_token \
     --from-literal=GH_WEBHOOK_SECRET=your_webhook_secret \
     --from-literal=GROQ_API_KEY=your_groq_api_key \
     -n ai-reviewer
   ```

3. Apply all manifests:
   ```bash
   sudo kubectl apply -f k8s/namespace.yaml
   sudo kubectl apply -f k8s/agent-configmap.yaml
   sudo kubectl apply -f k8s/agent-deployment.yaml
   sudo kubectl apply -f k8s/ingress.yaml
   ```

### CI/CD

Pushes to `main` auto-deploy via GitHub Actions. Required secrets:
- `VM_HOST` — VM IP or hostname
- `VM_SSH_KEY` — SSH private key
- `VM_SSH_USER` — SSH username
- `VM_SSH_PORT` — SSH port

## GitHub Webhook Configuration

1. Go to your repo → Settings → Webhooks → Add webhook
2. **Payload URL**: `http://<VM_IP>/webhook`
3. **Content type**: `application/json`
4. **Secret**: same value as `GH_WEBHOOK_SECRET`
5. **Events**: select "Pull requests"

## Resource Usage (10GB VM)

| Component | Memory |
|-----------|--------|
| OS + k3s  | ~1.5GB |
| Agent     | 256MB  |
| Traefik   | ~100MB |

No local model needed — Groq API handles all inference.

## Troubleshooting

```bash
# Check pod status
kubectl get pods -n ai-reviewer

# Check agent logs
kubectl logs -f deployment/review-agent -n ai-reviewer

# Test webhook locally
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: pull_request" \
  -H "X-Hub-Signature-256: sha256=test" \
  -d '{"action":"opened","pull_request":{"number":1}}'
```

