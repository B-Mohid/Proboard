"""
Tests for fetcher.py — AsyncMock-based tests for LeetCode GraphQL,
HackerRank REST, and the orchestrator.  Tests cover 200, 404, 429
responses plus timeout / exception scenarios.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
import pytest_asyncio

from fetcher import (
    _empty_hr,
    _empty_lc,
    _fetch_hackerrank,
    _fetch_leetcode,
    fetch_all_stats,
)

# Force asyncio mode for all async tests in this module
pytestmark = pytest.mark.asyncio(loop_scope="function")


# ===================================================================
# Helpers
# ===================================================================
def _make_lc_success_response() -> dict:
    """Simulated LeetCode GraphQL 200 payload."""
    return {
        "data": {
            "matchedUser": {
                "submitStats": {
                    "acSubmissionNum": [
                        {"difficulty": "All", "count": 42},
                        {"difficulty": "Easy", "count": 20},
                        {"difficulty": "Medium", "count": 15},
                        {"difficulty": "Hard", "count": 7},
                    ]
                }
            }
        }
    }


def _make_hr_badges_response() -> list:
    return [{"id": 1}, {"id": 2}, {"id": 3}]


def _make_hr_scores_response() -> dict:
    return {"models": [{"score": 120.5}, {"score": 80.0}]}


# ===================================================================
# Context Manager Mock for aiohttp response
# ===================================================================
class MockResponse:
    """Lightweight mock for an aiohttp response contextmanager."""

    def __init__(self, status: int, json_data=None):
        self.status = status
        self._json = json_data or {}

    async def json(self):
        return self._json

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class MockSession:
    """Mock aiohttp.ClientSession with configurable responses."""

    def __init__(self, responses: dict[str, MockResponse] | MockResponse):
        self._responses = responses

    def post(self, url, **kwargs):
        if isinstance(self._responses, dict):
            return self._responses.get(url, MockResponse(404))
        return self._responses

    def get(self, url, **kwargs):
        if isinstance(self._responses, dict):
            return self._responses.get(url, MockResponse(404))
        return self._responses


# ===================================================================
# LeetCode Fetch Tests
# ===================================================================
class TestFetchLeetcode:
    async def test_success_200(self):
        session = MockSession(MockResponse(200, _make_lc_success_response()))
        sem = asyncio.Semaphore(10)
        result = await _fetch_leetcode(session, sem, "testuser")

        assert result["lc_total"] == 42
        assert result["lc_easy"] == 20
        assert result["lc_medium"] == 15
        assert result["lc_hard"] == 7

    async def test_not_found_returns_zeros(self):
        """Private or non-existent profile → matchedUser is None."""
        payload = {"data": {"matchedUser": None}}
        session = MockSession(MockResponse(200, payload))
        sem = asyncio.Semaphore(10)
        result = await _fetch_leetcode(session, sem, "ghost")

        assert result == _empty_lc()

    async def test_http_404_returns_zeros(self):
        session = MockSession(MockResponse(404))
        sem = asyncio.Semaphore(10)
        result = await _fetch_leetcode(session, sem, "missing")

        assert result == _empty_lc()

    async def test_429_retries_then_zeros(self):
        """Rate-limited → should retry then give up with zeros."""
        session = MockSession(MockResponse(429))
        sem = asyncio.Semaphore(10)
        with patch("fetcher.asyncio.sleep", new_callable=AsyncMock):
            result = await _fetch_leetcode(session, sem, "throttled")

        assert result == _empty_lc()

    async def test_exception_returns_zeros(self):
        """Network error → caught, returns zeros."""

        class BrokenSession:
            def post(self, *a, **kw):
                raise ConnectionError("network down")

        sem = asyncio.Semaphore(10)
        with patch("fetcher.asyncio.sleep", new_callable=AsyncMock):
            result = await _fetch_leetcode(BrokenSession(), sem, "broken")

        assert result == _empty_lc()


# ===================================================================
# HackerRank Fetch Tests
# ===================================================================
class TestFetchHackerrank:
    async def test_success_200(self):
        responses = {
            "https://www.hackerrank.com/rest/hackers/alice/badges": MockResponse(
                200, {"models": _make_hr_badges_response()}
            ),
            "https://www.hackerrank.com/rest/hackers/alice/scores_elo": MockResponse(
                200, _make_hr_scores_response()
            ),
        }
        session = MockSession(responses)
        sem = asyncio.Semaphore(10)
        result = await _fetch_hackerrank(session, sem, "alice")

        assert result["hr_badges"] == 3
        assert result["hr_score"] == 200.5

    async def test_404_returns_zeros(self):
        session = MockSession(MockResponse(404))
        sem = asyncio.Semaphore(10)
        result = await _fetch_hackerrank(session, sem, "ghost")

        assert result == _empty_hr()


# ===================================================================
# Orchestrator Tests (sync, using patch)
# ===================================================================
class TestFetchAllStats:
    def test_deduplication_and_mapping(self):
        """Two students share same handle → should fetch once, map to both."""
        df = pd.DataFrame(
            {
                "roll_no": ["S1", "S2"],
                "lc_handle": ["same_handle", "same_handle"],
                "hr_handle": [None, None],
            }
        )

        lc_result = {"lc_easy": 5, "lc_medium": 3, "lc_hard": 1, "lc_total": 9}

        async def mock_run_all(lc_handles, hr_handles):
            lc_map = {h: lc_result for h in lc_handles}
            return lc_map, {}

        with patch("fetcher._run_all", new=mock_run_all):
            with patch("fetcher.asyncio.get_running_loop", side_effect=RuntimeError):
                results = fetch_all_stats(df)

        assert len(results) == 2
        assert results[0]["lc_total"] == 9
        assert results[1]["lc_total"] == 9

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["roll_no", "lc_handle", "hr_handle"])

        async def mock_run_all(lc, hr):
            return {}, {}

        with patch("fetcher._run_all", new=mock_run_all):
            with patch("fetcher.asyncio.get_running_loop", side_effect=RuntimeError):
                results = fetch_all_stats(df)

        assert results == []


# ===================================================================
# Zero-value Struct Tests
# ===================================================================
class TestZeroStructs:
    def test_empty_lc(self):
        z = _empty_lc()
        assert z == {"lc_easy": 0, "lc_medium": 0, "lc_hard": 0, "lc_total": 0}

    def test_empty_hr(self):
        z = _empty_hr()
        assert z == {"hr_badges": 0, "hr_score": 0.0}
