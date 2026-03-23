"""Tests for the dynamic prompt builder with custom template support."""

from agent.prompts import (
    REVIEW_TEMPLATE,
    REQUIRED_PLACEHOLDERS,
    _validate_custom_template,
    build_review_prompt_with_config,
)


VALID_CUSTOM_TEMPLATE = """\
You are a security-focused reviewer.
File: {filename}
{file_content_section}
PR: {pr_title}
{pr_description}
Diff:
{patch}
Return JSON only.
"""


class TestValidateCustomTemplate:
    def test_valid_template(self):
        assert _validate_custom_template(VALID_CUSTOM_TEMPLATE) is True

    def test_default_template_is_valid(self):
        assert _validate_custom_template(REVIEW_TEMPLATE) is True

    def test_missing_filename(self):
        template = VALID_CUSTOM_TEMPLATE.replace("{filename}", "FIXED_NAME")
        assert _validate_custom_template(template) is False

    def test_missing_patch(self):
        template = VALID_CUSTOM_TEMPLATE.replace("{patch}", "no-diff")
        assert _validate_custom_template(template) is False

    def test_empty_string(self):
        assert _validate_custom_template("") is False

    def test_all_placeholders_required(self):
        for placeholder in REQUIRED_PLACEHOLDERS:
            partial = VALID_CUSTOM_TEMPLATE.replace(placeholder, "REMOVED")
            assert _validate_custom_template(partial) is False, (
                f"Should reject template missing {placeholder}"
            )


class TestBuildReviewPromptWithConfig:
    def test_no_custom_template_uses_default(self):
        result = build_review_prompt_with_config(
            "app.py", "+ new line",
            pr_title="Add feature", pr_description="desc",
        )
        assert "senior code reviewer" in result
        assert "app.py" in result
        assert "+ new line" in result

    def test_none_custom_template_uses_default(self):
        result = build_review_prompt_with_config(
            "app.py", "+ line",
            pr_title="Title", pr_description="",
            custom_template=None,
        )
        assert "senior code reviewer" in result

    def test_valid_custom_template_is_used(self):
        result = build_review_prompt_with_config(
            "app.py", "+ new line",
            pr_title="Add feature", pr_description="desc",
            custom_template=VALID_CUSTOM_TEMPLATE,
        )
        assert "security-focused reviewer" in result
        assert "senior code reviewer" not in result
        assert "app.py" in result
        assert "+ new line" in result

    def test_invalid_custom_template_falls_back_to_default(self):
        bad_template = "Review this: {filename} but no other placeholders"
        result = build_review_prompt_with_config(
            "app.py", "+ line",
            pr_title="Title", pr_description="",
            custom_template=bad_template,
        )
        # Should fall back to default
        assert "senior code reviewer" in result
        assert "app.py" in result

    def test_empty_custom_template_uses_default(self):
        result = build_review_prompt_with_config(
            "app.py", "+ line",
            pr_title="Title", pr_description="",
            custom_template="",
        )
        assert "senior code reviewer" in result

    def test_sanitization_applied_to_custom_template(self):
        result = build_review_prompt_with_config(
            "app.py", "+ line",
            pr_title="Title with ```backticks```",
            pr_description="Desc with ```more```",
            custom_template=VALID_CUSTOM_TEMPLATE,
        )
        # Backticks should be stripped from title/description
        assert "```" not in result.split("Diff:")[0]

    def test_file_content_included_when_small(self):
        result = build_review_prompt_with_config(
            "app.py", "+ line",
            pr_title="Title", pr_description="",
            file_content="print('hello')",
            custom_template=VALID_CUSTOM_TEMPLATE,
        )
        assert "print('hello')" in result

    def test_file_content_excluded_when_too_large(self):
        large_content = "\n".join(f"line {i}" for i in range(600))
        result = build_review_prompt_with_config(
            "app.py", "+ line",
            pr_title="Title", pr_description="",
            file_content=large_content,
            custom_template=VALID_CUSTOM_TEMPLATE,
        )
        assert "line 599" not in result

    def test_pr_description_section_omitted_when_empty(self):
        result = build_review_prompt_with_config(
            "app.py", "+ line",
            pr_title="Title", pr_description="   ",
            custom_template=VALID_CUSTOM_TEMPLATE,
        )
        assert "PR description:" not in result
