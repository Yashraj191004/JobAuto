"""All Stored Jobs tab."""
from __future__ import annotations
from datetime import datetime, timedelta, UTC

import streamlit as st

from src.schema import connect
from src.tailor import tailor
from src.deliver.common import (
    DashboardContext,
    ALL_JOBS_SORT_OPTIONS, WINDOW_DAYS,
    apply_link, employment_type, work_mode, short_dt, h,
)


def render(ctx: DashboardContext) -> None:
    st.markdown('<div class="ja-eyebrow" style="margin-top:18px">02 / Inventory</div>', unsafe_allow_html=True)
    st.markdown('<div class="ja-section-title">All Stored Jobs</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ja-note">Every unique job saved in SQLite, including unscored, scored, '
        'queued, skipped, and applied roles.</div>',
        unsafe_allow_html=True,
    )

    f1, f2, f3, f4 = st.columns([1.3, 1, 1, 1])
    keyword = f1.text_input("Search all jobs", key="all_jobs_keyword",
                            placeholder="company, title, location, source")
    window = f2.selectbox(
        "Discovered",
        ["Today", "Last 3 days", "This week", "This month", "All time"],
        index=4, key="all_jobs_window",
    )
    scored_state = f3.selectbox("Score state", ["Any", "Scored only", "Unscored only"], key="all_jobs_scored_state")
    sort_choice  = f4.selectbox("Sort", list(ALL_JOBS_SORT_OPTIONS.keys()), key="all_jobs_sort")

    f5, f6, f7 = st.columns(3)
    tracks   = f5.multiselect("Tracks",   ctx.track_choices,   default=ctx.track_choices,   key="all_jobs_tracks")
    sources  = f6.multiselect("Sources",  ctx.source_choices,  default=ctx.source_choices,  key="all_jobs_sources")
    statuses = f7.multiselect("Statuses", ctx.status_choices,  default=ctx.status_choices,  key="all_jobs_statuses")
    limit    = st.slider("Rows to show", 25, 500, 150, 25, key="all_jobs_limit")

    clauses = ["1=1"]
    params: list = []
    if tracks:
        clauses.append(f"j.track IN ({','.join('?' * len(tracks))})")
        params += tracks
    if sources:
        clauses.append(f"j.source IN ({','.join('?' * len(sources))})")
        params += sources
    if statuses:
        clauses.append(f"j.status IN ({','.join('?' * len(statuses))})")
        params += statuses
    if scored_state == "Scored only":
        clauses.append("s.job_id IS NOT NULL")
    elif scored_state == "Unscored only":
        clauses.append("s.job_id IS NULL")
    if keyword.strip():
        kw = f"%{keyword.strip().lower()}%"
        clauses.append(
            "(lower(j.company) LIKE ? OR lower(j.title) LIKE ? "
            " OR lower(COALESCE(j.location, '')) LIKE ? "
            " OR lower(j.source) LIKE ? "
            " OR lower(COALESCE(j.description, '')) LIKE ?)"
        )
        params += [kw, kw, kw, kw, kw]
    days = WINDOW_DAYS[window]
    if days is not None:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        clauses.append("j.first_seen >= ?")
        params.append(cutoff)

    where = " AND ".join(clauses)
    con = connect()
    total = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    rows = con.execute(
        f"""SELECT j.*, s.score, s.verdict
            FROM jobs j LEFT JOIN scores s ON s.job_id = j.job_id
            WHERE {where}
            ORDER BY {ALL_JOBS_SORT_OPTIONS[sort_choice]}
            LIMIT ?""",
        [*params, limit],
    ).fetchall()
    filtered_total = con.execute(
        f"""SELECT COUNT(*)
            FROM jobs j LEFT JOIN scores s ON s.job_id = j.job_id
            WHERE {where}""",
        params,
    ).fetchone()[0]
    source_rows = con.execute(
        "SELECT source, COUNT(*) AS n FROM jobs GROUP BY source ORDER BY n DESC"
    ).fetchall()
    con.close()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Stored unique jobs", total)
    m2.metric("Matching filters",   filtered_total)
    m3.metric("Shown",              len(rows))
    m4.metric("Sources",            len(source_rows))

    if source_rows:
        source_chips = " ".join(
            f'<span class="ja-chip">{h(r["source"])} · {r["n"]}</span>' for r in source_rows
        )
        st.markdown(
            f'<div style="margin-top:14px"><span class="ja-col-label" style="margin-right:10px">Source mix</span>{source_chips}</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div style="height:14px"></div>', unsafe_allow_html=True)
    if not rows:
        st.info("No stored jobs match these filters.")

    for r in rows:
        emp   = employment_type(r["title"])
        mode  = work_mode(r["location"])
        score = r["score"]
        score_label = f"{score}/10" if score is not None else "unscored"
        header = f"{r['company']} - {r['title']} · {r['status']} · {score_label}"
        with st.expander(header):
            posted = r["posted_at"] or r["first_seen"]
            st.markdown(
                f"""
                <div style="margin-bottom: 10px;">
                  <span class="ja-chip">{h(score_label)}</span>
                  <span class="ja-chip">{h(r['status'])}</span>
                  <span class="ja-chip">{h(r['track'] or 'track unknown')}</span>
                  <span class="ja-chip">{h(emp)}</span>
                  <span class="ja-chip">{h(mode)}</span>
                  <span class="ja-chip">{h(r['source'])}</span>
                  <span class="ja-chip">{h(r['location'] or 'Location not listed')}</span>
                  <span class="ja-chip">Posted {h(short_dt(posted))}</span>
                  <span class="ja-chip">First seen {h(short_dt(r['first_seen']))}</span>
                </div>
                <div style="margin: 10px 0 14px;">
                  <a class="ja-link-arrow" href="{h(apply_link(r['job_id']))}" target="_blank">Open job posting -></a>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if r["description"]:
                st.markdown('<div class="ja-col-label">Description preview</div>', unsafe_allow_html=True)
                st.write((r["description"] or "")[:1200])

            a0, a1, a2, a3 = st.columns([1.2, 2, 1, 1])
            if a0.button("Score this job", key=f"all_score_{r['job_id']}", use_container_width=True):
                from src.score import score_one
                with st.spinner("Scoring selected job..."):
                    out = score_one(r["job_id"])
                if out.get("scored"):
                    st.success("Scored this job.")
                else:
                    st.warning("Could not score this job. Check Workflow logs.")
                st.rerun()
            if a1.button("Tailor resume + cover letter", key=f"all_t_{r['job_id']}", use_container_width=True):
                with st.spinner("Generating tailored documents..."):
                    out = tailor(r["job_id"])
                st.success(f"Saved -> {out['resume']}")
                st.rerun()
            if a2.button("Skip", key=f"all_s_{r['job_id']}", use_container_width=True):
                con = connect()
                con.execute("UPDATE jobs SET status='skipped' WHERE job_id=?", (r["job_id"],))
                con.execute(
                    "INSERT INTO events (job_id, kind, detail, ts) VALUES (?,?,?,?)",
                    (r["job_id"], "skip", "all_jobs", datetime.now(UTC).isoformat()),
                )
                con.commit(); con.close()
                st.rerun()
            if a3.button("Mark applied", key=f"all_a_{r['job_id']}", use_container_width=True):
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
                con.execute(
                    "INSERT INTO events (job_id, kind, detail, ts) VALUES (?,?,?,?)",
                    (r["job_id"], "submit", "manual_all_jobs", now),
                )
                con.commit(); con.close()
                st.rerun()
