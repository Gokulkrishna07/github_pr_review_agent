import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.groq_client import (
    _empty_review,
    _extract_candidates,
    _parse_response,
    _validate_review,
    review_diff,
)


class TestExtractCandidates:
    def test_bare_json_text_returns_text_as_first_candidate(self):
        text = '{"whats_good": []}'
        candidates = _extract_candidates(text)
        assert candidates[0] == text

    def test_json_in_backtick_json_block_extracted(self):
        inner = '{"whats_good": ["good thing"]}'
        text = f"```json\n{inner}\n```"
        candidates = _extract_candidates(text)
        assert inner in candidates

    def test_json_in_plain_backtick_block_extracted(self):
        inner = '{"critical": []}'
        text = f"```\n{inner}\n```"
        candidates = _extract_candidates(text)
        assert inner in candidates

    def test_json_embedded_in_prose_extracted(self):
        inner = '{"major": []}'
        text = f'Here is the review: {inner} — end of review.'
        candidates = _extract_candidates(text)
        assert inner in candidates

    def test_multiple_candidates_returned_for_complex_text(self):
        inner = '{"whats_good": []}'
        text = f"Some explanation.\n```json\n{inner}\n```\n{inner}"
        candidates = _extract_candidates(text)
        assert len(candidates) >= 2


class TestParseResponse:
    def test_valid_json_string_returns_correct_dict(self):
        data = {"whats_good": ["clean code"], "critical": [], "major": [], "minor": [], "nit": []}
        result = _parse_response(json.dumps(data))
        assert result["whats_good"] == ["clean code"]
        assert result["critical"] == []

    def test_json_wrapped_in_markdown_block_parsed(self):
        data = {"whats_good": [], "critical": [{"issue": "bug", "location": "line 10"}]}
        text = f"```json\n{json.dumps(data)}\n```"
        result = _parse_response(text)
        assert result["critical"][0]["issue"] == "bug"

    def test_json_embedded_in_explanation_text_parsed(self):
        data = {"whats_good": ["nice"], "major": [{"issue": "slow loop", "location": "L5"}]}
        text = f"Here is my review:\n{json.dumps(data)}\nThat concludes my review."
        result = _parse_response(text)
        assert result["whats_good"] == ["nice"]
        assert result["major"][0]["issue"] == "slow loop"

    def test_completely_invalid_text_returns_empty_review(self):
        result = _parse_response("This is not JSON at all.")
        assert result == _empty_review()

    def test_valid_json_missing_some_keys_returns_defaults(self):
        # Only whats_good present; other keys should default to empty lists.
        data = {"whats_good": ["great naming"]}
        result = _parse_response(json.dumps(data))
        assert result["whats_good"] == ["great naming"]
        assert result["critical"] == []
        assert result["major"] == []
        assert result["minor"] == []
        assert result["nit"] == []

    def test_empty_string_returns_empty_review(self):
        result = _parse_response("")
        assert result == _empty_review()

    def test_whitespace_only_returns_empty_review(self):
        result = _parse_response("   \n  ")
        assert result == _empty_review()


class TestValidateReview:
    def test_includes_valid_items_for_all_categories(self):
        data = {
            "whats_good": ["clean"],
            "critical": [{"issue": "SQL injection", "location": "L10"}],
            "major": [{"issue": "no error handling", "location": "L20"}],
            "minor": [{"issue": "long function", "location": "L30"}],
            "nit": [{"issue": "typo", "location": "L5"}],
        }
        result = _validate_review(data)
        assert result["whats_good"] == ["clean"]
        assert result["critical"][0] == {"issue": "SQL injection", "location": "L10"}
        assert result["major"][0] == {"issue": "no error handling", "location": "L20"}
        assert result["minor"][0] == {"issue": "long function", "location": "L30"}
        assert result["nit"][0] == {"issue": "typo", "location": "L5"}

    def test_strips_items_missing_issue_field(self):
        data = {"critical": [{"location": "L10"}]}  # no "issue" key
        result = _validate_review(data)
        assert result["critical"] == []

    def test_strips_items_with_non_string_issue_value(self):
        data = {"major": [{"issue": 42, "location": "L1"}]}
        result = _validate_review(data)
        assert result["major"] == []

    def test_missing_location_defaults_to_empty_string(self):
        data = {"minor": [{"issue": "unused import"}]}  # no "location" key
        result = _validate_review(data)
        assert result["minor"][0] == {"issue": "unused import", "location": ""}

    def test_non_list_category_value_handled_gracefully(self):
        data = {"critical": "not a list"}
        result = _validate_review(data)
        assert result["critical"] == []

    def test_non_string_whats_good_items_stripped(self):
        data = {"whats_good": ["good", 42, None, "also good"]}
        result = _validate_review(data)
        assert result["whats_good"] == ["good", "also good"]

    def test_empty_data_returns_empty_review(self):
        result = _validate_review({})
        assert result == _empty_review()


