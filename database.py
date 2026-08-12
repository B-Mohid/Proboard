"""
PROBOARD — Database Engine & Session Management
=================================================
Provides engine creation, scoped sessions, schema bootstrap,
and bulk-upsert helpers for both `students` and `daily_stats`.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Sequence

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from config import DATABASE_URL
from models import Base, DailyStat, Student

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons (lazy-init)
# ---------------------------------------------------------------------------
_engine: Engine | None = None
_SessionFactory: sessionmaker | None = None


def get_engine() -> Engine:
    """
    Return (and cache) the SQLAlchemy engine.

    Uses ``check_same_thread=False`` so SQLite works safely with
    Streamlit's threaded execution model.
    """
    global _engine
    if _engine is None:
        _engine = create_engine(
            DATABASE_URL,
            connect_args={"check_same_thread": False},
            echo=False,
            pool_pre_ping=True,
        )
    return _engine


def get_session() -> Session:
    """Return a new SQLAlchemy session bound to the cached engine."""
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionFactory()


def init_db() -> None:
    """
    Bootstrap the database: create all tables defined in ``models.py``
    if they don't already exist.  Safe to call on every startup.
    """
    engine = get_engine()
    Base.metadata.create_all(engine)
    tables = inspect(engine).get_table_names()
    logger.info("Database initialised — tables: %s", tables)


# ---------------------------------------------------------------------------
# Bulk Upsert — Students
# ---------------------------------------------------------------------------
def bulk_upsert_students(
    session: Session,
    students: Sequence[dict[str, Any]],
) -> int:
    """
    Insert or update student records.

    Parameters
    ----------
    session : Session
        Active SQLAlchemy session.
    students : list[dict]
        Each dict must contain at least ``roll_no`` and ``name``.
        Optional keys: ``lc_handle``, ``hr_handle``, ``email``,
        ``basics_score``.

    Returns
    -------
    int
        Number of rows upserted.
    """
    if not students:
        return 0

    upserted = 0
    for row in students:
        roll_no = str(row["roll_no"]).strip()
        existing: Student | None = session.get(Student, roll_no)

        if existing is None:
            student = Student(
                roll_no=roll_no,
                name=row.get("name", ""),
                lc_handle=row.get("lc_handle"),
                hr_handle=row.get("hr_handle"),
                email=row.get("email"),
                basics_score=int(row.get("basics_score", 0)),
            )
            session.add(student)
        else:
            # Update mutable fields only when new data is non-empty
            existing.name = row.get("name", existing.name)
            if row.get("lc_handle") is not None:
                existing.lc_handle = row["lc_handle"]
            if row.get("hr_handle") is not None:
                existing.hr_handle = row["hr_handle"]
            if row.get("email") is not None:
                existing.email = row["email"]
            existing.basics_score = int(
                row.get("basics_score", existing.basics_score)
            )

        upserted += 1

    session.commit()
    logger.info("Upserted %d student record(s).", upserted)
    return upserted


# ---------------------------------------------------------------------------
# Bulk Upsert — Daily Stats
# ---------------------------------------------------------------------------
def bulk_upsert_daily_stats(
    session: Session,
    stats: Sequence[dict[str, Any]],
    snapshot_date: date | None = None,
) -> int:
    """
    Insert or update daily performance snapshots.

    Uses the ``UNIQUE(date, roll_no)`` constraint to decide
    insert vs. update, preventing duplicate rows per day.

    Parameters
    ----------
    session : Session
        Active SQLAlchemy session.
    stats : list[dict]
        Each dict must contain ``roll_no``.  Optional keys:
        ``lc_easy``, ``lc_medium``, ``lc_hard``, ``lc_total``,
        ``hr_badges``, ``hr_score``, ``total_score``.
    snapshot_date : date, optional
        Defaults to ``date.today()``.

    Returns
    -------
    int
        Number of rows upserted.
    """
    if not stats:
        return 0

    today = snapshot_date or date.today()
    upserted = 0

    for row in stats:
        roll_no = str(row["roll_no"]).strip()

        existing: DailyStat | None = (
            session.query(DailyStat)
            .filter_by(date=today, roll_no=roll_no)
            .first()
        )

        if existing is None:
            stat = DailyStat(
                date=today,
                roll_no=roll_no,
                lc_easy=int(row.get("lc_easy", 0)),
                lc_medium=int(row.get("lc_medium", 0)),
                lc_hard=int(row.get("lc_hard", 0)),
                lc_total=int(row.get("lc_total", 0)),
                hr_badges=int(row.get("hr_badges", 0)),
                hr_score=float(row.get("hr_score", 0.0)),
                total_score=float(row.get("total_score", 0.0)),
            )
            session.add(stat)
        else:
            existing.lc_easy = int(row.get("lc_easy", existing.lc_easy))
            existing.lc_medium = int(row.get("lc_medium", existing.lc_medium))
            existing.lc_hard = int(row.get("lc_hard", existing.lc_hard))
            existing.lc_total = int(row.get("lc_total", existing.lc_total))
            existing.hr_badges = int(row.get("hr_badges", existing.hr_badges))
            existing.hr_score = float(row.get("hr_score", existing.hr_score))
            existing.total_score = float(
                row.get("total_score", existing.total_score)
            )

        upserted += 1

    session.commit()
    logger.info("Upserted %d daily-stat row(s) for %s.", upserted, today)
    return upserted
