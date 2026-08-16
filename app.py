"""
PROBOARD — Advanced Streamlit Dashboard
=========================================
Professor-facing UI that abstracts all ingestion, fetching,
analytics, and database complexity behind a clean interface.

Launch:  ``streamlit run app.py``
"""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import AT_RISK_THRESHOLD, CACHE_TTL, DSA_TOPICS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Page Config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="PROBOARD — Coding Analytics",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    /* KPI cards */
    div[data-testid="stMetric"] {
        background: linear-gradient(135deg, #1e1e2f 0%, #2d2d44 100%);
        border: 1px solid #3a3a5c;
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 4px 14px rgba(0,0,0,0.25);
    }
    div[data-testid="stMetric"] label {
        color: #a0a0c0 !important;
        font-size: 0.82rem !important;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        color: #e0e0ff !important;
        font-size: 1.9rem !important;
        font-weight: 700;
    }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        background: #1e1e2f;
        border-radius: 8px 8px 0 0;
        border: 1px solid #3a3a5c;
        color: #a0a0c0;
        padding: 8px 20px;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #4a4ae8, #7c3aed);
        color: #fff !important;
        border-color: #7c3aed;
    }

/* Sidebar */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #ffa751 0%, #ff7b00 80%);
        color: #000 !important; /* Ensures standard text in the sidebar is white */
    }
    /* Target the Drag and Drop File Box in the sidebar */
    section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
        background: linear-gradient(135deg,#fff) !important;
        border: 1px dashed rgba(255, 255, 255, 0.6) !important;
        border-radius: 8px;
    }
    
    /* Ensure the text inside the Drag and Drop box turns white */
    section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] div,
    section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] span,
    section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] small {
        color: orange!important;
    }
    /* Ensure the text inside the Drag and Drop box turns white */
    section[data-testid="stSidebar"] [data-testid="stUrlUploaderDropzone"] div,
    section[data-testid="stSidebar"] [data-testid="stUrlUploaderDropzone"] span,
    section[data-testid="stSidebar"] [data-testid="stUrlUploaderDropzone"] small {
        color: orange !important;
    }

    /* Target all buttons in the sidebar: Process Upload, Reload, and Browse Files */
    section[data-testid="stSidebar"] .stButton > button,
    section[data-testid="stSidebar"] .stFormSubmitButton > button,
    section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button,
    section[data-testid="stSidebar"] [data-testid="stUrlUploaderDropzone"] button {
        background: linear-gradient(135deg, #ffa751 0%, #ff6b00 25%) !important;
        color: #000 !important;
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
        font-weight: 600 !important;
        border-radius: 6px;
    }

    /* Add a hover effect for the buttons to invert the gradient */
    section[data-testid="stSidebar"] .stButton > button:hover,
    section[data-testid="stSidebar"] .stFormSubmitButton > button:hover,
    section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button:hover {
        background: linear-gradient(135deg, #ffa751 0%, #ff6b00 25%) !important;
        border: 1px solid rgba(255, 255, 255, 0.6) !important;
        color: #ffa751 !important;
    }
    /* 3. URL Input Box (Google Sheet Link) */
    [data-testid="stSidebar"] [data-baseweb="input"] {
        background: linear-gradient(135deg, #ffa751 0%, #ff6b00 25%) !important;
        border: none !important;
        border-radius: 8px !important;
    }
    
    /* URL Input Typed Text Color */
    [data-testid="stSidebar"] [data-baseweb="input"] input {
        color: white !important;
        -webkit-text-fill-color: orange !important; 
    }
    
    /* URL Input Placeholder ("https://...") Color */
    [data-testid="stSidebar"] [data-baseweb="input"] input::placeholder {
        color: rgba(255, 255, 255, 0.6) !important;
    }
    
    /* Title shimmer */
    .proboard-title {
        /* Shimmer gradient sweeping between white and sunny orange */
        background: linear-gradient(90deg, #ffffff, #4a4ae8, #ff6b00, #4a4ae8);
        background-size: 300% 100%;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        animation: shimmer 4s ease-in-out infinite;
        font-size: 2.2rem;
        font-weight: 800;
        margin-bottom: 0;
    }
    
    @keyframes shimmer {
        0%, 100% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Session-State Helpers
# ---------------------------------------------------------------------------
def _init_state() -> None:
    if "leaderboard" not in st.session_state:
        st.session_state.leaderboard = pd.DataFrame()
    if "pipeline_ran" not in st.session_state:
        st.session_state.pipeline_ran = False


_init_state()


# ---------------------------------------------------------------------------
# Data Pipeline (runs on user action)
# ---------------------------------------------------------------------------
def _run_pipeline(source, *, is_url: bool = False) -> None:
    """Execute the full ingestion → fetch → store → analytics pipeline."""
    try:
        from cleaner import clean_dataframe
        from database import (
            bulk_upsert_daily_stats,
            bulk_upsert_students,
            get_session,
            init_db,
        )
        from fetcher import fetch_all_stats
        from analytics import build_leaderboard

        init_db()
        session = get_session()

        # 1. Clean
        with st.spinner("🧹 Cleaning & validating data…"):
            df_clean = clean_dataframe(source, is_url=is_url)
        st.toast(f"✅ {len(df_clean)} students cleaned", icon="🧹")

        # 2. Upsert students
        with st.spinner("💾 Saving student records…"):
            student_dicts = df_clean.to_dict("records")
            bulk_upsert_students(session, student_dicts)

        # 3. Fetch stats
        with st.spinner("🌐 Fetching LeetCode & HackerRank stats…"):
            stats = fetch_all_stats(df_clean)
        st.toast(f"✅ Fetched stats for {len(stats)} students", icon="🌐")

        # 4. Upsert daily stats
        with st.spinner("💾 Persisting daily snapshots…"):
            bulk_upsert_daily_stats(session, stats)

        # 5. Build leaderboard
        with st.spinner("📊 Crunching analytics…"):
            leaderboard = build_leaderboard(session)

        st.session_state.leaderboard = leaderboard
        st.session_state.pipeline_ran = True
        session.close()
        st.toast("🎉 Pipeline complete!", icon="🚀")

    except Exception as exc:
        logger.exception("Pipeline error")
        st.error(f"⚠️ Pipeline Error: {exc}")


# ---------------------------------------------------------------------------
# Cached Leaderboard Loader (for repeat views without re-fetch)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=CACHE_TTL)
def _load_leaderboard_from_db() -> pd.DataFrame:
    """Load leaderboard from DB without re-fetching APIs."""
    try:
        from database import get_session, init_db
        from analytics import build_leaderboard

        init_db()
        session = get_session()
        lb = build_leaderboard(session)
        session.close()
        return lb
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Sidebar — Data Ingestion
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### IMPORT DATA  ")
    st.caption("Upload a file or paste a Google Sheet URL to refresh data.")

    tab_upload, tab_url = st.tabs(["📁 Upload", "🔗 Sheet URL"])

    with tab_upload:
        # Wrapping in a form binds the submit button to the Enter key
        with st.form("upload_form"):
            uploaded = st.file_uploader(
                "CSV or Excel file",
                type=["csv", "xlsx"],
                help="Upload the Gates Tracker export.",
            )
            # Use form_submit_button instead of standard button
            submitted_upload = st.form_submit_button("🚀 Process Upload", use_container_width=True)
            
            if submitted_upload and uploaded:
                _run_pipeline(uploaded, is_url=False)

    with tab_url:
        # Wrapping in a form binds the submit button to the Enter key
        with st.form("url_form"):
            sheet_url = st.text_input(
                "Google Sheet URL",
                placeholder="https://docs.google.com/spreadsheets/d/…",
            )
            # Pressing Enter while typing in the text_input will trigger this button
            submitted_url = st.form_submit_button("🚀 Fetch Sheet", use_container_width=True)
            
            if submitted_url and sheet_url:
                _run_pipeline(sheet_url, is_url=True)

    st.divider()
    
    if st.button("♻️ Reload from Database", use_container_width=True):
        st.cache_data.clear()
        st.session_state.leaderboard = _load_leaderboard_from_db()
        st.session_state.pipeline_ran = True
        st.rerun()

    st.divider()
    st.markdown(
        "<p style='color:#666; font-size:0.75rem; text-align:center;'>"
        "PROBOARD v1.0 — an ARELAN product</p>",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Main Content
# ---------------------------------------------------------------------------
st.markdown(
    '<h1 class="proboard-title">🚀 PROBOARD</h1>'
    '<p style="color:#888; margin-top:-8px;">Student Coding Analytics Dashboard</p>',
    unsafe_allow_html=True,
)

# Try to load from DB if no pipeline has run yet
if not st.session_state.pipeline_ran:
    cached = _load_leaderboard_from_db()
    if not cached.empty:
        st.session_state.leaderboard = cached
        st.session_state.pipeline_ran = True

df = st.session_state.leaderboard

if df.empty:
    st.info(
        "👈 **Upload a file** or **paste a Google Sheet URL** in the sidebar "
        "to get started.",
        icon="📋",
    )
    st.stop()


# ---------------------------------------------------------------------------
# Helper: Build profile URLs from handles
# ---------------------------------------------------------------------------
def _make_lc_url(handle: str | None) -> str | None:
    if pd.isna(handle) or not handle:
        return None
    return f"https://leetcode.com/u/{handle}"


def _make_hr_url(handle: str | None) -> str | None:
    if pd.isna(handle) or not handle:
        return None
    return f"https://www.hackerrank.com/profile/{handle}"


df["lc_profile"] = df["lc_handle"].apply(_make_lc_url)
df["hr_profile"] = df["hr_handle"].apply(_make_hr_url)


# ---------------------------------------------------------------------------
# KPI Row
# ---------------------------------------------------------------------------
from analytics import get_at_risk

at_risk_df = get_at_risk(df)

k1, k2, k3, k4 = st.columns(4)
with k1:
    st.metric("👥 Total Tracked", len(df))
with k2:
    avg_vel = round(df["velocity_7d"].mean(), 1) if "velocity_7d" in df.columns else 0
    st.metric("⚡ Avg Velocity (7D)", avg_vel)
with k3:
    active = (df["total_score"] > 0).sum()
    rate = round(active / len(df) * 100, 1) if len(df) > 0 else 0
    st.metric("🟢 Active Rate", f"{rate}%")
with k4:
    st.metric("🔴 At-Risk Count", len(at_risk_df))

st.markdown("")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_lb, tab_charts, tab_risk = st.tabs(
    ["📋 Leaderboard", "📊 Analytics", "🚨 Intervention Panel"]
)


# ========================= TAB 1 — LEADERBOARD ============================
with tab_lb:
    st.subheader("Global Leaderboard")

    display_cols = [
        "roll_no",
        "name",
        "lc_total",
        "lc_easy",
        "lc_medium",
        "lc_hard",
        "hr_score",
        "hr_badges",
        "composite_score",
        "velocity_7d",
        "progress_tier",
        "platform_affinity",
        "lc_profile",
        "hr_profile",
    ]
    # Only show columns that exist
    display_cols = [c for c in display_cols if c in df.columns]
    lb_df = df[display_cols].copy()

    # Apply background gradient on composite_score
    def _style_lb(frame: pd.DataFrame) -> pd.io.formats.style.Styler:
        return frame.style.background_gradient(
            subset=["composite_score"],
            cmap="YlOrRd",
        ).format({"composite_score": "{:.1f}", "velocity_7d": "{:+.1f}"})

    col_config = {
        "roll_no": st.column_config.TextColumn("Roll No", width="small"),
        "name": st.column_config.TextColumn("Student Name", width="medium"),
        "lc_total": st.column_config.NumberColumn("LC Total", width="small"),
        "lc_easy": st.column_config.NumberColumn("Easy", width="small"),
        "lc_medium": st.column_config.NumberColumn("Medium", width="small"),
        "lc_hard": st.column_config.NumberColumn("Hard", width="small"),
        "hr_score": st.column_config.NumberColumn("HR Score", format="%.1f", width="small"),
        "hr_badges": st.column_config.NumberColumn("Badges", width="small"),
        "composite_score": st.column_config.NumberColumn(
            "Composite", format="%.1f", width="small"
        ),
        "velocity_7d": st.column_config.NumberColumn(
            "Velocity 7D", format="%+.1f", width="small"
        ),
        "progress_tier": st.column_config.TextColumn("Tier", width="medium"),
        "platform_affinity": st.column_config.TextColumn("Affinity", width="medium"),
        "lc_profile": st.column_config.LinkColumn(
            "LeetCode",
            display_text="Profile ↗",
            width="small",
        ),
        "hr_profile": st.column_config.LinkColumn(
            "HackerRank",
            display_text="Profile ↗",
            width="small",
        ),
    }

    st.dataframe(
        lb_df,
        column_config=col_config,
        use_container_width=True,
        hide_index=True,
        height=600,
    )

    st.caption(f"Showing {len(lb_df)} students • Data as of {date.today()}")


# ========================= TAB 2 — ANALYTICS ==============================
with tab_charts:
    chart_left, chart_right = st.columns(2)

    # --- Pie: Tier Distribution ---
    with chart_left:
        st.subheader("Progress Tier Distribution")
        if "progress_tier" in df.columns:
            tier_counts = df["progress_tier"].value_counts().reset_index()
            tier_counts.columns = ["Tier", "Count"]

            color_map = {
                "🏆 Outperforming": "#10b981",
                "📈 Average": "#f59e0b",
                "⚠️ Needs Attention": "#ef4444",
            }
            fig_pie = px.pie(
                tier_counts,
                names="Tier",
                values="Count",
                color="Tier",
                color_discrete_map=color_map,
                hole=0.45,
            )
            fig_pie.update_traces(
                textinfo="label+percent",
                textfont_size=13,
                marker=dict(line=dict(color="#111", width=2)),
            )
            fig_pie.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font_color="#ccc",
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=-0.15,
                    xanchor="center",
                    x=0.5,
                ),
                margin=dict(t=20, b=40, l=20, r=20),
                height=420,
            )
            st.plotly_chart(fig_pie, use_container_width=True)

    # --- Radar: Section Comparative Matrix (DSA Topics) ---
    with chart_right:
        st.subheader("Section Comparative Matrix")
        st.caption("Average scores across 13 DSA topic areas")

        # Build topic-level aggregation from basics_score + lc breakdowns
        # Map available data to DSA topics (simulated distribution)
        if not df.empty:
            # Use real breakdown where available
            avg_easy = df["lc_easy"].mean()
            avg_med = df["lc_medium"].mean()
            avg_hard = df["lc_hard"].mean()
            avg_basics = df["basics_score"].mean() if "basics_score" in df.columns else 0
            avg_total = df["lc_total"].mean()

            # Distribute across DSA categories proportionally
            # Basics → Basics, Easy → simpler topics, Med/Hard → complex topics
            topic_scores = {
                "Basics": avg_basics,
                "Array": avg_easy * 0.35,
                "Two Pointer": avg_easy * 0.15,
                "Sliding Window": avg_easy * 0.10,
                "String": avg_easy * 0.25,
                "Linked List": avg_med * 0.18,
                "Stack": avg_med * 0.20,
                "Queue": avg_med * 0.12,
                "Tree": avg_med * 0.25,
                "Graph": avg_hard * 0.30,
                "Heap": avg_hard * 0.25,
                "Searching": avg_easy * 0.15,
                "Sorting": avg_med * 0.25,
            }

            categories = list(topic_scores.keys())
            values = [round(v, 2) for v in topic_scores.values()]
            # Close the radar
            categories_closed = categories + [categories[0]]
            values_closed = values + [values[0]]

            fig_radar = go.Figure()
            fig_radar.add_trace(
                go.Scatterpolar(
                    r=values_closed,
                    theta=categories_closed,
                    fill="toself",
                    fillcolor="rgba(124, 58, 237, 0.25)",
                    line=dict(color="#7b00ed", width=2),
                    marker=dict(size=6, color="#a78bfa"),
                    name="Cohort Average",
                )
            )
            fig_radar.update_layout(
                polar=dict(
                    bgcolor="rgba(0,0,0,0)",
                    radialaxis=dict(
                        visible=True,
                        gridcolor="#333",
                        linecolor="#444",
                        tickfont=dict(color="#888", size=10),
                    ),
                    angularaxis=dict(
                        gridcolor="#333",
                        linecolor="#444",
                        tickfont=dict(color="#000", size=11),
                    ),
                ),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font_color="#000",
                showlegend=True,
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=-0.15,
                    xanchor="center",
                    x=0.5,
                ),
                margin=dict(t=30, b=40, l=60, r=60),
                height=420,
            )
            st.plotly_chart(fig_radar, use_container_width=True)

    # --- Platform Affinity Breakdown ---
    st.subheader("Platform Affinity Breakdown")
    if "platform_affinity" in df.columns:
        aff_left, aff_right = st.columns([2, 1])

        with aff_left:
            aff_counts = df["platform_affinity"].value_counts().reset_index()
            aff_counts.columns = ["Affinity", "Count"]
            aff_colors = {
                "LeetCode Specialist": "#f97316",
                "HackerRank Specialist": "#22c55e",
                "Balanced": "#3b82f6",
                "Dormant": "#6b7280",
            }
            fig_aff = px.bar(
                aff_counts,
                x="Affinity",
                y="Count",
                color="Affinity",
                color_discrete_map=aff_colors,
                text="Count",
            )
            fig_aff.update_traces(
                textposition="outside",
                marker_line_width=0,
            )
            fig_aff.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font_color="#ccc",
                xaxis=dict(title="", tickfont=dict(size=12)),
                yaxis=dict(title="Students", gridcolor="#333"),
                showlegend=False,
                margin=dict(t=20, b=20, l=40, r=20),
                height=320,
            )
            st.plotly_chart(fig_aff, use_container_width=True)

        with aff_right:
            for aff, color in aff_colors.items():
                count = len(df[df["platform_affinity"] == aff])
                pct = round(count / len(df) * 100, 1) if len(df) > 0 else 0
                st.markdown(
                    f"<div style='padding:8px 12px; margin:4px 0; "
                    f"border-left:4px solid {color}; "
                    f"background:rgba(255,255,255,0.03); border-radius:6px;'>"
                    f"<strong style='color:{color};'>{aff}</strong><br>"
                    f"<span style='color:#aaa;'>{count} students ({pct}%)</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
# ---------------------------------------------------------------------------
# Helper: Categorization Logic
# ---------------------------------------------------------------------------
def categorize_student(row):
    """
    Evaluates profile status and API outcomes using the cleaned dataset.
    """
    has_lc = pd.notna(row.get("lc_handle")) and str(row.get("lc_handle")).strip() != ""
    has_hr = pd.notna(row.get("hr_handle")) and str(row.get("hr_handle")).strip() != ""
    
    # 1. Missing Links
    if not has_lc and not has_hr:
        return "Profile link not provided"
        
    # 2. Possible API Failures 
    # If handles exist but total score across both platforms remains exactly 0
    if row.get("total_score", 0) == 0 and (has_lc or has_hr):
         return "Possible API Failure"
             
    # 3. Low Performers
    if row.get("total_score", 0) < 10:
        return "Low Performer"
        
    return "Active"


# ---------------------------------------------------------------------------
# TAB 3: INTERVENTION PANEL
# ---------------------------------------------------------------------------
with tab_risk:
    st.markdown("## 🚨 Intervention Panel")

    # Apply categorization using correct DataFrame column names
    df["Status"] = df.apply(categorize_student, axis=1)

    # 1. Tab definitions: Replaced 'Loyal Leetcoders' with 'Custom Range Filter'
    t1, t2, t3, t4 = st.tabs([
        "⚠️ Low Performers (< 10 Solved)",
        "🔧 InActive/Possible API Failure",
        "🚫 Profile Link Not Provided",
        "🎯 Custom LC Range Filter"
    ])

    # Reusable table display configuration with clickable links
    column_config = {
        "lc_profile": st.column_config.LinkColumn("LeetCode", display_text="Open LeetCode ↗"),
        "hr_profile": st.column_config.LinkColumn("HackerRank", display_text="Open HackerRank ↗"),
    }

    with t1:
        low_performers = df[df["Status"] == "Low Performer"]
        st.caption(f"Found {len(low_performers)} students with total score < 10")
        st.dataframe(
            low_performers[["roll_no", "name", "lc_total", "hr_badges", "lc_profile", "hr_profile"]],
            column_config=column_config,
            use_container_width=True,
            hide_index=True
        )

    with t2:
        api_failures = df[df["Status"] == "InActive/Possible API Failure"]
        st.caption(f"Found {len(api_failures)} profiles triggering errors or account inactive or set to private (manual verification needed)")
        st.dataframe(
            api_failures[["roll_no", "name", "lc_profile", "hr_profile"]],
            column_config=column_config,
            use_container_width=True,
            hide_index=True
        )

    with t3:
        missing_links = df[df["Status"] == "Profile link not provided"]
        st.caption(f"Found {len(missing_links)} students with no submitted profile links")
        st.dataframe(
            missing_links[["roll_no", "name"]],
            use_container_width=True,
            hide_index=True
        )

    with t4:
        st.markdown("### Filter by LeetCode Solved Count")
        
        # Add a dual-ended slider for dynamic range selection
        max_lc = int(df["lc_total"].max()) if not df.empty else 100
        
        # Prevent slider errors if the current max is 0 (e.g., empty data)
        slider_max = max(max_lc + 20, 100) 
        
        col1, col2 = st.columns([2, 1])
        with col1:
            lc_range = st.slider(
                "Select LeetCode Total Range:",
                min_value=0,
                max_value=slider_max,
                value=(60, slider_max), # Defaults to looking for 60+
                step=1
            )
            
        min_val, max_val = lc_range
        
        # Filter and sort the dataframe based on slider input
        filtered_df = df[(df["lc_total"] >= min_val) & (df["lc_total"] <= max_val)].copy()
        filtered_df = filtered_df.sort_values("lc_total", ascending=False)
        
        st.caption(f"Found **{len(filtered_df)}** students who solved between **{min_val} and {max_val}** problems.")
        
        st.dataframe(
            filtered_df[["roll_no", "name", "lc_total", "lc_easy", "lc_medium", "lc_hard", "lc_profile"]],
            column_config=column_config,
            use_container_width=True,
            hide_index=True
        )