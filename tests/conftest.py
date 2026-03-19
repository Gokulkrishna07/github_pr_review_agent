import os

# Set env vars BEFORE any agent imports so Settings() doesn't fail at module load time.
os.environ.setdefault("GH_TOKEN", "test-gh-token")
os.environ.setdefault("GH_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
