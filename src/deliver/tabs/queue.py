"""Application Queue tab."""
from __future__ import annotations
from datetime import datetime, UTC
from pathlib import Path

import streamlit as st

from src.schema import connect
from src.deliver.common import (
    DashboardContext,
    apply_link, employment_type, work_mode, score_tone,
)


def render(_ctx: DashboardContext) -> None:
    st.markdown('<div class="ja-eyebrow" style="margin-top:18px">02 / Apply</div>', unsafe_allow_html=True)
    st.markdown('<div class="ja-section-title">Application Queue</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ja-note">Tailored documents are ready for these roles. Open the apply link, '
        'let the extension fill visible fields, then record the submission.</div>',
        unsafe_allow_html=True,
    )

    con = connect()
    rows = con.execute(
        """SELECT j.*, a.resume_path, a.cover_path, s.score
           FROM jobs j
           LEFT JOIN applications a ON a.job_id = j.job_id
           LEFT JOIN scores s ON s.job_id = j.job_id
           WHERE j.status='queued'
           ORDER BY j.first_seen DESC"""
    ).fetchall()
    con.close()

    qc1, _qc2 = st.columns([1, 3])
    qc1.metric("Ready to apply", len(rows))

    st.markdown('<div style="height:14px"></div>', unsafe_allow_html=True)

    if not rows:
        st.info("Queue is empty. Tailor a resume from **Today's Fits** to add roles here.")

    for r in rows:
        emp  = employment_type(r["title"])
        mode = work_mode(r["location"])
        with st.container():
            st.markdown(
                f"""
                <div style="background: var(--surface); border: 1px solid var(--line);
                            border-left: 3px solid var(--accent); border-radius: var(--r-md);
                            padding: 16px 18px; margin-bottom: 10px; box-shadow: var(--shadow-soft);">
                  <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:16px; flex-wrap:wrap;">
                    <div>
                      <div style="font-family: var(--font-display); font-size: 19px; font-weight: 600; color: var(--ink); letter-spacing: -0.015em;">
                        {r['company']} <span style="color:var(--muted); font-weight:500;">—</span> {r['title']}
                      </div>
                      <div style="margin-top: 8px;">
                        <span class="ja-chip score {score_tone(r["score"])}">Fit {r["score"] or "?"}/10</span>
                        <span class="ja-chip">{emp}</span>
                        <span class="ja-chip">{mode}</span>
                        <span class="ja-chip">{r["location"] or "Location not listed"}</span>
                      </div>
                    </div>
                    <div style="display: flex; flex-direction: column; gap: 4px; align-items: flex-end;">
                      <a class="ja-link-arrow" href="{apply_link(r['job_id'])}" target="_blank">Apply link →</a>
                    </div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            col1, col2 = st.columns(2)
            if r["resume_path"]:
                col1.markdown(
                    f"<div class='ja-col-label'>Resume</div><code>{r['resume_path']}</code>",
                    unsafe_allow_html=True,
                )
                try:
                    col1.download_button(
                        "↓  Download resume.md",
                        Path(r["resume_path"]).read_text(),
                        file_name="resume.md",
                        key=f"dr_{r['job_id']}",
                    )
                except Exception:
                    pass
            if r["cover_path"]:
                col2.markdown(
                    f"<div class='ja-col-label'>Cover letter</div><code>{r['cover_path']}</code>",
                    unsafe_allow_html=True,
                )
                try:
                    col2.download_button(
                        "↓  Download cover.md",
                        Path(r["cover_path"]).read_text(),
                        file_name="cover_letter.md",
                        key=f"dc_{r['job_id']}",
                    )
                except Exception:
                    pass

            bb1, bb2 = st.columns(2)
            if bb1.button("✓  Mark applied", key=f"qa_{r['job_id']}", type="primary", use_container_width=True):
                con = connect()
                now = datetime.now(UTC).isoformat()
                con.execute("UPDATE jobs SET status='applied' WHERE job_id=?", (r["job_id"],))
                con.execute(
                    """INSERT INTO applications (job_id, applied_at, submitted_at)
                       VALUES (?, ?, ?)
                       ON CONFLICT(job_id) DO UPDATE
                       SET applied_at=excluded.applied_at, submitted_at=excluded.submitted_at""",
                    (r["job_id"], now, now),
                )
                con.commit(); con.close()
                st.rerun()
            if bb2.button("← Back to fits", key=f"qb_{r['job_id']}", use_container_width=True):
                con = connect()
                con.execute("UPDATE jobs SET status='scored' WHERE job_id=?", (r["job_id"],))
                con.commit(); con.close()
                st.rerun()
            st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)
