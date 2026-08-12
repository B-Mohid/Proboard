"""
PROBOARD — Centralized Configuration
=====================================
All paths, constants, and environment-driven secrets live here.
Import `config` from any module to get consistent settings.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Environment & Paths
# ---------------------------------------------------------------------------
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "proboard.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

# ---------------------------------------------------------------------------
# Google Sheets Ingestion
# ---------------------------------------------------------------------------
GOOGLE_SHEET_ID = os.getenv(
    "GOOGLE_SHEET_ID",
    "15v52FSkde4DJXkyie7Z0CCq1zQoT0hS0nQRXkORkONg",
)
CSV_URL = (
    f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/export?format=csv"
)

# ---------------------------------------------------------------------------
# Schema — expected columns in the raw Google Sheet
# ---------------------------------------------------------------------------
EXPECTED_COLUMNS = [
    "Sl.No",
    "Roll.No",
    "Student Name",
    "Basics(5)",
    "Leet Code Link",
    "Hacker Rank Link",
]

# ---------------------------------------------------------------------------
# Async / Networking
# ---------------------------------------------------------------------------
SEMAPHORE_LIMIT: int = 10          # max concurrent aiohttp requests
REQUEST_TIMEOUT: int = 10          # seconds per HTTP call
MAX_RETRIES: int = 3               # exponential-backoff retries on 429

# ---------------------------------------------------------------------------
# Analytics Weights & Thresholds
# ---------------------------------------------------------------------------
HR_WEIGHT: float = float(os.getenv("HR_WEIGHT", "0.5"))
AT_RISK_THRESHOLD: int = 10        # total score below this → flagged
CACHE_TTL: int = 900               # Streamlit cache TTL in seconds

# ---------------------------------------------------------------------------
# College Email
# ---------------------------------------------------------------------------
EMAIL_DOMAIN: str = "gatesit.ac.in"

# ---------------------------------------------------------------------------
# DSA Topics (13 categories for radar charts)
# ---------------------------------------------------------------------------
DSA_TOPICS: list[str] = [
    "Basics",
    "Array",
    "Two Pointer",
    "Sliding Window",
    "String",
    "Linked List",
    "Stack",
    "Queue",
    "Tree",
    "Graph",
    "Heap",
    "Searching",
    "Sorting",
]

# ---------------------------------------------------------------------------
# SMTP / Notifier  (all secrets from .env)
# ---------------------------------------------------------------------------
SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM: str = os.getenv("SMTP_FROM", SMTP_USER)
