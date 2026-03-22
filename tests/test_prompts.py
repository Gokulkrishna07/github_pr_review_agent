"""Tests for agent.prompts — prompt building and sanitization."""

from agent.prompts import (
    FULL_FILE_MAX_LINES,
    _build_file_content_section,
    _sanitize_input,
    build_review_prompt,
)


class TestSanitizeInput:
    def test_truncates_to_max_len(self):
        result = _sanitize_input("abcdef", 3)
        assert result == "abc"

    def test_strips_triple_backticks(self):
        result = _sanitize_input("before ```code``` after", 100)
        assert "```" not in result
        assert "before code after" == result

    def test_empty_string(self):
        assert _sanitize_input("", 100) == ""

    def test_truncation_before_backtick_strip(self):
        # Backticks at position 5+; truncated to 3 means no backticks to strip
        result = _sanitize_input("abc```def", 3)
        assert result == "abc"


class TestBuildFileContentSection:
    def test_returns_content_for_small_file(self):
        content = "def foo():\n    pass"
        result = _build_file_content_section(content)
        assert "Full file content" in result
        assert content in result

    def test_returns_empty_for_none(self):
        assert _build_file_content_section(None) == ""

    def test_returns_empty_for_empty_string(self):
        assert _build_file_content_section("") == ""

    def test_returns_empty_for_large_file(self):
        large = "\n".join(f"line {i}" for i in range(FULL_FILE_MAX_LINES + 1))
        assert _build_file_content_section(large) == ""

    def test_includes_file_at_exactly_max_lines(self):
        content = "\n".join(f"line {i}" for i in range(FULL_FILE_MAX_LINES))
        result = _build_file_content_section(content)
        assert "Full file content" in result


class TestBuildReviewPrompt:
    def test_includes_filename(self):
        prompt = build_review_prompt("app.py", "+ code", pr_title="T", pr_description="")
        assert "app.py" in prompt

    def test_includes_patch(self):
        prompt = build_review_prompt("f.py", "+ new_line", pr_title="T", pr_description="")
        assert "+ new_line" in prompt

    def test_includes_pr_title(self):
        prompt = build_review_prompt("f.py", "+ x", pr_title="Fix login bug", pr_description="")
        assert "Fix login bug" in prompt

    def test_includes_pr_description_when_present(self):
        prompt = build_review_prompt("f.py", "+ x", pr_title="T", pr_description="Refactored auth")
        assert "Refactored auth" in prompt

    def test_omits_description_section_when_empty(self):
        prompt = build_review_prompt("f.py", "+ x", pr_title="T", pr_description="")
        assert "PR description:" not in prompt

    def test_omits_description_when_whitespace_only(self):
        prompt = build_review_prompt("f.py", "+ x", pr_title="T", pr_description="   ")
        assert "PR description:" not in prompt

    def test_includes_file_content_when_provided(self):
        prompt = build_review_prompt(
            "f.py", "+ x", pr_title="T", pr_description="",
            file_content="def foo():\n    return 1"
        )
        assert "Full file content" in prompt
        assert "def foo():" in prompt

    def test_omits_file_content_when_none(self):
        prompt = build_review_prompt("f.py", "+ x", pr_title="T", pr_description="", file_content=None)
        assert "Full file content" not in prompt

    def test_sanitizes_pr_title(self):
        prompt = build_review_prompt("f.py", "+ x", pr_title="Title ```injection```", pr_description="")
        assert "```" not in prompt.split("```diff")[0]  # no backticks before the diff block

    def test_truncates_long_title(self):
        long_title = "A" * 500
        prompt = build_review_prompt("f.py", "+ x", pr_title=long_title, pr_description="")
        # Title should be truncated to 200
        assert "A" * 201 not in prompt

    def test_returns_string(self):
        result = build_review_prompt("f.py", "+ x", pr_title="T", pr_description="D")
        assert isinstance(result, str)

    def test_contains_json_structure_guide(self):
        prompt = build_review_prompt("f.py", "+ x", pr_title="T", pr_description="")
        assert "whats_good" in prompt
        assert "critical" in prompt
        assert "major" in prompt
        assert "minor" in prompt
        assert "nit" in prompt
