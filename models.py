"""
PROBOARD — SQLAlchemy ORM Models
=================================
Defines the `students` and `daily_stats` tables with full constraints,
relationships, and repr helpers.
"""

from datetime import date, datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


# ---------------------------------------------------------------------------
# Declarative Base
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    """Shared declarative base for all PROBOARD models."""
    pass


# ---------------------------------------------------------------------------
# Students Table
# ---------------------------------------------------------------------------
class Student(Base):
    """
    Canonical student record.

    One row per student, keyed by college roll number.
    Handles and email are derived during the cleaning phase.
    """

    __tablename__ = "students"

    roll_no: str = Column(String(20), primary_key=True, nullable=False)
    name: str = Column(String(120), nullable=False)
    lc_handle: str | None = Column(String(80), nullable=True)
    hr_handle: str | None = Column(String(80), nullable=True)
    email: str | None = Column(String(120), nullable=True)
    basics_score: int = Column(Integer, default=0, nullable=False)

    # Relationship — one student → many daily snapshots
    daily_stats = relationship(
        "DailyStat",
        back_populates="student",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    # Relationship — one student → many email logs
    email_logs = relationship(
        "EmailLog",
        back_populates="student",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return (
            f"<Student(roll_no={self.roll_no!r}, name={self.name!r}, "
            f"lc={self.lc_handle!r}, hr={self.hr_handle!r})>"
        )


# ---------------------------------------------------------------------------
# Daily Stats Table
# ---------------------------------------------------------------------------
class DailyStat(Base):
    """
    Daily performance snapshot per student.

    The UNIQUE(date, roll_no) constraint prevents duplicate
    entries for the same student on the same day, enabling
    safe bulk upserts.
    """

    __tablename__ = "daily_stats"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, default=date.today)
    roll_no: str = Column(
        String(20),
        ForeignKey("students.roll_no", ondelete="CASCADE"),
        nullable=False,
    )

    # LeetCode granular counts
    lc_easy: int = Column(Integer, default=0, nullable=False)
    lc_medium: int = Column(Integer, default=0, nullable=False)
    lc_hard: int = Column(Integer, default=0, nullable=False)
    lc_total: int = Column(Integer, default=0, nullable=False)

    # HackerRank metrics
    hr_badges: int = Column(Integer, default=0, nullable=False)
    hr_score: float = Column(Float, default=0.0, nullable=False)

    # Composite
    total_score: float = Column(Float, default=0.0, nullable=False)

    # Table-level constraints
    __table_args__ = (
        UniqueConstraint("date", "roll_no", name="uq_date_roll"),
    )

    # Relationship back-reference
    student = relationship("Student", back_populates="daily_stats")

    def __repr__(self) -> str:
        return (
            f"<DailyStat(date={self.date}, roll_no={self.roll_no!r}, "
            f"lc_total={self.lc_total}, hr_score={self.hr_score}, "
            f"total={self.total_score})>"
        )


# ---------------------------------------------------------------------------
# Email Log — Idempotency for Notifier
# ---------------------------------------------------------------------------
class EmailLog(Base):
    """
    Tracks alert emails sent per student per day.

    The UNIQUE(date, roll_no) constraint guarantees that the
    notifier daemon never sends duplicate emails on the same day.
    """

    __tablename__ = "email_log"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, default=date.today)
    roll_no: str = Column(
        String(20),
        ForeignKey("students.roll_no", ondelete="CASCADE"),
        nullable=False,
    )
    sent_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("date", "roll_no", name="uq_email_date_roll"),
    )

    student = relationship("Student", back_populates="email_logs")

    def __repr__(self) -> str:
        return (
            f"<EmailLog(date={self.date}, roll_no={self.roll_no!r}, "
            f"sent_at={self.sent_at})>"
        )
