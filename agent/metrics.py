from prometheus_client import Counter, Gauge, Histogram

pr_reviews_total = Counter(
    "pr_reviews_total",
    "Total PR reviews processed",
    ["status"],  # success | failed | skipped | duplicate
)

pr_review_duration_seconds = Histogram(
    "pr_review_duration_seconds",
    "End-to-end time to complete a PR review",
)

groq_requests_total = Counter(
    "groq_requests_total",
    "Total Groq API requests",
    ["status"],  # success | error
)

active_reviews = Gauge(
    "active_reviews",
    "Number of PR reviews currently in progress",
)
