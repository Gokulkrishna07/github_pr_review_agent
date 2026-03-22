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

groq_request_duration_seconds = Histogram(
    "groq_request_duration_seconds",
    "Groq API call duration",
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

github_request_duration_seconds = Histogram(
    "github_request_duration_seconds",
    "GitHub API call duration",
    ["endpoint"],  # pr_details | pr_files | file_content | post_comment
)

review_queue_depth = Gauge(
    "review_queue_depth",
    "Number of PR reviews currently queued",
)

files_skipped_total = Counter(
    "files_skipped_total",
    "Files skipped by diff parser",
    ["reason"],  # removed | no_patch | extension | too_large
)

llm_tokens_used_total = Counter(
    "llm_tokens_used_total",
    "Total LLM tokens consumed",
    ["type"],  # prompt | completion
)

retry_attempts_total = Counter(
    "retry_attempts_total",
    "Total retry attempts for GitHub API calls",
)
