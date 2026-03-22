import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent.agent import _build_review_body, process_review


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WEBHOOK_SECRET = "test-webhook-secret"


def _sign(payload_bytes: bytes, secret: str = WEBHOOK_SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _pr_payload(action: str = "opened", pr_number: int = 7) -> dict:
    return {
        "action": action,
        "pull_request": {
            "number": pr_number,
            "head": {"sha": "abc123def456"},
        },
        "repository": {
            "name": "my-repo",
            "owner": {"login": "my-org"},
        },
    }


def _empty_review() -> dict:
    return {"whats_good": [], "critical": [], "major": [], "minor": [], "nit": []}


# ---------------------------------------------------------------------------
# _build_review_body — pure function tests
# ---------------------------------------------------------------------------


class TestBuildReviewBody:
    def test_all_categories_populated_produces_correct_sections(self):
        file_reviews = [
            (
                "src/app.py",
                {
                    "whats_good": ["Good naming"],
                    "critical": [{"issue": "SQL injection", "location": "L10"}],
                    "major": [{"issue": "No error handling", "location": "L20"}],
                    "minor": [{"issue": "Long function", "location": "L30"}],
                    "nit": [{"issue": "Typo in comment", "location": "L5"}],
                },
            )
        ]
        body = _build_review_body(file_reviews, "My PR", "llama-model")

        assert "## Code Review" in body
        assert "### ✅ What's Good" in body
        assert "Good naming" in body
        assert "**🔴 Critical:**" in body
        assert "SQL injection" in body
        assert "**🟡 Major:**" in body
        assert "No error handling" in body
        assert "**🔵 Minor:**" in body
        assert "Long function" in body
        assert "**💡 Nit:**" in body
        assert "Typo in comment" in body

    def test_no_issues_produces_no_issues_found_message(self):
        file_reviews = [("src/clean.py", _empty_review())]
        body = _build_review_body(file_reviews, "Clean PR", "model")

        assert "### ✅ This is a solid PR and good to merge" in body
        assert "**🔴 Critical:**" not in body
        assert "**🟡 Major:**" not in body

    def test_only_whats_good_no_issue_sections_shown(self):
        review = {**_empty_review(), "whats_good": ["Excellent structure"]}
        file_reviews = [("a.py", review)]
        body = _build_review_body(file_reviews, "PR", "model")

        assert "Excellent structure" in body
        assert "### Issues Found" not in body
        assert "### ✅ This is a solid PR and good to merge" in body

    def test_critical_issues_numbered_starting_from_1(self):
        review = {
            **_empty_review(),
            "critical": [
                {"issue": "First bug", "location": "L1"},
                {"issue": "Second bug", "location": "L2"},
            ],
        }
        file_reviews = [("app.py", review)]
        body = _build_review_body(file_reviews, "PR", "model")

        assert "- issue 1 —" in body
        assert "- issue 2 —" in body

    def test_major_issues_numbered_correctly(self):
        review = {
            **_empty_review(),
            "major": [
                {"issue": "Alpha", "location": ""},
                {"issue": "Beta", "location": ""},
                {"issue": "Gamma", "location": ""},
            ],
        }
        file_reviews = [("f.py", review)]
        body = _build_review_body(file_reviews, "PR", "model")

        assert "- issue 1 —" in body
        assert "- issue 2 —" in body
        assert "- issue 3 —" in body

    def test_multiple_files_issues_merged_into_correct_sections(self):
        file_reviews = [
            ("a.py", {**_empty_review(), "critical": [{"issue": "Bug in a", "location": "L1"}]}),
            ("b.py", {**_empty_review(), "critical": [{"issue": "Bug in b", "location": "L2"}]}),
        ]
        body = _build_review_body(file_reviews, "PR", "model")

        assert "Bug in a" in body
        assert "Bug in b" in body
        # Both should be under the single Critical section
        critical_section_start = body.index("**🔴 Critical:**")
        assert body.index("Bug in a") > critical_section_start
        assert body.index("Bug in b") > critical_section_start

    def test_location_included_in_backtick_format(self):
        review = {**_empty_review(), "minor": [{"issue": "Style issue", "location": "L42"}]}
        file_reviews = [("util.py", review)]
        body = _build_review_body(file_reviews, "PR", "model")

        assert "`[util.py L42]`" in body

    def test_missing_location_defaults_to_empty_string_no_crash(self):
        review = {**_empty_review(), "nit": [{"issue": "Minor thing", "location": ""}]}
        file_reviews = [("util.py", review)]
        body = _build_review_body(file_reviews, "PR", "model")

        assert "Minor thing" in body
        assert "`[util.py ]`" in body  # empty location results in trailing space inside backticks

    def test_model_name_appears_in_footer(self):
        file_reviews = [("a.py", _empty_review())]
        body = _build_review_body(file_reviews, "PR", "llama-3.1-8b-instant")

        assert "llama-3.1-8b-instant" in body

    def test_footer_always_present(self):
        file_reviews = [("a.py", _empty_review())]
        body = _build_review_body(file_reviews, "PR", "some-model")

        assert "Reviewed by PR Review Bot" in body
        assert "---" in body

    def test_whats_good_from_multiple_files_all_listed(self):
        file_reviews = [
            ("a.py", {**_empty_review(), "whats_good": ["Good thing A"]}),
            ("b.py", {**_empty_review(), "whats_good": ["Good thing B"]}),
        ]
        body = _build_review_body(file_reviews, "PR", "model")

        assert "Good thing A" in body
        assert "Good thing B" in body


# ---------------------------------------------------------------------------
# Webhook endpoint tests (ASGI integration)
# ---------------------------------------------------------------------------


@pytest.fixture
async def client():
    from agent.agent import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHealthEndpoint:
    async def test_get_health_returns_ok(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestMetricsEndpoint:
    async def test_get_metrics_returns_200_with_text_plain(self, client):
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]


class TestWebhookSignatureValidation:
    async def test_invalid_signature_returns_401(self, client):
        payload = json.dumps(_pr_payload()).encode()
        resp = await client.post(
            "/webhook",
            content=payload,
            headers={
                "x-hub-signature-256": "sha256=deadbeef",
                "x-github-event": "pull_request",
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 401

    async def test_empty_signature_returns_401(self, client):
        payload = json.dumps(_pr_payload()).encode()
        resp = await client.post(
            "/webhook",
            content=payload,
            headers={
                "x-hub-signature-256": "",
                "x-github-event": "pull_request",
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 401


class TestWebhookEventFiltering:
    async def test_push_event_returns_ignored(self, client):
        payload = b"{}"
        sig = _sign(payload)
        resp = await client.post(
            "/webhook",
            content=payload,
            headers={
                "x-hub-signature-256": sig,
                "x-github-event": "push",
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ignored"
        assert "push" in data["reason"]

    async def test_pull_request_closed_action_returns_ignored(self, client):
        pr_payload = _pr_payload(action="closed")
        payload = json.dumps(pr_payload).encode()
        sig = _sign(payload)
        resp = await client.post(
            "/webhook",
            content=payload,
            headers={
                "x-hub-signature-256": sig,
                "x-github-event": "pull_request",
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ignored"
        assert "closed" in data["reason"]


class TestWebhookProcessingTrigger:
    async def test_opened_action_returns_processing_with_pr_number(self, client):
        pr_payload = _pr_payload(action="opened", pr_number=42)
        payload = json.dumps(pr_payload).encode()
        sig = _sign(payload)

        with patch("agent.agent.process_review", new_callable=AsyncMock):
            resp = await client.post(
                "/webhook",
                content=payload,
                headers={
                    "x-hub-signature-256": sig,
                    "x-github-event": "pull_request",
                    "content-type": "application/json",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processing"
        assert data["pr"] == 42

    async def test_synchronize_action_returns_processing(self, client):
        pr_payload = _pr_payload(action="synchronize", pr_number=10)
        payload = json.dumps(pr_payload).encode()
        sig = _sign(payload)

        with patch("agent.agent.process_review", new_callable=AsyncMock):
            resp = await client.post(
                "/webhook",
                content=payload,
                headers={
                    "x-hub-signature-256": sig,
                    "x-github-event": "pull_request",
                    "content-type": "application/json",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processing"


# ---------------------------------------------------------------------------
# process_review — async unit tests
# ---------------------------------------------------------------------------


class TestProcessReview:
    """
    All external dependencies are patched in the agent.agent namespace.
    Metrics counters are real (prometheus counters accumulate across tests),
    so we capture the value before and after to assert deltas.
    """

    def _counter_value(self, counter, label: str) -> float:
        return counter.labels(status=label)._value.get()

    async def test_already_reviewed_returns_early_increments_duplicate(self):
        from agent.metrics import pr_reviews_total

        before = self._counter_value(pr_reviews_total, "duplicate")

        with (
            patch("agent.agent.is_already_reviewed", return_value=True),
            patch("agent.agent.get_pr_details", new_callable=AsyncMock) as mock_details,
        ):
            await process_review("owner", "repo", 1, "sha")

        mock_details.assert_not_called()
        after = self._counter_value(pr_reviews_total, "duplicate")
        assert after == before + 1

    async def test_no_reviewable_diffs_increments_skipped(self):
        from agent.metrics import pr_reviews_total

        before = self._counter_value(pr_reviews_total, "skipped")

        with (
            patch("agent.agent.is_already_reviewed", return_value=False),
            patch(
                "agent.agent.get_pr_details",
                new_callable=AsyncMock,
                return_value={"title": "T", "description": "D"},
            ),
            patch("agent.agent.get_pr_files", new_callable=AsyncMock, return_value=[]),
            patch("agent.agent.parse_pr_files", return_value=[]),
            patch("agent.agent.review_diff", new_callable=AsyncMock) as mock_review,
        ):
            await process_review("owner", "repo", 1, "sha")

        mock_review.assert_not_called()
        after = self._counter_value(pr_reviews_total, "skipped")
        assert after == before + 1

    async def test_successful_review_posts_comment_and_marks_reviewed(self):
        from agent.diff_parser import FileDiff
        from agent.metrics import pr_reviews_total

        before = self._counter_value(pr_reviews_total, "success")

        fake_diff = FileDiff(filename="main.py", patch="+ code", status="added", lines=1)
        fake_review = {**_empty_review(), "whats_good": ["Clean code"]}

        with (
            patch("agent.agent.is_already_reviewed", return_value=False),
            patch(
                "agent.agent.get_pr_details",
                new_callable=AsyncMock,
                return_value={"title": "My PR", "description": "desc"},
            ),
            patch("agent.agent.get_pr_files", new_callable=AsyncMock, return_value=[{}]),
            patch("agent.agent.parse_pr_files", return_value=[fake_diff]),
            patch("agent.agent.review_diff", new_callable=AsyncMock, return_value=fake_review),
            patch("agent.agent.post_pr_comment", new_callable=AsyncMock) as mock_comment,
            patch("agent.agent.mark_as_reviewed") as mock_mark,
        ):
            await process_review("owner", "repo", 5, "sha5")

        mock_comment.assert_called_once()
        call_args = mock_comment.call_args
        assert call_args[0][2] == 5  # pr_number positional arg
        posted_body = call_args[0][3]
        assert "Clean code" in posted_body

        mock_mark.assert_called_once_with("owner", "repo", 5, "sha5")
        after = self._counter_value(pr_reviews_total, "success")
        assert after == before + 1

    async def test_all_file_reviews_fail_increments_failed_no_comment(self):
        from agent.diff_parser import FileDiff
        from agent.metrics import pr_reviews_total

        before = self._counter_value(pr_reviews_total, "failed")

        fake_diff = FileDiff(filename="main.py", patch="+ code", status="added", lines=1)

        with (
            patch("agent.agent.is_already_reviewed", return_value=False),
            patch(
                "agent.agent.get_pr_details",
                new_callable=AsyncMock,
                return_value={"title": "T", "description": "D"},
            ),
            patch("agent.agent.get_pr_files", new_callable=AsyncMock, return_value=[{}]),
            patch("agent.agent.parse_pr_files", return_value=[fake_diff]),
            patch(
                "agent.agent.review_diff",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM error"),
            ),
            patch("agent.agent.post_pr_comment", new_callable=AsyncMock) as mock_comment,
        ):
            await process_review("owner", "repo", 3, "sha3")

        mock_comment.assert_not_called()
        after = self._counter_value(pr_reviews_total, "failed")
        assert after == before + 1

    async def test_one_file_fails_one_succeeds_posts_partial_review(self):
        from agent.diff_parser import FileDiff
        from agent.metrics import pr_reviews_total

        before = self._counter_value(pr_reviews_total, "success")

        diff_a = FileDiff(filename="a.py", patch="+ a", status="added", lines=1)
        diff_b = FileDiff(filename="b.py", patch="+ b", status="added", lines=1)
        review_b = {**_empty_review(), "whats_good": ["Nice work in b"]}

        call_count = 0

        async def review_side_effect(filename, patch, **kwargs):
            nonlocal call_count
            call_count += 1
            if filename == "a.py":
                raise RuntimeError("a.py failed")
            return review_b

        with (
            patch("agent.agent.is_already_reviewed", return_value=False),
            patch(
                "agent.agent.get_pr_details",
                new_callable=AsyncMock,
                return_value={"title": "PR", "description": ""},
            ),
            patch("agent.agent.get_pr_files", new_callable=AsyncMock, return_value=[{}, {}]),
            patch("agent.agent.parse_pr_files", return_value=[diff_a, diff_b]),
            patch("agent.agent.review_diff", new_callable=AsyncMock, side_effect=review_side_effect),
            patch("agent.agent.post_pr_comment", new_callable=AsyncMock) as mock_comment,
            patch("agent.agent.mark_as_reviewed"),
        ):
            await process_review("owner", "repo", 8, "sha8")

        mock_comment.assert_called_once()
        posted_body = mock_comment.call_args[0][3]
        assert "Nice work in b" in posted_body
        after = self._counter_value(pr_reviews_total, "success")
        assert after == before + 1

    async def test_exception_in_get_pr_details_increments_failed(self):
        from agent.metrics import pr_reviews_total

        before = self._counter_value(pr_reviews_total, "failed")

        with (
            patch("agent.agent.is_already_reviewed", return_value=False),
            patch(
                "agent.agent.get_pr_details",
                new_callable=AsyncMock,
                side_effect=RuntimeError("GitHub API down"),
            ),
            patch("agent.agent.post_pr_comment", new_callable=AsyncMock) as mock_comment,
        ):
            await process_review("owner", "repo", 9, "sha9")

        mock_comment.assert_not_called()
        after = self._counter_value(pr_reviews_total, "failed")
        assert after == before + 1

    async def test_process_review_decrements_queue_depth(self):
        from agent.metrics import review_queue_depth

        before = review_queue_depth._value.get()

        with (
            patch("agent.agent.is_already_reviewed", return_value=True),
        ):
            await process_review("owner", "repo", 1, "sha")

        after = review_queue_depth._value.get()
        assert after == before - 1
