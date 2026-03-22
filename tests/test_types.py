"""Tests for agent.types — TypedDict definitions for review structures."""

from agent.types import FileReview, ReviewComment


class TestReviewComment:
    def test_creates_valid_review_comment(self):
        comment: ReviewComment = {"issue": "Missing null check", "location": "line 42"}
        assert comment["issue"] == "Missing null check"
        assert comment["location"] == "line 42"

    def test_required_keys(self):
        # TypedDict is a dict subclass; verify it has expected keys
        comment: ReviewComment = {"issue": "Bug", "location": "line 1"}
        assert "issue" in comment
        assert "location" in comment


class TestFileReview:
    def test_creates_valid_file_review(self):
        review: FileReview = {
            "whats_good": ["Clean code"],
            "critical": [{"issue": "SQL injection", "location": "line 10"}],
            "major": [],
            "minor": [{"issue": "Unclear naming", "location": "line 5"}],
            "nit": [],
        }
        assert review["whats_good"] == ["Clean code"]
        assert len(review["critical"]) == 1
        assert review["critical"][0]["issue"] == "SQL injection"
        assert review["minor"][0]["location"] == "line 5"

    def test_empty_file_review(self):
        review: FileReview = {
            "whats_good": [],
            "critical": [],
            "major": [],
            "minor": [],
            "nit": [],
        }
        for key in ("whats_good", "critical", "major", "minor", "nit"):
            assert review[key] == []

    def test_multiple_items_per_category(self):
        review: FileReview = {
            "whats_good": ["Good naming", "Well structured"],
            "critical": [],
            "major": [
                {"issue": "No error handling", "location": "line 20"},
                {"issue": "Race condition", "location": "line 45"},
            ],
            "minor": [],
            "nit": [{"issue": "Trailing whitespace", "location": "line 3"}],
        }
        assert len(review["whats_good"]) == 2
        assert len(review["major"]) == 2
        assert review["major"][1]["issue"] == "Race condition"


class TestTypeIntegration:
    def test_file_review_used_by_groq_empty_review(self):
        """Verify _empty_review() from groq_client matches FileReview structure."""
        from agent.groq_client import _empty_review

        review = _empty_review()
        expected_keys = {"whats_good", "critical", "major", "minor", "nit"}
        assert set(review.keys()) == expected_keys

    def test_file_review_used_by_groq_validate(self):
        """Verify _validate_review() from groq_client returns FileReview-compatible dict."""
        from agent.groq_client import _validate_review

        raw = {
            "whats_good": ["Nice work"],
            "critical": [{"issue": "Bug", "location": "line 1"}],
            "major": [],
            "minor": [],
            "nit": [],
        }
        result = _validate_review(raw)
        assert result["whats_good"] == ["Nice work"]
        assert result["critical"][0]["issue"] == "Bug"
        assert result["critical"][0]["location"] == "line 1"

    def test_validate_review_filters_invalid_items(self):
        """Ensure _validate_review strips out malformed entries."""
        from agent.groq_client import _validate_review

        raw = {
            "whats_good": ["Good", 123, None],
            "critical": [
                {"issue": "Real bug", "location": "line 5"},
                {"not_an_issue": "bad"},
                "just a string",
            ],
            "major": [],
            "minor": [],
            "nit": [],
        }
        result = _validate_review(raw)
        assert result["whats_good"] == ["Good"]
        assert len(result["critical"]) == 1
        assert result["critical"][0]["issue"] == "Real bug"
