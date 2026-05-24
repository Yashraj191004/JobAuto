"""Pipeline Health / Workflow tab."""
from __future__ import annotations
import shutil
import time

import requests
import streamlit as st

from src.schema import connect
from src.deliver.common import DashboardContext, copilot_available


def render(ctx: DashboardContext) -> None:
    st.markdown('<div class="ja-eyebrow" style="margin-top:18px">04 / Operate</div>', unsafe_allow_html=True)
    st.markdown('<div class="ja-section-title">Pipeline Health</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ja-note">AI provider order: <code>Gemini → Copilot → Codex → Claude</code>. '
        'If a provider is missing, the pipeline falls through to the next.</div>',
        unsafe_allow_html=True,
    )

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Gemini CLI",  "OK" if shutil.which("gemini") else "Missing")
    col_b.metric("Copilot CLI", "OK" if copilot_available()   else "Missing")
    col_c.metric("Codex CLI",   "OK" if shutil.which("codex") else "Missing")
    col_d.metric("Claude CLI",  "OK" if shutil.which("claude") else "Missing")

    st.markdown('<div style="height:14px"></div>', unsafe_allow_html=True)

    if ctx.server_ok:
        counts = ctx.server_info.get("counts") if isinstance(ctx.server_info, dict) else ""
        st.success(f"Local API server is up — {counts}")
    else:
        st.error(
            "API server is **not** running.\n\n"
            "The Chrome extension AND the in-dashboard 'Open job posting' links both depend on it. "
            "Start it in a second terminal with:\n\n"
            "```\npython -m src.server\n```\n\n"
            "It listens on `http://127.0.0.1:8765`. "
            f"Last error: `{ctx.server_info}`"
        )

    if st.button("Re-test API server"):
        st.rerun()

    st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)
    st.markdown('<div class="ja-col-label">Recent pipeline runs</div>', unsafe_allow_html=True)

    con = connect()
    runs = con.execute("SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT 10").fetchall()
    for r in runs:
        klass = "ok" if r["status"] == "ok" else ("err" if r["status"] == "error" else "")
        st.markdown(
            f"""
            <div class="ja-run-row {klass}">
              <span class="dot"></span>
              <span class="stage">{r['stage']}</span>
              <span class="meta">{r['started_at'][:19]} → {(r['ended_at'] or '—')[:19]}</span>
              <span class="meta" style="margin-left:auto; color:var(--ink-soft);">{r['detail'] or ''}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    if not runs:
        st.info("No runs yet — use the sidebar **Run pipeline now**.")

    st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)
    st.markdown('<div class="ja-col-label">Recent events</div>', unsafe_allow_html=True)

    events = con.execute("SELECT * FROM events ORDER BY id DESC LIMIT 25").fetchall()
    con.close()
    for e in events:
        st.markdown(
            f"""
            <div class="ja-log-row">
              <span class="ts">{e['ts'][:19]}</span>
              <span class="kind">{e['kind']}</span>
              <span class="detail">{('job=' + e['job_id']) if e['job_id'] else '—'} · {e['detail'] or ''}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)
    st.markdown('<div class="ja-col-label">Data sources</div>', unsafe_allow_html=True)

    sources_status = {
        "Greenhouse":      "https://boards-api.greenhouse.io/v1/boards/stripe/jobs",
        "Lever":           "https://api.lever.co/v0/postings/netflix?mode=json",
        "Ashby":           "https://api.ashbyhq.com/posting-api/job-board/Ashby",
        "SimplifyJobs NG": "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json",
        "YC OSS":          "https://yc-oss.github.io/api/companies/all.json",
    }
    if st.button("⊙  Probe all sources"):
        for name, url in sources_status.items():
            try:
                t0 = time.time()
                r = requests.get(url, timeout=8)
                ms = int((time.time() - t0) * 1000)
                if r.ok:
                    st.success(f"{name}  ·  HTTP {r.status_code}  ·  {ms}ms")
                else:
                    st.error(f"{name}  ·  HTTP {r.status_code}")
            except Exception as ex:
                st.error(f"{name}  ·  {ex}")
