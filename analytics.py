"""
PROBOARD — Analytical Engine
==============================
Velocity tracking, composite scoring, NumPy percentile tiers,
platform affinity classification, and at-risk identification.
All functions operate on DataFrames for seamless Streamlit integration.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from config import AT_RISK_THRESHOLD, HR_WEIGHT
from models import DailyStat, Student

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Progress Tier Labels
# ---------------------------------------------------------------------------
TIER_TOP = "🏆 Outperforming"
TIER_MID = "📈 Average"
TIER_LOW = "⚠️ Needs Attention"


# ---------------------------------------------------------------------------
# Core: Build Leaderboard from DB
# ---------------------------------------------------------------------------
def build_leaderboard(
    session: "Session",
    snapshot_date: date | None = None,
) -> pd.DataFrame:
    """
    Join ``students`` + latest ``daily_stats`` and enrich with all
    computed analytics columns.

    Returns a DataFrame with columns:
        roll_no, name, email, lc_handle, hr_handle, basics_score,
        lc_easy, lc_medium, lc_hard, lc_total, hr_badges, hr_score,
        total_score, composite_score, velocity_7d, progress_tier,
        platform_affinity
    """
    today = snapshot_date or date.today()

    # Latest daily_stats for each student on `today`
    rows = (
        session.query(Student, DailyStat)
        .outerjoin(
            DailyStat,
            (Student.roll_no == DailyStat.roll_no) & (DailyStat.date == today),
        )
        .all()
    )

    records: list[dict[str, Any]] = []
    for student, stat in rows:
        records.append(
            {
                "roll_no": student.roll_no,
                "name": student.name,
                "email": student.email,
                "lc_handle": student.lc_handle,
                "hr_handle": student.hr_handle,
                "basics_score": student.basics_score,
                "lc_easy": stat.lc_easy if stat else 0,
                "lc_medium": stat.lc_medium if stat else 0,
                "lc_hard": stat.lc_hard if stat else 0,
                "lc_total": stat.lc_total if stat else 0,
                "hr_badges": stat.hr_badges if stat else 0,
                "hr_score": stat.hr_score if stat else 0.0,
                "total_score": stat.total_score if stat else 0.0,
            }
        )
    
    # 1. First instantiate the DataFrame
    df = pd.DataFrame(records)
    if df.empty:
        return df

    # 3. Add existing computed columns
    df["composite_score"] = compute_composite_score(df["lc_total"], df["hr_score"])
    df["velocity_7d"] = _velocity_bulk(session, df["roll_no"].tolist(), today)
    df["progress_tier"] = assign_progress_tiers(df["composite_score"].values)
    df["platform_affinity"] = df.apply(classify_platform_affinity, axis=1)
    df = pd.DataFrame(records)
    if df.empty:
        return df

    # --- Computed columns -------------------------------------------------
    df["composite_score"] = compute_composite_score(
        df["lc_total"], df["hr_score"]
    )
    df["velocity_7d"] = _velocity_bulk(session, df["roll_no"].tolist(), today)
    df["progress_tier"] = assign_progress_tiers(df["composite_score"].values)
    df["platform_affinity"] = df.apply(classify_platform_affinity, axis=1)

    return df.sort_values("composite_score", ascending=False).reset_index(
        drop=True
    )


# ---------------------------------------------------------------------------
# Composite Activity Score
# ---------------------------------------------------------------------------
def compute_composite_score(
    lc_total: pd.Series,
    hr_score: pd.Series,
) -> pd.Series:
    """``lc_total + (hr_score * HR_WEIGHT)``."""
    return lc_total + (hr_score * HR_WEIGHT)


# ---------------------------------------------------------------------------
# 7-Day Velocity
# ---------------------------------------------------------------------------
def compute_velocity_7d(
    session: Session,
    roll_no: str,
    today: date | None = None,
) -> float:
    """
    ``total_score(today) − total_score(today − 7)`` for one student.

    Returns ``0.0`` if either snapshot is missing.
    """
    today = today or date.today()
    week_ago = today - timedelta(days=7)

    current: DailyStat | None = (
        session.query(DailyStat)
        .filter_by(roll_no=roll_no, date=today)
        .first()
    )
    previous: DailyStat | None = (
        session.query(DailyStat)
        .filter_by(roll_no=roll_no, date=week_ago)
        .first()
    )

    score_now = current.total_score if current else 0.0
    score_then = previous.total_score if previous else 0.0
    return round(score_now - score_then, 2)


def _velocity_bulk(
    session: Session,
    roll_nos: list[str],
    today: date,
) -> list[float]:
    """Vectorised velocity lookup for the full cohort."""
    week_ago = today - timedelta(days=7)

    # Fetch today's and last week's stats in two bulk queries
    today_stats = {
        s.roll_no: s.total_score
        for s in session.query(DailyStat).filter(
            DailyStat.date == today,
            DailyStat.roll_no.in_(roll_nos),
        )
    }
    prev_stats = {
        s.roll_no: s.total_score
        for s in session.query(DailyStat).filter(
            DailyStat.date == week_ago,
            DailyStat.roll_no.in_(roll_nos),
        )
    }

    return [
        round(today_stats.get(r, 0.0) - prev_stats.get(r, 0.0), 2)
        for r in roll_nos
    ]


# ---------------------------------------------------------------------------
# Progress Tiers (NumPy Percentile)
# ---------------------------------------------------------------------------
def assign_progress_tiers(scores: np.ndarray) -> list[str]:
    """
    Dynamically bucket students into three tiers using cohort
    percentiles:

    - **Top 20 %** (≥ 80th percentile) → 🏆 Outperforming
    - **Middle 60 %** → 📈 Average
    - **Bottom 20 %** (≤ 20th percentile) → ⚠️ Needs Attention
    """
    if len(scores) == 0:
        return []

    arr = np.asarray(scores, dtype=float)
    p20, p80 = np.percentile(arr, [20, 80])

    tiers: list[str] = []
    for v in arr:
        if v >= p80:
            tiers.append(TIER_TOP)
        elif v <= p20:
            tiers.append(TIER_LOW)
        else:
            tiers.append(TIER_MID)

    return tiers


# ---------------------------------------------------------------------------
# Platform Affinity
# ---------------------------------------------------------------------------
def classify_platform_affinity(row: pd.Series) -> str:
    """
    Classify each student's platform usage pattern.

    - **LeetCode Specialist**: LC dominates (>70 % of composite)
    - **HackerRank Specialist**: HR dominates (>70 % of composite)
    - **Balanced**: neither dominates
    - **Dormant**: zero activity on both platforms
    """
    lc = float(row.get("lc_total", 0))
    hr = float(row.get("hr_score", 0))
    total = lc + hr

    if total == 0:
        return "Dormant"

    lc_ratio = lc / total
    if lc_ratio > 0.7:
        return "LeetCode Specialist"
    if lc_ratio < 0.3:
        return "HackerRank Specialist"
    return "Balanced"


# ---------------------------------------------------------------------------
# At-Risk Identification
# ---------------------------------------------------------------------------
def get_at_risk(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return students who are at risk:

    - ``velocity_7d == 0`` (stagnant)  **OR**
    - ``total_score < AT_RISK_THRESHOLD``

    A ``risk_reason`` column distinguishes API failure suspects
    from genuinely inactive students.
    """
    if df.empty:
        return df

    mask = (df["velocity_7d"] == 0) | (df["total_score"] < AT_RISK_THRESHOLD)
    at_risk = df[mask].copy()

    def _reason(row: pd.Series) -> str:
        reasons = []
        # Use pd.notna() instead of 'is not None' for Pandas DataFrames
        if row["total_score"] == 0 and pd.notna(row["lc_handle"]):
            reasons.append("Possible API failure")
        if row["velocity_7d"] == 0 and row["total_score"] > 0:
            reasons.append("Stagnant (0 progress in 7 days)")
        if row["total_score"] < AT_RISK_THRESHOLD:
            reasons.append(f"Low total ({row['total_score']})")
        return "; ".join(reasons) if reasons else "Inactive"

    at_risk["risk_reason"] = at_risk.apply(_reason, axis=1)
    return at_risk.reset_index(drop=True)


def assign_status_and_sort(df: pd.DataFrame) -> pd.DataFrame:
    """
    This contains the repaired lines from the bottom of your snippet.
    """
    # Apply the categorize_student function (make sure it's defined elsewhere)
    df["status"] = df.apply(categorize_student, axis=1) 
    
    # Fixed the cut-off 'ascen' parameter
    return df.sort_values("composite_score", ascending=False)