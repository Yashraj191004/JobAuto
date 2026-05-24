"""Application Tracker tab."""
from __future__ import annotations
from datetime import datetime, timedelta, UTC

import streamlit as st

from src.schema import connect
from src.deliver.common import DashboardContext, score_tone


def render(_ctx: DashboardContext) -> None:
    st.markdown('<div class="ja-eyebrow" style="margin-top:18px">03 / Track</div>', unsafe_allow_html=True)
    st.markdown('<div class="ja-section-title">Application Tracker</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ja-note">A running log of submitted applications, skipped roles, and daily output.</div>',
        unsafe_allow_html=True,
    )

    con = connect()
    applied = con.execute(
        """SELECT j.*, a.applied_at, s.score
           FROM jobs j
           LEFT JOIN applications a ON a.job_id = j.job_id
           LEFT JOIN scores s ON s.job_id = j.job_id
           WHERE j.status='applied'
           ORDER BY a.applied_at DESC"""
    ).fetchall()
    skipped_count = con.execute("SELECT COUNT(*) FROM jobs WHERE status='skipped'").fetchone()[0]
    con.close()

    today_iso   = datetime.now(UTC).date().isoformat()
    week_cutoff = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    today_count = sum(1 for r in applied if r["applied_at"] and r["applied_at"][:10] == today_iso)
    week_count  = sum(1 for r in applied if r["applied_at"] and r["applied_at"] >= week_cutoff)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total applied", len(applied))
    c2.metric("This week",     week_count)
    c3.metric("Today",         today_count)
    c4.metric("Skipped",       skipped_count)

    st.markdown('<div style="height:18px"></div>', unsafe_allow_html=True)
    st.markdown('<div class="ja-col-label">Submission Log</div>', unsafe_allow_html=True)

    if not applied:
        st.info("No applications yet.")
        return

    for r in applied:
        when = (r["applied_at"] or "")[:16].replace("T", " ")
        st.markdown(
            f"""
            <div style="display:grid; grid-template-columns: 160px 1fr auto; gap:18px;
                        padding: 10px 14px; border-bottom: 1px dashed var(--line);
                        font-size: 13px; align-items:baseline;">
              <span style="font-family:var(--font-mono); color:var(--muted); font-size:11px;">{when}</span>
              <span><strong style="color:var(--ink); font-weight:600">{r['company']}</strong> · <a href="{r['url']}" target="_blank">{r['title']}</a></span>
              <span class="ja-chip score {score_tone(r['score'])}">{r['score'] or '?'}/10</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
