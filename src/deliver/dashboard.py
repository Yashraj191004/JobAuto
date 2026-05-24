"""Local dashboard — single surface for everything.

Run:   streamlit run src/deliver/dashboard.py

The page is split into per-tab modules under ``src/deliver/tabs/``. This file
is only the entrypoint: it builds the page chrome, sidebar filters, and the
shared ``DashboardContext`` once per render, then dispatches to each tab.
"""
from __future__ import annotations
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

# Make `src.*` importable when launched via `streamlit run`.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.schema import connect, init_db
from src.config import load_profile
from src.deliver.common import (
    CSS, EXTENSION_API,
    EMPLOYMENT_TYPES, WORK_MODES, SENIORITY_LEVELS, VERDICT_CHOICES,
    SORT_OPTIONS, WINDOW_DAYS, PRESETS,
    DashboardContext, check_server, distinct_values, h,
)
from src.deliver.tabs import fits as tab_fits_mod
from src.deliver.tabs import all_jobs as tab_all_jobs_mod
from src.deliver.tabs import queue as tab_queue_mod
from src.deliver.tabs import tracker as tab_tracker_mod
from src.deliver.tabs import workflow as tab_workflow_mod
from src.deliver.tabs import knowledge as tab_knowledge_mod


st.set_page_config(
    page_title="Job Agent — Command Center",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"About": "Job Agent — personal automated job pipeline."},
)
init_db()
TRACK_CHOICES = [t.get("track") for t in (load_profile().get("targets") or []) if t.get("track")]

