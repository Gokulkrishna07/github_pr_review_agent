# GitHub PR Code Review Agent

AI-powered code review agent that automatically reviews pull requests using a locally-hosted LLM (Ollama + qwen2.5-coder:7b).

## Architecture

```
GitHub Webhook → FastAPI Agent → Ollama LLM → GitHub Review Comments
```

- **Webhook handler** receives PR events, verifies HMAC signature
- **Diff parser** extracts and filters changed files
- **Ollama client** sends diffs for review with structured JSON output
- **GitHub client** posts inline review comments back to the PR

## Prerequisites

- Docker & Docker Compose (local dev)
- Ubuntu VM with k3s (production)
- GitHub personal access token with `repo` scope
- GitHub webhook secret

## Local Development

1. Copy environment file and fill in your tokens:
   ```bash
   cp .env.example .env
   ```

2. Start all services:
   ```bash
   docker-compose up --build
   ```
   This starts Ollama, pulls the model, and starts the agent on port 8000.

3. Verify:
   ```bash
   curl http://localhost:8000/health
   curl http://localhost:8000/ready
   ```

## VM Deployment (k3s)

### Initial Setup

1. Install k3s on the VM:
   ```bash
   curl -sfL https://get.k3s.io | sh -
   ```

2. Clone the repo and create the secret:
   ```bash
   cd ~/Code_review_agent
   cp k8s/agent-secret.yaml k8s/agent-secret-actual.yaml
   # Edit agent-secret-actual.yaml with real values
   sudo kubectl apply -f k8s/agent-secret-actual.yaml
   ```

3. Build and import the agent image:
   ```bash
   docker build -t review-agent:latest ./agent
   docker save review-agent:latest | sudo k3s ctr images import -
   ```

4. Apply all manifests:
   ```bash
   sudo kubectl apply -f k8s/namespace.yaml
   sudo kubectl apply -f k8s/ollama-pv.yaml
   sudo kubectl apply -f k8s/ollama-deployment.yaml
   sudo kubectl apply -f k8s/agent-configmap.yaml
   sudo kubectl apply -f k8s/agent-deployment.yaml
   sudo kubectl apply -f k8s/ingress.yaml
   ```

### CI/CD

Pushes to `main` auto-deploy via GitHub Actions. Required secrets:
- `VM_HOST` — VM IP or hostname
- `VM_SSH_KEY` — SSH private key for the `ubuntu` user

## GitHub Webhook Configuration

1. Go to your repo → Settings → Webhooks → Add webhook
2. **Payload URL**: `http://<VM_IP>/webhook`
3. **Content type**: `application/json`
4. **Secret**: same value as `GITHUB_WEBHOOK_SECRET`
5. **Events**: select "Pull requests"

## RAM Budget (10GB VM)

| Component | Memory |
|-----------|--------|
| OS + k3s  | ~1.5GB |
| Ollama    | 7GB    |
| Agent     | 256MB  |
| Traefik   | ~100MB |
| Buffer    | ~1.1GB |

## Troubleshooting

```bash
# Check pod status
sudo kubectl get pods -n ai-reviewer

# Check agent logs
sudo kubectl logs -f deployment/review-agent -n ai-reviewer

# Check ollama logs
sudo kubectl logs -f deployment/ollama -n ai-reviewer

# Test webhook locally
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: pull_request" \
  -H "X-Hub-Signature-256: sha256=test" \
  -d '{"action":"opened","pull_request":{"number":1}}'
```