class TestEmptyReview:
    def test_returns_correct_structure(self):
        result = _empty_review()
        assert set(result.keys()) == {"whats_good", "critical", "major", "minor", "nit"}

    def test_all_values_are_empty_lists(self):
        result = _empty_review()
        for key, value in result.items():
            assert value == [], f"Expected empty list for key '{key}', got {value!r}"

    def test_returns_independent_instances(self):
        a = _empty_review()
        b = _empty_review()
        a["critical"].append("something")
        assert b["critical"] == []


class TestReviewDiff:
    def _make_mock_completion(self, content: str):
        message = MagicMock()
        message.content = content
        choice = MagicMock()
        choice.message = message
        completion = MagicMock()
        completion.choices = [choice]
        return completion

    async def test_success_returns_parsed_result_and_increments_metric(self, mocker):
        response_data = {
            "whats_good": ["clean structure"],
            "critical": [],
            "major": [],
            "minor": [],
            "nit": [],
        }
        mock_completion = self._make_mock_completion(json.dumps(response_data))

        mock_create = AsyncMock(return_value=mock_completion)
        mock_client_instance = MagicMock()
        mock_client_instance.chat = MagicMock()
        mock_client_instance.chat.completions = MagicMock()
        mock_client_instance.chat.completions.create = mock_create

        mock_metric = mocker.patch("agent.groq_client.groq_requests_total")
        mock_labels = MagicMock()
        mock_metric.labels.return_value = mock_labels

        with patch("agent.groq_client.AsyncGroq", return_value=mock_client_instance):
            result = await review_diff(
                "main.py",
                "+ def foo(): pass",
                pr_title="Add foo",
                pr_description="Adds the foo function",
                api_key="test-key",
                model="llama-3.1-8b-instant",
                timeout=30,
            )

        assert result["whats_good"] == ["clean structure"]
        mock_metric.labels.assert_called_with(status="success")
        mock_labels.inc.assert_called_once()

    async def test_groq_exception_increments_error_metric_and_reraises(self, mocker):
        mock_client_instance = MagicMock()
        mock_client_instance.chat = MagicMock()
        mock_client_instance.chat.completions = MagicMock()
        mock_client_instance.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("Groq API unavailable")
        )

        mock_metric = mocker.patch("agent.groq_client.groq_requests_total")
        mock_labels = MagicMock()
        mock_metric.labels.return_value = mock_labels

        with patch("agent.groq_client.AsyncGroq", return_value=mock_client_instance):
            with pytest.raises(RuntimeError, match="Groq API unavailable"):
                await review_diff(
                    "main.py",
                    "+ def foo(): pass",
                    pr_title="Add foo",
                    pr_description="",
                    api_key="test-key",
                    model="llama-3.1-8b-instant",
                    timeout=30,
                )

        mock_metric.labels.assert_called_with(status="error")
        mock_labels.inc.assert_called_once()

    async def test_empty_pr_description_omits_description_section(self, mocker):
        response_data = {"whats_good": [], "critical": [], "major": [], "minor": [], "nit": []}
        mock_completion = self._make_mock_completion(json.dumps(response_data))

        mock_create = AsyncMock(return_value=mock_completion)
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create = mock_create

        mocker.patch("agent.groq_client.groq_requests_total")

        with patch("agent.groq_client.AsyncGroq", return_value=mock_client_instance):
            result = await review_diff(
                "main.py",
                "+ line",
                pr_title="Title",
                pr_description="   ",  # whitespace-only → treated as empty
                api_key="key",
                model="model",
                timeout=10,
            )

        call_kwargs = mock_create.call_args
        prompt_used = call_kwargs[1]["messages"][0]["content"]
        # The description_section should be empty string when pr_description is blank
        assert "PR description:" not in prompt_used