# Inject global CSS once.
st.markdown(CSS, unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────
# Sidebar — preset + filter state
# ──────────────────────────────────────────────────────────────────────

def _apply_preset(name: str) -> None:
    p = PRESETS[name]
    st.session_state["f_min_score"]   = p["min_score"]
    st.session_state["f_date_window"] = p["date_window"]
    st.session_state["f_emp_types"]   = p["emp_types"]
    st.session_state["f_work_modes"]  = p["work_modes"]
    st.session_state["f_seniorities"] = p["seniorities"]


def _reset_filters() -> None:
    for k in [
        "f_min_score", "f_date_window", "f_track_filter", "f_source_filter",
        "f_status_filter", "f_verdict_filter", "f_company_filter",
        "f_keyword", "f_location", "f_emp_types", "f_work_modes",
        "f_seniorities", "f_remote_only", "f_excl_clearance",
        "f_excl_senior", "f_hide_seen", "f_sort",
    ]:
        st.session_state.pop(k, None)


server_ok, server_info = check_server()
source_choices  = distinct_values("source")
company_choices = distinct_values("company")
status_choices  = distinct_values("status")
default_statuses = [s for s in ("scored", "queued") if s in status_choices]


with st.sidebar:
    st.markdown(
        """
        <div style="padding: 4px 0 14px;">
          <div style="font-family:'Fraunces',serif; font-size: 22px; font-weight: 600;
                      color: #fff; letter-spacing: -0.02em;">Filters</div>
          <div style="font-family:'JetBrains Mono',monospace; font-size: 10px;
                      color: #aab0bc; letter-spacing: 0.14em;
                      text-transform: uppercase; margin-top: 2px;">
            Refine your pipeline
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div style="color:#aab0bc; font-size: 10px; font-weight: 600; '
        'letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 6px;">'
        'Quick Presets</div>',
        unsafe_allow_html=True,
    )
    preset_cols = st.columns(2)
    for i, name in enumerate(PRESETS.keys()):
        if preset_cols[i % 2].button(name, key=f"preset_{i}", use_container_width=True):
            _apply_preset(name)
            st.rerun()
    st.markdown('<div style="height: 8px;"></div>', unsafe_allow_html=True)
    if st.button("↺  Reset all filters", key="reset_filters", use_container_width=True):
        _reset_filters()
        st.rerun()
    st.divider()

    with st.expander("Quality & Fit", expanded=True):
        min_score = st.slider("Min fit score", 1, 10, key="f_min_score",
                              value=st.session_state.get("f_min_score", 7))
        verdict_filter = st.multiselect(
            "Verdict", VERDICT_CHOICES,
            default=st.session_state.get("f_verdict_filter", VERDICT_CHOICES),
            key="f_verdict_filter",
            help="Only affects scored jobs in the Fit Scores tab.",
        )
        hide_seen = st.checkbox("Hide skipped & applied",
                                value=st.session_state.get("f_hide_seen", True),
                                key="f_hide_seen")

    with st.expander("Role & Level", expanded=True):
        track_filter = st.multiselect(
            "Track (category)", TRACK_CHOICES,
            default=st.session_state.get("f_track_filter", TRACK_CHOICES),
            key="f_track_filter",
        )
        emp_types = st.multiselect(
            "Employment type", EMPLOYMENT_TYPES,
            default=st.session_state.get("f_emp_types", []),
            key="f_emp_types",
            help="Internship / New Grad / Full-Time / Contract — inferred from the job title.",
        )
        seniorities = st.multiselect(
            "Seniority", SENIORITY_LEVELS,
            default=st.session_state.get("f_seniorities", []),
            key="f_seniorities",
            help="Entry / Mid / Senior+ — inferred from the job title.",
        )

    with st.expander("Work & Location", expanded=True):
        work_modes = st.multiselect(
            "Work mode", WORK_MODES,
            default=st.session_state.get("f_work_modes", []),
            key="f_work_modes",
            help="Remote / Hybrid / Onsite — inferred from the listed location.",
        )
        location_filter = st.text_input(
            "Location contains",
            value=st.session_state.get("f_location", ""),
            key="f_location",
        )
        remote_only = st.checkbox(
            "Quick toggle: Remote / Hybrid only",
            value=st.session_state.get("f_remote_only", False),
            key="f_remote_only",
        )
        exclude_clearance = st.checkbox(
            "Exclude security clearance",
            value=st.session_state.get("f_excl_clearance", True),
            key="f_excl_clearance",
        )
        exclude_senior = st.checkbox(
            "Exclude senior / staff / principal",
            value=st.session_state.get("f_excl_senior", True),
            key="f_excl_senior",
        )

    with st.expander("Discovery & Source", expanded=False):
        date_windows = ["Today", "Last 3 days", "This week", "This month", "All time"]
        date_window = st.selectbox(
            "Posted", date_windows,
            index=date_windows.index(st.session_state.get("f_date_window", "This week")),
            key="f_date_window",
        )
        source_filter = st.multiselect(
            "Source", source_choices,
            default=st.session_state.get("f_source_filter", source_choices),
            key="f_source_filter",
        )
        status_filter = st.multiselect(
            "Status", status_choices,
            default=st.session_state.get("f_status_filter", default_statuses),
            key="f_status_filter",
        )
        company_filter = st.multiselect(
            "Company", company_choices,
            default=st.session_state.get("f_company_filter", []),
            key="f_company_filter",
        )
        keyword_filter = st.text_input(
            "Keyword in title / description",
            value=st.session_state.get("f_keyword", ""),
            key="f_keyword",
        )

    sort_choice = st.selectbox(
        "Sort by", list(SORT_OPTIONS.keys()),
        index=list(SORT_OPTIONS.keys()).index(
            st.session_state.get("f_sort", "Score (high → low)")
        ),
        key="f_sort",
    )

    st.divider()
    pipeline_tracks = st.multiselect(
        "Pipeline tracks", TRACK_CHOICES,
        default=track_filter or TRACK_CHOICES,
        help="Choose which tracks to ingest/search.",
    )
    if st.button("▶  Run pipeline now", type="primary", use_container_width=True):
        with st.spinner("Ingesting selected tracks..."):
            from src.ingest import run as ing
            ing(tracks=pipeline_tracks)
        st.success("Done.")
        st.rerun()


# ──────────────────────────────────────────────────────────────────────
# Build the shared context once, then render the page
# ──────────────────────────────────────────────────────────────────────

ctx = DashboardContext(
    min_score=min_score,
    date_window=date_window,
    track_filter=track_filter,
    source_filter=source_filter,
    status_filter=status_filter,
    verdict_filter=verdict_filter,
    company_filter=company_filter,
    keyword_filter=keyword_filter,
    location_filter=location_filter,
    emp_types=emp_types,
    work_modes=work_modes,
    seniorities=seniorities,
    remote_only=remote_only,
    exclude_clearance=exclude_clearance,
    exclude_senior=exclude_senior,
    hide_seen=hide_seen,
    sort_choice=sort_choice,
    days=WINDOW_DAYS[date_window],
    track_choices=TRACK_CHOICES,
    source_choices=source_choices,
    status_choices=status_choices,
    company_choices=company_choices,
    server_ok=server_ok,
    server_info=server_info,
)


# Top bar with apply-link health badge.
now_str = datetime.now().strftime("%a %b %d · %H:%M")
api_badge = (
    '<span class="ja-pulse">Apply API online</span>'
    if server_ok
    else '<span class="ja-pulse bad">Apply API offline · run `python -m src.server`</span>'
)
st.markdown(
    f"""
    <div class="ja-topbar">
      <div class="ja-topbar-row">
        <div>
          <div class="ja-kicker">JobAuto · Command Center</div>
          <h1 class="ja-title">Job <em>Agent</em></h1>
          <div class="ja-subtitle">
            Discover fresh roles, filter the full job inventory, tailor your resume and cover letter,
            autofill applications, and track every submission — all from one console.
          </div>
        </div>
        <div class="ja-topbar-meta">
          {api_badge}
          <span>{now_str}</span>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# Top-level KPI strip.
con = connect()
status_counts = {
    row["status"]: row["n"]
    for row in con.execute(
        "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"
    ).fetchall()
}
track_counts = {
    row["track"] or "unknown": row["n"]
    for row in con.execute(
        "SELECT track, COUNT(*) AS n FROM jobs GROUP BY track"
    ).fetchall()
}
latest_run = con.execute("SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT 1").fetchone()
con.close()

st.markdown('<div class="ja-eyebrow">Pipeline Snapshot</div>', unsafe_allow_html=True)
top_a, top_b, top_c, top_d = st.columns(4)
top_a.metric("Fresh / Scored", status_counts.get("new", 0) + status_counts.get("scored", 0))
top_b.metric("Queued",  status_counts.get("queued", 0))
top_c.metric("Applied", status_counts.get("applied", 0))
top_d.metric("Last run", (latest_run["status"] if latest_run else "—").title())

if track_counts:
    chips_html = " ".join(
        f'<span class="ja-chip">{h(k)} · {v}</span>'
        for k, v in sorted(track_counts.items())
    )
    st.markdown(
        f'<div style="margin-top:14px"><span class="ja-col-label" style="margin-right:10px">Tracks</span>{chips_html}</div>',
        unsafe_allow_html=True,
    )

if not server_ok:
    st.markdown(
        f"""
        <div style="background: var(--danger-soft); border: 1px solid rgba(168,50,27,.25);
                    border-left: 3px solid var(--danger);
                    border-radius: var(--r-md); padding: 12px 16px; margin-top: 14px;
                    font-size: 13px; color: var(--ink);">
          <strong style="color: var(--danger)">⚠  Apply API server is not running.</strong>
          Clicking "Open job posting" or "Apply link" below will fail until you start the local server.
          Open a second terminal in the project folder and run <code>python -m src.server</code> —
          this listens on <code>{EXTENSION_API}</code> and is what redirects you to the real job URL
          and powers the Chrome extension's autofill.
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown('<div style="height:18px"></div>', unsafe_allow_html=True)


tab_all_jobs, tab_queue, tab_tracker, tab_workflow, tab_knowledge, tab_fits = st.tabs(
    ["All Jobs", "Queue", "Tracker", "Workflow", "Knowledge", "Fit Scores"]
)

with tab_fits:
    tab_fits_mod.render(ctx)

with tab_all_jobs:
    tab_all_jobs_mod.render(ctx)

with tab_queue:
    tab_queue_mod.render(ctx)

with tab_tracker:
    tab_tracker_mod.render(ctx)

with tab_workflow:
    tab_workflow_mod.render(ctx)

with tab_knowledge:
    tab_knowledge_mod.render(ctx)
