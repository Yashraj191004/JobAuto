"""Today's Fits (Best Matches) tab."""
from __future__ import annotations
from datetime import datetime, UTC

import streamlit as st

from src.schema import connect
from src.tailor import tailor
from src.deliver.common import (
    DashboardContext,
    SORT_OPTIONS, VERDICT_CHOICES, PRESETS,
    apply_link, employment_type, work_mode, seniority,
    row_matches_inferred, safe_json_list, short_dt, score_tone,
)


def render(ctx: DashboardContext) -> None:
    st.markdown('<div class="ja-eyebrow" style="margin-top:18px">01 / Discover</div>', unsafe_allow_html=True)
    st.markdown('<div class="ja-section-title">Best Matches</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="ja-note">{len(PRESETS)} quick presets in the sidebar let you flip between '
        "common views in one click. Sort, employment type, work mode, and seniority filters are "
        "inferred live from each job's title and location.</div>",
        unsafe_allow_html=True,
    )

    where, params = ctx.build_where()
    con = connect()
    rows = con.execute(
        f"""SELECT j.*, s.score, s.verdict, s.strengths, s.gaps, s.red_flags
            FROM jobs j JOIN scores s ON s.job_id = j.job_id
            WHERE {where}
            ORDER BY {SORT_OPTIONS[ctx.sort_choice]}""",
        params,
    ).fetchall()
    con.close()

    rows = [r for r in rows if row_matches_inferred(r, ctx.emp_types, ctx.work_modes, ctx.seniorities)]

    fc1, fc2, fc3, fc4 = st.columns(4)
    fc1.metric("Visible matches", len(rows))
    fc2.metric("Window",   ctx.date_window)
    fc3.metric("Min score", f"{ctx.min_score} / 10")
    fc4.metric("Sort",     ctx.sort_choice.split(" (")[0])

    # Active-filter summary chips
    active_chips: list[str] = []
    if ctx.emp_types:     active_chips.append(f"Type: {', '.join(ctx.emp_types)}")
    if ctx.work_modes:    active_chips.append(f"Mode: {', '.join(ctx.work_modes)}")
    if ctx.seniorities:   active_chips.append(f"Level: {', '.join(ctx.seniorities)}")
    if ctx.verdict_filter and len(ctx.verdict_filter) < len(VERDICT_CHOICES):
        active_chips.append(f"Verdict: {', '.join(ctx.verdict_filter)}")
    if ctx.keyword_filter.strip():
        active_chips.append(f'Keyword: "{ctx.keyword_filter.strip()}"')
    if ctx.location_filter.strip():
        active_chips.append(f'Location: "{ctx.location_filter.strip()}"')
    if active_chips:
        chips_html = " ".join(f'<span class="ja-chip info">{c}</span>' for c in active_chips)
        st.markdown(
            f'<div style="margin-top:14px"><span class="ja-col-label" style="margin-right:10px">Active filters</span>{chips_html}</div>',
            unsafe_allow_html=True,
        )

    reviewed_ids = [r["job_id"] for r in rows if r["status"] == "scored"]
    if reviewed_ids and st.button("Hide reviewed jobs", key="hide_reviewed_jobs"):
        con = connect()
        now = datetime.now(UTC).isoformat()
        con.executemany(
            "UPDATE jobs SET status='seen' WHERE job_id=? AND status='scored'",
            [(job_id,) for job_id in reviewed_ids],
        )
        con.execute(
            "INSERT INTO events (kind, detail, ts) VALUES (?,?,?)",
            ("seen", f"hidden_reviewed={len(reviewed_ids)}", now),
        )
        con.commit()
        con.close()
        st.rerun()

    st.markdown('<div style="height:14px"></div>', unsafe_allow_html=True)

    if not rows:
        st.info("No matches in this window. Try widening the date range, lowering the min score, or running the pipeline.")

    for r in rows:
        score = int(r["score"] or 0)
        emp    = employment_type(r["title"])
        mode   = work_mode(r["location"])
        senior = seniority(r["title"])
        header = f"{score}/10   ·   {r['company']}   —   {r['title']}   ·   {emp} · {mode}"
        with st.expander(header):
            posted = r["posted_at"] or r["first_seen"]
            st.markdown(
                f"""
                <div style="margin-bottom: 4px;">
                  <span class="ja-chip score {score_tone(score)}">Fit {score}/10</span>
                  <span class="ja-chip">{r['track'] or 'track unknown'}</span>
                  <span class="ja-chip">{emp}</span>
                  <span class="ja-chip">{mode}</span>
                  <span class="ja-chip">{senior}</span>
                  <span class="ja-chip">{r['source']}</span>
                  <span class="ja-chip">{r['location'] or 'Location not listed'}</span>
                  <span class="ja-chip">Posted {short_dt(posted)}</span>
                </div>
                <div style="margin: 10px 0 14px;">
                  <a class="ja-link-arrow" href="{apply_link(r['job_id'])}" target="_blank">
                    Open job posting →
                  </a>
                </div>
                """,
                unsafe_allow_html=True,
            )

            c1, c2 = st.columns(2)
            with c1:
                st.markdown('<div class="ja-col-label">Strengths</div>', unsafe_allow_html=True)
                strengths = safe_json_list(r["strengths"])
                if not strengths:
                    st.markdown('<span class="ja-muted">No strengths saved yet.</span>', unsafe_allow_html=True)
                for s in strengths:
                    st.markdown(f"<div class='ja-card-body'>— {s}</div>", unsafe_allow_html=True)
            with c2:
                st.markdown('<div class="ja-col-label">Gaps & Red Flags</div>', unsafe_allow_html=True)
                gaps  = safe_json_list(r["gaps"])
                flags = safe_json_list(r["red_flags"])
                if not gaps and not flags:
                    st.markdown('<span class="ja-muted">No major gaps flagged.</span>', unsafe_allow_html=True)
                for s in gaps:
                    st.markdown(f"<div class='ja-card-body'>— {s}</div>", unsafe_allow_html=True)
                for s in flags:
                    st.markdown(
                        f"<div class='ja-card-body'><strong style='color:var(--danger)'>⚑ Red flag</strong> — {s}</div>",
                        unsafe_allow_html=True,
                    )

            st.markdown('<hr class="ja-divider">', unsafe_allow_html=True)

            b1, b2, b3 = st.columns([2, 1, 1])
            if b1.button("✦  Tailor resume + cover letter", key=f"t_{r['job_id']}",
                         type="primary", use_container_width=True):
                with st.spinner("Generating tailored documents…"):
                    out = tailor(r["job_id"])
                st.success(f"Saved → {out['resume']}")
                st.rerun()
            if b2.button("Skip", key=f"s_{r['job_id']}", use_container_width=True):
                con = connect()
                con.execute("UPDATE jobs SET status='skipped' WHERE job_id=?", (r["job_id"],))
                con.execute(
                    "INSERT INTO events (job_id, kind, detail, ts) VALUES (?,?,?,?)",
                    (r["job_id"], "skip", None, datetime.now(UTC).isoformat()),
                )
                con.commit(); con.close()
                st.rerun()
            if b3.button("Mark applied", key=f"a_{r['job_id']}", use_container_width=True):
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
                    (r["job_id"], "submit", "manual", now),
                )
                con.commit(); con.close()
                st.rerun()
