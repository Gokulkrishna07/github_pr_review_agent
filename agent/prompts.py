"""Prompt templates for LLM code review, extracted for testability and configurability."""

import logging

logger = logging.getLogger(__name__)

FULL_FILE_MAX_LINES = 500

REQUIRED_PLACEHOLDERS = {"{filename}", "{patch}", "{pr_title}", "{pr_description}", "{file_content_section}"}

REVIEW_TEMPLATE = """\
You are a senior code reviewer. Analyze the following changes and return a JSON object with categorized review feedback.

Return this exact structure:
{{
  "whats_good": ["<genuine positive observation>", ...],
  "critical": [{{"issue": "<description>", "location": "line <N>"}}],
  "major":    [{{"issue": "<description>", "location": "line <N>"}}],
  "minor":    [{{"issue": "<description>", "location": "line <N>"}}],
  "nit":      [{{"issue": "<description>", "location": "line <N>"}}]
}}

Severity guide:
- critical : bugs, security vulnerabilities, data loss risks
- major    : significant performance issues, missing error handling, logic errors
- minor    : code quality, readability, unclear naming
- nit      : style suggestions, minor improvements (non-blocking)
- whats_good: at least 1-2 genuine positives — never leave this empty

Rules:
- "location" must reference the line number visible in the diff
- Only flag issues clearly present in the code shown — do not assume things are missing if they are not visible
- Use empty array [] for categories with nothing to report
- If there are NO issues at all, set all issue arrays to [] and include "This is a solid PR and good to merge" as the first item in whats_good
- Return ONLY valid JSON, no other text

PR context: {pr_title}
{pr_description}

File: {filename}
{file_content_section}
Changes made in this PR:
```diff
{patch}
```
"""


def _sanitize_input(text: str, max_len: int) -> str:
    """Truncate text to max_len and strip triple backticks to prevent prompt injection."""
    text = text[:max_len]
    text = text.replace("```", "")
    return text


def _build_file_content_section(file_content: str | None) -> str:
    """Return the full file content block for the prompt, or empty string if unavailable/too large."""
    if not file_content:
        return ""
    line_count = file_content.count("\n") + 1
    if line_count > FULL_FILE_MAX_LINES:
        return ""
    return f"Full file content for context:\n```\n{file_content}\n```\n"


def build_review_prompt(
    filename: str,
    patch: str,
    *,
    pr_title: str,
    pr_description: str,
    file_content: str | None = None,
) -> str:
    """Build the complete review prompt for a single file diff."""
    pr_title = _sanitize_input(pr_title, 200)
    pr_description = _sanitize_input(pr_description, 2000)
    description_section = f"PR description: {pr_description}" if pr_description.strip() else ""
    file_content_section = _build_file_content_section(file_content)

    return REVIEW_TEMPLATE.format(
        filename=filename,
        patch=patch,
        pr_title=pr_title,
        pr_description=description_section,
        file_content_section=file_content_section,
    )


def _validate_custom_template(template: str) -> bool:
    """Check that a custom template contains all required placeholders."""
    return all(p in template for p in REQUIRED_PLACEHOLDERS)


def build_review_prompt_with_config(
    filename: str,
    patch: str,
    *,
    pr_title: str,
    pr_description: str,
    file_content: str | None = None,
    custom_template: str | None = None,
) -> str:
    """Build review prompt, using custom_template if valid, else falling back to default."""
    pr_title = _sanitize_input(pr_title, 200)
    pr_description = _sanitize_input(pr_description, 2000)
    description_section = f"PR description: {pr_description}" if pr_description.strip() else ""
    file_content_section = _build_file_content_section(file_content)

    template = REVIEW_TEMPLATE
    if custom_template and _validate_custom_template(custom_template):
        template = custom_template
    elif custom_template:
        logger.warning(
            "Custom template missing required placeholders, using default. "
            "Required: %s", REQUIRED_PLACEHOLDERS
        )

    try:
        return template.format(
            filename=filename,
            patch=patch,
            pr_title=pr_title,
            pr_description=description_section,
            file_content_section=file_content_section,
        )
    except (KeyError, IndexError, ValueError) as e:
        logger.error("Failed to render template, falling back to default: %s", e)
        return REVIEW_TEMPLATE.format(
            filename=filename,
            patch=patch,
            pr_title=pr_title,
            pr_description=description_section,
            file_content_section=file_content_section,
        )
