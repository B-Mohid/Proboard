"""
Shared pytest fixtures for PROBOARD test suite.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import Base, DailyStat, Student


# ---------------------------------------------------------------------------
# In-Memory SQLite Session
# ---------------------------------------------------------------------------
@pytest.fixture()
def db_session():
    """Yield a fresh in-memory SQLAlchemy session per test."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# Sample Cleaned DataFrame
# ---------------------------------------------------------------------------
@pytest.fixture()
def sample_clean_df() -> pd.DataFrame:
    """Minimal cleaned DataFrame matching cleaner output schema."""
    return pd.DataFrame(
        {
            "roll_no": ["23F21A0566", "23F21A0567", "23F21A0568"],
            "name": ["Alice", "Bob", "Charlie"],
            "basics_score": [5, 3, 0],
            "lc_handle": ["alice_lc", "bob_lc", None],
            "hr_handle": ["alice_hr", None, None],
            "email": [
                "23f21a0566@gatesit.ac.in",
                "23f21a0567@gatesit.ac.in",
                "23f21a0568@gatesit.ac.in",
            ],
        }
    )


# ---------------------------------------------------------------------------
# Seed Students & Stats into DB
# ---------------------------------------------------------------------------
@pytest.fixture()
def seeded_session(db_session, sample_clean_df):
    """DB session pre-loaded with students and two days of stats."""
    today = date.today()
    week_ago = today - timedelta(days=7)

    for _, row in sample_clean_df.iterrows():
        db_session.add(
            Student(
                roll_no=row["roll_no"],
                name=row["name"],
                lc_handle=row["lc_handle"],
                hr_handle=row["hr_handle"],
                email=row["email"],
                basics_score=int(row["basics_score"]),
            )
        )
    db_session.flush()

    # Week-ago stats
    stats_prev = [
        ("23F21A0566", 5, 3, 1, 9, 2, 10.0, 19.0),
        ("23F21A0567", 2, 1, 0, 3, 0, 0.0, 3.0),
        ("23F21A0568", 0, 0, 0, 0, 0, 0.0, 0.0),
    ]
    for roll, e, m, h, t, b, hr, ts in stats_prev:
        db_session.add(
            DailyStat(
                date=week_ago,
                roll_no=roll,
                lc_easy=e, lc_medium=m, lc_hard=h, lc_total=t,
                hr_badges=b, hr_score=hr, total_score=ts,
            )
        )

    # Today's stats (Alice improved, Bob same, Charlie still 0)
    stats_today = [
        ("23F21A0566", 8, 5, 2, 15, 3, 15.0, 30.0),
        ("23F21A0567", 2, 1, 0, 3, 0, 0.0, 3.0),
        ("23F21A0568", 0, 0, 0, 0, 0, 0.0, 0.0),
    ]
    for roll, e, m, h, t, b, hr, ts in stats_today:
        db_session.add(
            DailyStat(
                date=today,
                roll_no=roll,
                lc_easy=e, lc_medium=m, lc_hard=h, lc_total=t,
                hr_badges=b, hr_score=hr, total_score=ts,
            )
        )

    db_session.commit()
    yield db_session
