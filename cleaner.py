"""
PROBOARD — Zero-Trust Data Ingestion & Sanitization
=====================================================
Accepts Google Sheet URLs or file uploads (.csv / .xlsx), validates
the schema, strips XSS / HTML payloads, and extracts platform
handles via strict regex.  Returns a clean DataFrame ready for the
async fetcher and database layers.
"""

from __future__ import annotations

import io
import logging
import re
from typing import IO

import pandas as pd

from config import EMAIL_DOMAIN, EXPECTED_COLUMNS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Security — HTML / XSS Stripping
# ---------------------------------------------------------------------------
_HTML_TAG_RE = re.compile(r"<[^>]+>", re.IGNORECASE)
_HTML_ENTITY_RE = re.compile(r"&[#\w]+;")
_JS_EVENT_RE = re.compile(r"\bon\w+\s*=", re.IGNORECASE)


def _strip_html(text: str) -> str:
    """Remove HTML tags, entities, and JS event-handler attributes."""
    text = _HTML_TAG_RE.sub("", text)
    text = _HTML_ENTITY_RE.sub("", text)
    text = _JS_EVENT_RE.sub("", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Handle Parsing — Strict Regex
# ---------------------------------------------------------------------------
_LC_URL_RE = re.compile(
    r"https?://(?:www\.)?leetcode\.com/(?:u/)?([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
_HR_URL_RE = re.compile(
    r"https?://(?:www\.)?hackerrank\.com/(?:profile/)?([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)


def parse_lc_handle(raw: object) -> str | None:
    """
    Extract a LeetCode username from a raw cell value.

    Accepts full URLs (``leetcode.com/u/handle``, ``leetcode.com/handle``)
    and strips trailing paths / query strings.  Returns ``None`` for
    empty, NaN, or non-LeetCode URLs.
    """
    if pd.isna(raw) or str(raw).strip() == "":
        return None

    cleaned = _strip_html(str(raw).strip())
    match = _LC_URL_RE.search(cleaned)
    if match:
        return match.group(1)

    # Reject: URL present but not leetcode.com → security rule
    if re.search(r"https?://", cleaned, re.IGNORECASE):
        logger.warning("Rejected non-LeetCode URL: %s", cleaned[:80])
        return None

    # Bare handle (no URL) — allow only safe chars
    bare = cleaned.split()[0]  # first token only
    if re.fullmatch(r"[A-Za-z0-9_-]+", bare):
        return bare
    return None


def parse_hr_handle(raw: object) -> str | None:
    """
    Extract a HackerRank username from a raw cell value.

    Accepts full URLs (``hackerrank.com/profile/handle``,
    ``hackerrank.com/handle``) and strips trailing paths / query
    strings.  Returns ``None`` for empty, NaN, or non-HR URLs.
    """
    if pd.isna(raw) or str(raw).strip() == "":
        return None

    cleaned = _strip_html(str(raw).strip())
    match = _HR_URL_RE.search(cleaned)
    if match:
        return match.group(1)

    # Reject: URL present but not hackerrank.com
    if re.search(r"https?://", cleaned, re.IGNORECASE):
        logger.warning("Rejected non-HackerRank URL: %s", cleaned[:80])
        return None

    # Bare handle
    bare = cleaned.split()[0]
    if re.fullmatch(r"[A-Za-z0-9_-]+", bare):
        return bare
    return None


# ---------------------------------------------------------------------------
# Google Sheet URL Validator
# ---------------------------------------------------------------------------
_GSHEET_ID_RE = re.compile(
    r"https?://docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)"
)


def validate_google_sheet_url(url: str) -> str:
    """
    Validate a Google Sheets URL and return the CSV export link.

    Raises ``ValueError`` if the URL does not match the expected
    Google Sheets domain pattern.
    """
    url = url.strip()
    match = _GSHEET_ID_RE.search(url)
    if not match:
        raise ValueError(
            f"Invalid Google Sheet URL — expected docs.google.com/spreadsheets/d/ID, "
            f"got: {url[:100]}"
        )
    sheet_id = match.group(1)
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"



# Define canonical internal names and their possible variations in the wild
COLUMN_ALIASES = {
    "roll_no": ["roll.no", "roll no", "roll number", "rollno", "id"],
    "name": ["student name", "name", "student"],
    "lc_link": ["leet code link", "leetcode profile link", "leetcode link", "leetcode"],
    "hr_link": ["hacker rank link", "hackerrank profile link", "hackerrank link", "hackerrank"],
    "basics_score": ["basics(5)", "basics", "score"]
}

REQUIRED_COLUMNS = ["roll_no", "name", "lc_link", "hr_link"]
EMAIL_DOMAIN = "gatesit.ac.in" # Adjust if needed

def _find_header_row(text: str) -> int:
    """
    Scan raw CSV text to locate the real header row.
    Uses case-insensitive matching to handle variations like 'Roll.No' vs 'roll no'.
    """
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        line_lower = line.lower()
        if "roll" in line_lower and "name" in line_lower:
            return idx
    return 0

def clean_dataframe(
    source: str, # type hint simplified for the snippet; keep yours if you prefer
    *,
    is_url: bool = False,
) -> pd.DataFrame:
    """
    Ingest, validate, sanitize, and return a clean student DataFrame with dynamic mapping.
    """
    # ------------------------------------------------------------------
    # 1. Load raw data
    # ------------------------------------------------------------------
    if is_url:
        import requests 
        # Ensure you have your validate_google_sheet_url function defined above this
        csv_url = validate_google_sheet_url(str(source))
        resp = requests.get(csv_url, timeout=15)
        resp.raise_for_status()
        header_idx = _find_header_row(resp.text)
        df = pd.read_csv(io.StringIO(resp.text), skiprows=header_idx)
    elif isinstance(source, str) and source.endswith(".xlsx"):
        df = pd.read_excel(source, engine="openpyxl")
    elif isinstance(source, str):
        with open(source, encoding="utf-8") as fh:
            text = fh.read()
        header_idx = _find_header_row(text)
        df = pd.read_csv(io.StringIO(text), skiprows=header_idx)
    else:
        # Streamlit UploadedFile or generic file-like
        raw_bytes = source.read()
        name = getattr(source, "name", "upload.csv")
        if name.endswith(".xlsx"):
            df = pd.read_excel(io.BytesIO(raw_bytes), engine="openpyxl")
        else:
            text = raw_bytes.decode("utf-8", errors="replace")
            header_idx = _find_header_row(text)
            df = pd.read_csv(io.StringIO(text), skiprows=header_idx)

    # ------------------------------------------------------------------
    # 2. Dynamic Column Mapping
    # ------------------------------------------------------------------
    # Strip whitespace and lowercase the raw headers for robust matching
    raw_cols = {c: str(c).strip().lower() for c in df.columns}
    rename_map = {}
    
    for raw_name, lower_name in raw_cols.items():
        for canonical, aliases in COLUMN_ALIASES.items():
            if lower_name in aliases or lower_name == canonical:
                rename_map[raw_name] = canonical
                break
                
    df = df.rename(columns=rename_map)

    # ------------------------------------------------------------------
    # 3. Schema validation (Check against canonical names)
    # ------------------------------------------------------------------
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Schema mismatch — could not map required columns: {missing}. "
            f"Parsed columns after mapping: {list(df.columns)}"
        )

    # Inject optional columns with defaults if they don't exist in this specific sheet
    if "basics_score" not in df.columns:
        df["basics_score"] = 0

    # ------------------------------------------------------------------
    # 4. Drop junk rows (section dividers, repeated headers)
    # ------------------------------------------------------------------
    df = df[df["roll_no"].notna()].copy()
    df = df[
        ~df["roll_no"]
        .astype(str)
        .str.contains(r"CSE|Roll\.No|roll no", case=False, na=False)
    ]

    # ------------------------------------------------------------------
    # 5. Sanitize every string cell (XSS / HTML strip)
    # ------------------------------------------------------------------
    # Make sure _strip_html is defined in your file
    str_cols = df.select_dtypes(include="object").columns
    for col in str_cols:
        df[col] = df[col].apply(
            lambda v: _strip_html(str(v)) if pd.notna(v) else v
        )

    # ------------------------------------------------------------------
    # 6. Parse handles via strict regex & Computed fields
    # ------------------------------------------------------------------
    # Make sure parse_lc_handle and parse_hr_handle are defined in your file
    df["lc_handle"] = df["lc_link"].apply(parse_lc_handle)
    df["hr_handle"] = df["hr_link"].apply(parse_hr_handle)

    df["email"] = df["roll_no"].apply(
        lambda r: f"{str(r).strip().lower()}@{EMAIL_DOMAIN}" if pd.notna(r) else None
    )

    # ------------------------------------------------------------------
    # 7. Normalize & select output columns
    # ------------------------------------------------------------------
    df["roll_no"] = df["roll_no"].astype(str).str.strip()
    df["name"] = df["name"].astype(str).str.strip()
    df["basics_score"] = pd.to_numeric(df["basics_score"], errors="coerce").fillna(0).astype(int)

    output_cols = ["roll_no", "name", "basics_score", "lc_handle", "hr_handle", "email"]
    df = df[output_cols].reset_index(drop=True)

    logger.info("Cleaned %d student records.", len(df))
    return df