"""
Tests for analytics.py — percentile tiers, composite scoring,
velocity tracking, platform affinity, and at-risk identification.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from analytics import (
    TIER_LOW,
    TIER_MID,
    TIER_TOP,
    assign_progress_tiers,
    build_leaderboard,
    classify_platform_affinity,
    compute_composite_score,
    compute_velocity_7d,
    get_at_risk,
)


# ===================================================================
# Composite Score
# ===================================================================
class TestCompositeScore:
    def test_basic(self):
        lc = pd.Series([10, 0, 5])
        hr = pd.Series([20.0, 0.0, 10.0])
        result = compute_composite_score(lc, hr)
        # HR_WEIGHT = 0.5 by default
        assert result.iloc[0] == 20.0   # 10 + 20*0.5
        assert result.iloc[1] == 0.0
        assert result.iloc[2] == 10.0   # 5 + 10*0.5

    def test_zero_inputs(self):
        lc = pd.Series([0])
        hr = pd.Series([0.0])
        assert compute_composite_score(lc, hr).iloc[0] == 0.0


# ===================================================================
# Progress Tiers (NumPy Percentile)
# ===================================================================
class TestProgressTiers:
    def test_sorted_distribution(self):
        scores = np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        tiers = assign_progress_tiers(scores)
        assert tiers[0] == TIER_LOW      # 0 → bottom 20%
        assert tiers[-1] == TIER_TOP     # 10 → top 20%
        assert tiers[5] == TIER_MID      # 5 → middle

    def test_all_same_scores(self):
        scores = np.array([5, 5, 5, 5, 5])
        tiers = assign_progress_tiers(scores)
        # All equal → all at p20 AND p80 → should be TOP (>= p80)
        assert all(t == TIER_TOP for t in tiers)

    def test_empty_array(self):
        assert assign_progress_tiers(np.array([])) == []

    def test_single_value(self):
        tiers = assign_progress_tiers(np.array([42]))
        assert len(tiers) == 1

    def test_two_values(self):
        tiers = assign_progress_tiers(np.array([0, 100]))
        assert tiers[0] == TIER_LOW
        assert tiers[1] == TIER_TOP


# ===================================================================
# Platform Affinity
# ===================================================================
class TestPlatformAffinity:
    def test_leetcode_specialist(self):
        row = pd.Series({"lc_total": 100, "hr_score": 0})
        assert classify_platform_affinity(row) == "LeetCode Specialist"

    def test_hackerrank_specialist(self):
        row = pd.Series({"lc_total": 5, "hr_score": 95})
        assert classify_platform_affinity(row) == "HackerRank Specialist"

    def test_balanced(self):
        row = pd.Series({"lc_total": 50, "hr_score": 50})
        assert classify_platform_affinity(row) == "Balanced"

    def test_dormant(self):
        row = pd.Series({"lc_total": 0, "hr_score": 0})
        assert classify_platform_affinity(row) == "Dormant"

    def test_edge_70_percent(self):
        # Exactly 70/30 split → lc_ratio = 0.7 → exactly at boundary
        row = pd.Series({"lc_total": 70, "hr_score": 30})
        result = classify_platform_affinity(row)
        assert result in ("LeetCode Specialist", "Balanced")


# ===================================================================
# Velocity 7D
# ===================================================================
class TestVelocity7d:
    def test_positive_velocity(self, seeded_session):
        """Alice gained 11 points (30 - 19)."""
        v = compute_velocity_7d(seeded_session, "23F21A0566")
        assert v == 11.0

    def test_zero_velocity(self, seeded_session):
        """Bob didn't change (3 - 3)."""
        v = compute_velocity_7d(seeded_session, "23F21A0567")
        assert v == 0.0

    def test_missing_student(self, seeded_session):
        """Non-existent student → 0."""
        v = compute_velocity_7d(seeded_session, "NONEXISTENT")
        assert v == 0.0


# ===================================================================
# Build Leaderboard
# ===================================================================
class TestBuildLeaderboard:
    def test_returns_all_students(self, seeded_session):
        lb = build_leaderboard(seeded_session)
        assert len(lb) == 3

    def test_has_computed_columns(self, seeded_session):
        lb = build_leaderboard(seeded_session)
        for col in ["composite_score", "velocity_7d", "progress_tier", "platform_affinity"]:
            assert col in lb.columns, f"Missing column: {col}"

    def test_sorted_by_composite(self, seeded_session):
        lb = build_leaderboard(seeded_session)
        scores = lb["composite_score"].tolist()
        assert scores == sorted(scores, reverse=True)


# ===================================================================
# At-Risk Identification
# ===================================================================
class TestGetAtRisk:
    def test_identifies_at_risk(self, seeded_session):
        lb = build_leaderboard(seeded_session)
        at_risk = get_at_risk(lb)
        # Bob (velocity=0, total=3) and Charlie (total=0) should be at risk
        assert len(at_risk) >= 2
        assert "risk_reason" in at_risk.columns

    def test_empty_df(self):
        empty = pd.DataFrame()
        result = get_at_risk(empty)
        assert result.empty

    def test_risk_reason_populated(self, seeded_session):
        lb = build_leaderboard(seeded_session)
        at_risk = get_at_risk(lb)
        assert all(at_risk["risk_reason"].str.len() > 0)
