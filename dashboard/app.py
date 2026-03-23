"""Streamlit dashboard for PR Review Agent — prompt customization & output style configuration."""

from __future__ import annotations

import os

import httpx
import streamlit as st

# Internal URL for server-side API calls (pod-to-pod inside k8s)
API_BASE = os.environ.get("API_BASE_URL", "http://localhost:8000")
# Public URL for browser redirects (OAuth login, etc.)
PUBLIC_API_BASE = os.environ.get("PUBLIC_API_BASE_URL", API_BASE)

# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


def _api_headers() -> dict:
    token = st.session_state.get("session_token", "")
    return {"Cookie": f"session={token}"} if token else {}


def _api_get(path: str) -> httpx.Response:
    return httpx.get(f"{API_BASE}{path}", headers=_api_headers(), timeout=30)


def _api_put(path: str, json: dict) -> httpx.Response:
    return httpx.put(f"{API_BASE}{path}", json=json, headers=_api_headers(), timeout=30)


def _api_delete(path: str) -> httpx.Response:
    return httpx.delete(f"{API_BASE}{path}", headers=_api_headers(), timeout=30)


def _api_post(path: str, json: dict) -> httpx.Response:
    return httpx.post(f"{API_BASE}{path}", json=json, headers=_api_headers(), timeout=30)


def _is_logged_in() -> bool:
    return bool(st.session_state.get("session_token"))


def _check_auth() -> dict | None:
    """Verify session is still valid, return user info or None."""
    if not _is_logged_in():
        return None
    resp = _api_get("/auth/me")
    if resp.status_code == 200:
        return resp.json()
    st.session_state.pop("session_token", None)
    return None


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def login_page():
    st.title("PR Review Agent Dashboard")
    st.markdown("---")
    st.markdown("### Sign in to customize your code review settings")
    st.markdown(
        "Configure how the bot reviews your pull requests — "
        "customize the prompt template, output style, and severity filters."
    )
    st.markdown("")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.link_button(
            "Sign in with GitHub",
            f"{PUBLIC_API_BASE}/auth/github",
            use_container_width=True,
        )

    st.markdown("---")
    st.caption("You'll be redirected to GitHub to authorize the app.")

    # Handle OAuth callback — token passed as query param from backend redirect
    params = st.query_params
    if "session" in params:
        st.session_state["session_token"] = params["session"]
        st.query_params.clear()
        st.rerun()


