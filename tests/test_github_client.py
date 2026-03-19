import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import base64

from agent.github_client import (
    PAGE_SIZE,
    _headers,
    _request_with_retry,
    get_file_content,
    get_pr_details,
    get_pr_files,
    post_pr_comment,
)


def _fake_response(status_code: int, body: dict | list) -> MagicMock:
    """Build a minimal fake httpx.Response-like object."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = body
    resp.raise_for_status = MagicMock()
    return resp


class TestGetFileContent:
    async def test_returns_decoded_file_content(self):
        content = "def hello():\n    return 42\n"
        encoded = base64.b64encode(content.encode()).decode()
        api_body = {"encoding": "base64", "content": encoded}
        fake_resp = _fake_response(200, api_body)

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=fake_resp):
            result = await get_file_content("owner", "repo", "hello.py", "abc123", "token")

        assert result == content

    async def test_returns_none_on_non_200_status(self):
        fake_resp = _fake_response(404, {})

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=fake_resp):
            result = await get_file_content("owner", "repo", "missing.py", "abc123", "token")

        assert result is None

    async def test_returns_none_when_encoding_not_base64(self):
        api_body = {"encoding": "utf-8", "content": "some content"}
        fake_resp = _fake_response(200, api_body)

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=fake_resp):
            result = await get_file_content("owner", "repo", "file.py", "abc123", "token")

        assert result is None

    async def test_returns_none_when_content_missing(self):
        api_body = {"encoding": "base64", "content": ""}
        fake_resp = _fake_response(200, api_body)

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=fake_resp):
            result = await get_file_content("owner", "repo", "file.py", "abc123", "token")

        assert result is None

    async def test_passes_commit_sha_as_ref_param(self):
        content = "x = 1\n"
        encoded = base64.b64encode(content.encode()).decode()
        api_body = {"encoding": "base64", "content": encoded}
        fake_resp = _fake_response(200, api_body)

        with patch(
            "httpx.AsyncClient.request", new_callable=AsyncMock, return_value=fake_resp
        ) as mock_req:
            await get_file_content("owner", "repo", "x.py", "deadbeef", "token")

        call_kwargs = mock_req.call_args
        assert call_kwargs[1]["params"] == {"ref": "deadbeef"}


class TestHeaders:
    def test_authorization_header_format(self):
        headers = _headers("my-token")
        assert headers["Authorization"] == "Bearer my-token"

    def test_accept_header_present(self):
        headers = _headers("tok")
        assert headers["Accept"] == "application/vnd.github+json"

    def test_api_version_header_present(self):
        headers = _headers("tok")
        assert headers["X-GitHub-Api-Version"] == "2022-11-28"


class TestGetPrDetails:
    async def test_returns_title_and_description(self):
        api_body = {"title": "Fix the bug", "body": "Fixes issue #42"}
        fake_resp = _fake_response(200, api_body)

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=fake_resp):
            result = await get_pr_details("owner", "repo", 1, "token")

        assert result["title"] == "Fix the bug"
        assert result["description"] == "Fixes issue #42"

    async def test_null_body_returns_empty_string_not_none(self):
        api_body = {"title": "No description", "body": None}
        fake_resp = _fake_response(200, api_body)

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=fake_resp):
            result = await get_pr_details("owner", "repo", 1, "token")

        assert result["description"] == ""
        assert result["description"] is not None

    async def test_missing_title_returns_empty_string(self):
        api_body = {"body": "Some description"}
        fake_resp = _fake_response(200, api_body)

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=fake_resp):
            result = await get_pr_details("owner", "repo", 1, "token")

        assert result["title"] == ""


class TestGetPrFiles:
    async def test_single_page_returns_correct_list(self):
        page_data = [{"filename": "a.py"}, {"filename": "b.py"}]
        fake_resp = _fake_response(200, page_data)

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=fake_resp):
            result = await get_pr_files("owner", "repo", 1, "token")

        assert result == page_data

    async def test_two_pages_combined_correctly(self):
        first_page = [{"filename": f"file_{i}.py"} for i in range(PAGE_SIZE)]
        second_page = [{"filename": "last.py"}]

        responses = [
            _fake_response(200, first_page),
            _fake_response(200, second_page),
        ]

        with patch(
            "httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=responses
        ):
            result = await get_pr_files("owner", "repo", 1, "token")

        assert len(result) == PAGE_SIZE + 1
        assert result[-1]["filename"] == "last.py"

    async def test_exactly_page_size_triggers_second_request(self):
        """When first page returns exactly PAGE_SIZE items, a second page must be fetched."""
        first_page = [{"filename": f"f{i}.py"} for i in range(PAGE_SIZE)]
        second_page = []  # empty second page signals end

        responses = [_fake_response(200, first_page), _fake_response(200, second_page)]

        with patch(
            "httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=responses
        ) as mock_req:
            result = await get_pr_files("owner", "repo", 1, "token")

        assert mock_req.call_count == 2
        assert len(result) == PAGE_SIZE


class TestPostPrComment:
    async def test_calls_correct_url_with_body_in_json(self):
        fake_resp = _fake_response(201, {"id": 1})

        with patch(
            "httpx.AsyncClient.request", new_callable=AsyncMock, return_value=fake_resp
        ) as mock_request:
            await post_pr_comment("myorg", "myrepo", 42, "Great PR!", "token")

        mock_request.assert_called_once()
        call_kwargs = mock_request.call_args
        assert call_kwargs[0][1] == "https://api.github.com/repos/myorg/myrepo/issues/42/comments"
        assert call_kwargs[1]["json"] == {"body": "Great PR!"}


class TestRequestWithRetry:
    async def test_returns_immediately_on_200(self):
        fake_resp = _fake_response(200, {})

        async with httpx.AsyncClient() as client:
            with patch.object(client, "request", new_callable=AsyncMock, return_value=fake_resp):
                result = await _request_with_retry(client, "GET", "http://example.com", token="tok")

        assert result.status_code == 200

    async def test_retries_twice_on_429_then_succeeds(self):
        rate_limited = _fake_response(429, {})
        success = _fake_response(200, {"ok": True})

        responses = [rate_limited, rate_limited, success]

        async with httpx.AsyncClient() as client:
            with patch.object(
                client, "request", new_callable=AsyncMock, side_effect=responses
            ), patch("asyncio.sleep", new_callable=AsyncMock):
                result = await _request_with_retry(client, "GET", "http://example.com", token="tok")

        assert result.status_code == 200

    async def test_retries_on_403(self):
        forbidden = _fake_response(403, {})
        success = _fake_response(200, {})

        async with httpx.AsyncClient() as client:
            with patch.object(
                client, "request", new_callable=AsyncMock, side_effect=[forbidden, success]
            ), patch("asyncio.sleep", new_callable=AsyncMock):
                result = await _request_with_retry(client, "GET", "http://example.com", token="tok")

        assert result.status_code == 200

    async def test_does_not_retry_on_404(self):
        not_found = _fake_response(404, {})

        async with httpx.AsyncClient() as client:
            with patch.object(
                client, "request", new_callable=AsyncMock, return_value=not_found
            ) as mock_req:
                result = await _request_with_retry(client, "GET", "http://example.com", token="tok")

        assert result.status_code == 404
        assert mock_req.call_count == 1

    async def test_does_not_retry_on_500(self):
        server_error = _fake_response(500, {})

        async with httpx.AsyncClient() as client:
            with patch.object(
                client, "request", new_callable=AsyncMock, return_value=server_error
            ) as mock_req:
                result = await _request_with_retry(client, "GET", "http://example.com", token="tok")

        assert result.status_code == 500
        assert mock_req.call_count == 1

    async def test_exhausts_all_retries_and_returns_last_response(self):
        rate_limited = _fake_response(429, {})

        # MAX_RETRIES = 3, so all 3 attempts return 429
        responses = [rate_limited, rate_limited, rate_limited]

        async with httpx.AsyncClient() as client:
            with patch.object(
                client, "request", new_callable=AsyncMock, side_effect=responses
            ), patch("asyncio.sleep", new_callable=AsyncMock):
                result = await _request_with_retry(client, "GET", "http://example.com", token="tok")

        assert result.status_code == 429
