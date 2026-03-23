"""Pydantic models for the dashboard API request/response serialization."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class UserResponse(BaseModel):
    github_id: int
    github_login: str
    avatar_url: str = ""


class OutputStyleConfig(BaseModel):
    show_whats_good: bool = True
    severity_categories: list[str] = Field(
        default=["critical", "major", "minor", "nit"]
    )
    format: Literal["grouped", "per_file"] = "grouped"
    emoji: bool = True
    include_line_refs: bool = True


class ReviewConfigCreate(BaseModel):
    repo_full_name: str
    prompt_template: str | None = None
    output_style: OutputStyleConfig = Field(default_factory=OutputStyleConfig)
    severity_filter: list[str] = Field(
        default=["critical", "major", "minor", "nit"]
    )
    llm_provider: str = "groq"
    llm_model: str | None = None
    active: bool = True


class ReviewConfigResponse(BaseModel):
    id: int
    user_id: int
    repo_full_name: str
    prompt_template: str | None = None
    output_style: OutputStyleConfig = Field(default_factory=OutputStyleConfig)
    severity_filter: list[str] = Field(
        default=["critical", "major", "minor", "nit"]
    )
    active: bool = True
    created_at: str = ""
    updated_at: str = ""


class PreviewRequest(BaseModel):
    prompt_template: str
    filename: str = "example.py"
    patch: str = "@@ -1,3 +1,4 @@\n+import os\n import sys"
    pr_title: str = "Add os import"
    pr_description: str = "Adding os module for path handling"
