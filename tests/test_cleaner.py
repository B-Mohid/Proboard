"""
Tests for cleaner.py — handle parsing, XSS stripping, URL
validation, schema enforcement, and security rejection.
"""

from __future__ import annotations

import io
import math

import pandas as pd
import pytest

from cleaner import (
    _strip_html,
    clean_dataframe,
    parse_hr_handle,
    parse_lc_handle,
    validate_google_sheet_url,
)


# ===================================================================
# XSS / HTML Stripping
# ===================================================================
class TestStripHtml:
    def test_removes_script_tags(self):
        assert "script" not in _strip_html("<script>alert('xss')</script>ok")

    def test_removes_html_entities(self):
        result = _strip_html("a &amp; b &lt; c")
        assert "&amp;" not in result
        assert "&lt;" not in result

    def test_removes_js_event_handlers(self):
        result = _strip_html('onclick="hack()" hello')
        assert "onclick" not in result

    def test_preserves_clean_text(self):
        assert _strip_html("hello world") == "hello world"

    def test_strips_nested_tags(self):
        result = _strip_html("<div><b>bold</b></div>")
        assert "<" not in result
        assert "bold" in result


# ===================================================================
# LeetCode Handle Parsing
# ===================================================================
class TestParseLcHandle:
    def test_standard_url(self):
        assert parse_lc_handle("https://leetcode.com/u/john_doe/") == "john_doe"

    def test_url_without_u_prefix(self):
        assert parse_lc_handle("https://leetcode.com/alice") == "alice"

    def test_url_with_www(self):
        assert parse_lc_handle("https://www.leetcode.com/u/bob") == "bob"

    def test_url_with_query_string(self):
        assert parse_lc_handle("https://leetcode.com/u/abc-123?tab=sub") == "abc-123"

    def test_bare_handle(self):
        assert parse_lc_handle("username_123") == "username_123"

    def test_empty_string(self):
        assert parse_lc_handle("") is None

    def test_none_value(self):
        assert parse_lc_handle(None) is None

    def test_nan_value(self):
        assert parse_lc_handle(float("nan")) is None

    def test_rejects_non_leetcode_url(self):
        assert parse_lc_handle("https://evil.com/u/hacker") is None

    def test_rejects_hackerrank_url(self):
        assert parse_lc_handle("https://hackerrank.com/profile/foo") is None

    def test_xss_in_url(self):
        result = parse_lc_handle('<script>alert(1)</script>https://leetcode.com/u/safe')
        # Should still parse the handle after stripping HTML
        assert result == "safe" or result is None  # either safe or rejected


# ===================================================================
# HackerRank Handle Parsing
# ===================================================================
class TestParseHrHandle:
    def test_profile_url(self):
        assert parse_hr_handle("https://hackerrank.com/profile/test_user") == "test_user"

    def test_url_with_www(self):
        assert parse_hr_handle("https://www.hackerrank.com/profile/alice") == "alice"

    def test_url_without_profile(self):
        assert parse_hr_handle("https://hackerrank.com/bob123") == "bob123"

    def test_empty(self):
        assert parse_hr_handle("") is None

    def test_nan(self):
        assert parse_hr_handle(float("nan")) is None

    def test_rejects_non_hr_url(self):
        assert parse_hr_handle("https://evil.com/profile/hacker") is None

    def test_bare_handle(self):
        assert parse_hr_handle("my_handle") == "my_handle"


# ===================================================================
# Google Sheet URL Validation
# ===================================================================
class TestValidateGoogleSheetUrl:
    def test_valid_url(self):
        url = "https://docs.google.com/spreadsheets/d/ABC123_xyz/edit#gid=0"
        result = validate_google_sheet_url(url)
        assert "ABC123_xyz" in result
        assert "export?format=csv" in result

    def test_rejects_non_google_url(self):
        with pytest.raises(ValueError, match="Invalid Google Sheet URL"):
            validate_google_sheet_url("https://evil.com/spreadsheets/d/123")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            validate_google_sheet_url("")


# ===================================================================
# Full Pipeline — clean_dataframe
# ===================================================================
class TestCleanDataframe:
    _CSV_HEADER = "Sl.No,Roll.No,Student Name,Basics(5),Leet Code Link,Hacker Rank Link"

    def _make_csv(self, *data_rows: str) -> io.BytesIO:
        lines = [self._CSV_HEADER] + list(data_rows)
        content = "\n".join(lines).encode("utf-8")
        buf = io.BytesIO(content)
        buf.name = "test.csv"
        return buf

    def test_valid_csv(self):
        buf = self._make_csv(
            "1,23F21A0566,Alice,5,https://leetcode.com/u/alice,https://hackerrank.com/profile/alice"
        )
        df = clean_dataframe(buf)
        assert len(df) == 1
        assert df.iloc[0]["roll_no"] == "23F21A0566"
        assert df.iloc[0]["lc_handle"] == "alice"
        assert df.iloc[0]["hr_handle"] == "alice"
        assert "@gatesit.ac.in" in df.iloc[0]["email"]

    def test_missing_column_raises(self):
        bad_csv = io.BytesIO(b"Col1,Col2\na,b")
        bad_csv.name = "bad.csv"
        with pytest.raises(ValueError, match="Schema mismatch"):
            clean_dataframe(bad_csv)

    def test_skips_divider_rows(self):
        buf = self._make_csv(
            "1,23F21A0566,Alice,5,https://leetcode.com/u/alice,",
            ",,CSE-B Section Divider,,,"
        )
        df = clean_dataframe(buf)
        assert len(df) == 1  # divider row skipped

    def test_handles_empty_links(self):
        buf = self._make_csv("1,23F21A0566,Alice,5,,")
        df = clean_dataframe(buf)
        assert df.iloc[0]["lc_handle"] is None
        assert df.iloc[0]["hr_handle"] is None