def dashboard_page(user: dict):
    st.title("Dashboard")
    st.markdown(f"Welcome, **{user['github_login']}**!")
    st.markdown("---")

    # Fetch repos
    with st.spinner("Loading repositories..."):
        resp = _api_get("/api/repos")
    if resp.status_code != 200:
        st.error("Failed to load repositories. Check your GitHub connection.")
        return

    repos = resp.json()

    # Fetch existing configs
    config_resp = _api_get("/api/config")
    existing_configs = {}
    if config_resp.status_code == 200:
        for c in config_resp.json():
            existing_configs[c["repo_full_name"]] = c

    st.subheader("Your Repositories")

    # Default config card
    has_default = "*" in existing_configs
    with st.container(border=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown("**Default Config** (applies to all repos without specific config)")
            status = "Customized" if has_default else "Using system defaults"
            st.caption(status)
        with col2:
            if st.button("Configure", key="config_default"):
                st.session_state["config_repo"] = "*"
                st.session_state["page"] = "config"
                st.rerun()

    st.markdown("")

    # Repo cards
    for repo in repos:
        full_name = repo["full_name"]
        has_config = full_name in existing_configs
        with st.container(border=True):
            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                st.markdown(f"**{full_name}**")
                lang = repo.get("language", "")
                desc = repo.get("description", "")
                caption_parts = []
                if lang:
                    caption_parts.append(lang)
                if desc:
                    caption_parts.append(desc[:80])
                if has_config:
                    caption_parts.append("Custom config")
                st.caption(" · ".join(caption_parts) if caption_parts else "No description")
            with col2:
                if st.button("Configure", key=f"config_{full_name}"):
                    st.session_state["config_repo"] = full_name
                    st.session_state["page"] = "config"
                    st.rerun()
            with col3:
                if has_config:
                    if st.button("Reset", key=f"reset_{full_name}"):
                        _api_delete(f"/api/config/{full_name}")
                        st.rerun()


def config_page(user: dict):
    repo = st.session_state.get("config_repo", "*")
    display_name = "Default (all repos)" if repo == "*" else repo

    col1, col2 = st.columns([4, 1])
    with col1:
        st.title(f"Configure: {display_name}")
    with col2:
        if st.button("Back to Dashboard"):
            st.session_state["page"] = "dashboard"
            st.rerun()

    st.markdown("---")

    # Load defaults
    defaults_resp = _api_get("/api/config/defaults")
    if defaults_resp.status_code != 200:
        st.error("Failed to load defaults")
        return
    defaults = defaults_resp.json()

    # Load existing config
    config_resp = _api_get(f"/api/config/{repo}")
    existing = config_resp.json() if config_resp.status_code == 200 else None

    # --- Prompt Template ---
    st.subheader("Prompt Template")
    st.caption(
        "Customize the prompt sent to the LLM for code review. "
        "Must include these placeholders: `{filename}`, `{patch}`, `{pr_title}`, "
        "`{pr_description}`, `{file_content_section}`"
    )

    current_template = (
        existing.get("prompt_template") if existing and existing.get("prompt_template")
        else defaults["prompt_template"]
    )
    prompt_template = st.text_area(
        "Prompt template",
        value=current_template,
        height=400,
        label_visibility="collapsed",
    )

    # Preview
    with st.expander("Preview rendered prompt"):
        preview_resp = _api_post("/api/config/preview", json={
            "prompt_template": prompt_template,
            "filename": "example.py",
            "patch": "@@ -1,3 +1,4 @@\n+import os\n import sys",
            "pr_title": "Add os import",
            "pr_description": "Adding os module for path handling",
        })
        if preview_resp.status_code == 200:
            st.code(preview_resp.json()["rendered_prompt"], language="text")
        else:
            st.error("Template has errors — check placeholders")

    st.markdown("---")

    # --- LLM Provider & Model ---
    st.subheader("LLM Provider & Model")
    st.caption("Choose which AI provider and model to use for code reviews.")

    providers_resp = _api_get("/api/providers")
    providers = providers_resp.json() if providers_resp.status_code == 200 else []

    # Fallback if no providers configured
    if not providers:
        providers = [{"name": "groq", "display_name": "Groq", "models": ["llama-3.3-70b-versatile"], "default_model": "llama-3.3-70b-versatile"}]

    provider_names = [p["name"] for p in providers]
    provider_display = {p["name"]: p["display_name"] for p in providers}

    current_provider = (
        existing.get("llm_provider", "groq") if existing else "groq"
    )
    if current_provider not in provider_names:
        current_provider = provider_names[0]

    col_p1, col_p2 = st.columns(2)
    with col_p1:
        selected_provider = st.selectbox(
            "Provider",
            options=provider_names,
            format_func=lambda x: provider_display.get(x, x),
            index=provider_names.index(current_provider),
        )

    # Get models for selected provider
    provider_info = next((p for p in providers if p["name"] == selected_provider), providers[0])
    available_models = provider_info["models"]
    default_model = provider_info["default_model"]

    current_model = (
        existing.get("llm_model") if existing and existing.get("llm_model")
        else default_model
    )
    if current_model not in available_models:
        current_model = default_model

    with col_p2:
        selected_model = st.selectbox(
            "Model",
            options=available_models,
            index=available_models.index(current_model),
        )

    st.markdown("---")

    # --- Output Style ---
    st.subheader("Output Style")

    current_style = (
        existing.get("output_style", defaults["output_style"])
        if existing else defaults["output_style"]
    )

    col1, col2 = st.columns(2)
    with col1:
        show_whats_good = st.checkbox(
            "Show 'What's Good' section",
            value=current_style.get("show_whats_good", True),
        )
        use_emoji = st.checkbox(
            "Use emoji in output",
            value=current_style.get("emoji", True),
        )
        include_line_refs = st.checkbox(
            "Include line references",
            value=current_style.get("include_line_refs", True),
        )

    with col2:
        output_format = st.radio(
            "Issue grouping",
            options=["grouped", "per_file"],
            format_func=lambda x: "By severity" if x == "grouped" else "By file",
            index=0 if current_style.get("format", "grouped") == "grouped" else 1,
        )

    st.markdown("---")

    # --- Severity Filter ---
    st.subheader("Severity Filter")
    st.caption("Choose which severity levels to include in the review output.")

    all_severities = ["critical", "major", "minor", "nit"]
    current_severities = (
        existing.get("severity_filter", all_severities) if existing else all_severities
    )

    severity_cols = st.columns(4)
    selected_severities = []
    for i, sev in enumerate(all_severities):
        with severity_cols[i]:
            if st.checkbox(
                sev.capitalize(),
                value=sev in current_severities,
                key=f"sev_{sev}",
            ):
                selected_severities.append(sev)

    if not selected_severities:
        st.warning("At least one severity level should be selected.")

    st.markdown("---")

    # --- Save ---
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("Save Configuration", type="primary", use_container_width=True):
            config_data = {
                "repo_full_name": repo,
                "prompt_template": prompt_template if prompt_template != defaults["prompt_template"] else None,
                "output_style": {
                    "show_whats_good": show_whats_good,
                    "emoji": use_emoji,
                    "include_line_refs": include_line_refs,
                    "format": output_format,
                    "severity_categories": selected_severities,
                },
                "severity_filter": selected_severities,
                "llm_provider": selected_provider,
                "llm_model": selected_model,
                "active": True,
            }
            save_resp = _api_put(f"/api/config/{repo}", json=config_data)
            if save_resp.status_code == 200:
                st.success("Configuration saved!")
            else:
                st.error(f"Failed to save: {save_resp.text}")

    with col2:
        if st.button("Reset to Defaults", use_container_width=True):
            if existing:
                _api_delete(f"/api/config/{repo}")
            st.rerun()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    st.set_page_config(
        page_title="PR Review Agent",
        page_icon="🤖",
        layout="wide",
    )

    # Sidebar
    user = _check_auth()

    if user:
        with st.sidebar:
            st.image(user.get("avatar_url", ""), width=60)
            st.markdown(f"**{user['github_login']}**")
            st.markdown("---")

            page = st.radio(
                "Navigation",
                options=["dashboard", "config"],
                format_func=lambda x: "Dashboard" if x == "dashboard" else "Configuration",
                index=0 if st.session_state.get("page", "dashboard") == "dashboard" else 1,
                label_visibility="collapsed",
            )
            st.session_state["page"] = page

            st.markdown("---")
            if st.button("Logout"):
                _api_post("/auth/logout", json={})
                st.session_state.clear()
                st.rerun()

        current_page = st.session_state.get("page", "dashboard")
        if current_page == "config":
            config_page(user)
        else:
            dashboard_page(user)
    else:
        login_page()


if __name__ == "__main__":
    main()
