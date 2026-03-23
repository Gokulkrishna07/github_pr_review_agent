import os

# Set env vars BEFORE any agent imports so Settings() doesn't fail at module load time.
os.environ.setdefault("GITHUB_APP_ID", "123456")
os.environ.setdefault("GITHUB_APP_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("GH_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
os.environ.setdefault("GITHUB_OAUTH_CLIENT_ID", "test-oauth-client-id")
os.environ.setdefault("GITHUB_OAUTH_CLIENT_SECRET", "test-oauth-client-secret")
os.environ.setdefault("SESSION_SECRET_KEY", "test-session-secret-key-for-testing")
os.environ.setdefault("CONFIG_DB_PATH", ":memory:")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("PERPLEXITY_API_KEY", "test-perplexity-key")
