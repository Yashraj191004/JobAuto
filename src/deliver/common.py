"""Shared dashboard plumbing: constants, helpers, CSS, filter-state.

The dashboard is split into per-tab modules under ``src/deliver/tabs/``.
Each tab function takes a single ``ctx`` argument — a SimpleNamespace built
once by ``dashboard.py`` — so the tabs do not need to import each other
or recompute filter SQL.
"""
from __future__ import annotations
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, UTC
from html import escape

import requests
import streamlit as st

from src.schema import connect
from src.config import COPILOT_ASK_COMMAND

EXTENSION_API = "http://127.0.0.1:8765"


# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

EMPLOYMENT_TYPES = ["Internship", "New Grad", "Full-Time", "Contract"]
WORK_MODES       = ["Remote", "Hybrid", "Onsite"]
SENIORITY_LEVELS = ["Entry", "Mid", "Senior+"]
VERDICT_CHOICES  = ["apply", "maybe", "skip"]

SORT_OPTIONS = {
    "Score (high → low)": "s.score DESC, COALESCE(j.posted_at, j.first_seen) DESC",
    "Newest first":       "COALESCE(j.posted_at, j.first_seen) DESC, s.score DESC",
    "Oldest first":       "COALESCE(j.posted_at, j.first_seen) ASC",
    "Company (A → Z)":    "lower(j.company) ASC, s.score DESC",
}
ALL_JOBS_SORT_OPTIONS = {
    "Newest discovered":    "j.first_seen DESC",
    "Recently seen":        "j.last_seen DESC",
    "Posted newest":        "COALESCE(j.posted_at, j.first_seen) DESC",
    "Company (A to Z)":     "lower(j.company) ASC, lower(j.title) ASC",
    "Score (high to low)":  "s.score DESC, j.first_seen DESC",
}
WINDOW_DAYS = {
    "Today": 1, "Last 3 days": 3, "This week": 7,
    "This month": 30, "All time": None,
}

PRESETS = {
    "Top picks (9+)":       {"min_score": 9, "date_window": "This week",  "emp_types": [],            "work_modes": [],                "seniorities": ["Entry", "Mid"]},
    "Remote / Hybrid only": {"min_score": 7, "date_window": "This week",  "emp_types": [],            "work_modes": ["Remote","Hybrid"], "seniorities": ["Entry", "Mid"]},
    "Internships":          {"min_score": 6, "date_window": "This month", "emp_types": ["Internship"], "work_modes": [],               "seniorities": ["Entry"]},
    "New Grad only":        {"min_score": 7, "date_window": "This month", "emp_types": ["New Grad"],   "work_modes": [],               "seniorities": ["Entry"]},
    "Fresh today":          {"min_score": 6, "date_window": "Today",      "emp_types": [],             "work_modes": [],               "seniorities": ["Entry","Mid"]},
}


# ──────────────────────────────────────────────────────────────────────
# Small utilities
# ──────────────────────────────────────────────────────────────────────

def apply_link(job_id: str) -> str:
    return f"{EXTENSION_API}/apply/{job_id}"


def employment_type(title: str) -> str:
    t = (title or "").lower()
    if "intern" in t and "internal" not in t:
        return "Internship"
    if any(k in t for k in [
        "new grad", "new-grad", "newgrad", "early career", "university grad",
        "entry level", "entry-level", "graduate program", "associate software",
    ]):
        return "New Grad"
    if any(k in t for k in ["contractor", "contract", "consultant", "1099"]):
        return "Contract"
    return "Full-Time"


def work_mode(location: str) -> str:
    l = (location or "").lower()
    if "hybrid" in l:
        return "Hybrid"
    if "remote" in l or "anywhere" in l or "work from home" in l:
        return "Remote"
    return "Onsite"


def seniority(title: str) -> str:
    t = (title or "").lower()
    if any(k in t for k in [
        "senior", "staff", "principal", "distinguished",
        " lead", "manager", "director", "head of", "vp ",
    ]):
        return "Senior+"
    if any(k in t for k in [
        "intern", "new grad", "new-grad", "entry", "associate",
        "junior", "early career", "graduate program",
    ]):
        return "Entry"
    return "Mid"


def row_matches_inferred(row, emp_types: list[str], work_modes_: list[str], seniorities: list[str]) -> bool:
    if emp_types and employment_type(row["title"]) not in emp_types:
        return False
    if work_modes_ and work_mode(row["location"]) not in work_modes_:
        return False
    if seniorities and seniority(row["title"]) not in seniorities:
        return False
    return True


def check_server() -> tuple[bool, dict | str]:
    try:
        r = requests.get(f"{EXTENSION_API}/health", timeout=2)
        return r.ok, (r.json() if r.ok else r.text)
    except Exception as e:
        return False, str(e)


def distinct_values(column: str, table: str = "jobs") -> list[str]:
    allowed = {
        "jobs":   {"source", "company", "location", "status"},
        "scores": {"verdict", "track_match"},
    }
    if column not in allowed.get(table, set()):
        return []
    con = connect()
    rows = con.execute(
        f"SELECT DISTINCT {column} AS value FROM {table} "
        f"WHERE {column} IS NOT NULL AND {column} != '' ORDER BY {column}"
    ).fetchall()
    con.close()
    return [row["value"] for row in rows]


def safe_json_list(value: str | None) -> list[str]:
    try:
        data = json.loads(value or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def short_dt(value: str | None) -> str:
    if not value:
        return "Unknown"
    return value[:16].replace("T", " ")


def score_tone(score: int | None) -> str:
    if not score:
        return "warn"
    if score >= 8:
        return "good"
    if score >= 6:
        return "warn"
    return "danger"


def h(value) -> str:
    return escape("" if value is None else str(value), quote=True)


def copilot_available() -> bool:
    return bool(COPILOT_ASK_COMMAND or shutil.which("gh") or shutil.which("copilot"))


# ──────────────────────────────────────────────────────────────────────
# Shared dashboard context
# ──────────────────────────────────────────────────────────────────────

@dataclass
class DashboardContext:
    """A bundle of filter state + helpers shared across every tab.

    ``dashboard.py`` builds one of these once per render and passes it into
    each tab's ``render()`` function.
    """
    # Filter state
    min_score:        int
    date_window:      str
    track_filter:     list[str]
    source_filter:    list[str]
    status_filter:    list[str]
    verdict_filter:   list[str]
    company_filter:   list[str]
    keyword_filter:   str
    location_filter:  str
    emp_types:        list[str]
    work_modes:       list[str]
    seniorities:      list[str]
    remote_only:      bool
    exclude_clearance: bool
    exclude_senior:   bool
    hide_seen:        bool
    sort_choice:      str
    days:             int | None

    # Derived choices for the sidebar
    track_choices:    list[str]
    source_choices:   list[str]
    status_choices:   list[str]
    company_choices:  list[str]

    # Server health
    server_ok:        bool
    server_info:      object

    def build_where(self) -> tuple[str, list]:
        clauses = ["s.score >= ?"]
        params: list = [self.min_score]
        if self.track_filter:
            clauses.append(f"j.track IN ({','.join('?' * len(self.track_filter))})")
            params += self.track_filter
        if self.source_filter:
            clauses.append(f"j.source IN ({','.join('?' * len(self.source_filter))})")
            params += self.source_filter
        if self.status_filter:
            clauses.append(f"j.status IN ({','.join('?' * len(self.status_filter))})")
            params += self.status_filter
        elif self.hide_seen:
            clauses.append("j.status IN ('scored','queued')")
        if self.verdict_filter and set(self.verdict_filter) != set(VERDICT_CHOICES):
            clauses.append(f"s.verdict IN ({','.join('?' * len(self.verdict_filter))})")
            params += self.verdict_filter
        if self.company_filter:
            clauses.append(f"j.company IN ({','.join('?' * len(self.company_filter))})")
            params += self.company_filter
        if self.keyword_filter.strip():
            kw = f"%{self.keyword_filter.strip().lower()}%"
            clauses.append(
                "(lower(j.title) LIKE ? OR lower(COALESCE(j.description, '')) LIKE ?)"
            )
            params += [kw, kw]
        if self.location_filter.strip():
            clauses.append("lower(COALESCE(j.location, '')) LIKE ?")
            params.append(f"%{self.location_filter.strip().lower()}%")
        if self.remote_only:
            clauses.append(
                "(lower(COALESCE(j.location, '')) GLOB '*remote*' "
                "OR lower(COALESCE(j.location, '')) GLOB '*hybrid*')"
            )
        if self.exclude_clearance:
            clauses.append(
                "lower(j.title || ' ' || COALESCE(j.description, '')) NOT LIKE '%security clearance%'"
            )
        if self.exclude_senior:
            clauses.append(
                "lower(j.title) NOT GLOB '*senior*' AND lower(j.title) NOT GLOB '*staff*' "
                "AND lower(j.title) NOT GLOB '*principal*' AND lower(j.title) NOT GLOB '*lead*'"
            )
        if self.days is not None:
            cutoff = (datetime.now(UTC) - timedelta(days=self.days)).isoformat()
            clauses.append("(COALESCE(j.posted_at, j.first_seen) >= ?)")
            params.append(cutoff)
        return " AND ".join(clauses), params


# ──────────────────────────────────────────────────────────────────────
# CSS — injected once by dashboard.py
# ──────────────────────────────────────────────────────────────────────

CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700;9..144,800&family=Inter+Tight:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">

<style>
  :root {
    --bg: #f5f2ec; --bg-alt: #efeae1;
    --surface: #ffffff; --surface-2: #faf7f1;
    --ink: #0c1118; --ink-soft: #2a2f3a;
    --muted: #6b6f78; --muted-2: #9ba0aa;
    --line: #e3ddd1; --line-strong: #d2cab9;
    --accent: #0f5a4d; --accent-ink: #073e34; --accent-soft: #e8f1ed;
    --gold: #b8862a; --gold-soft: #fbf2d9;
    --danger: #a8321b; --danger-soft: #fbe8e2;
    --info: #1f4d8a; --info-soft: #e6eef9;
    --font-display: 'Fraunces', 'Iowan Old Style', Georgia, serif;
    --font-body:    'Inter Tight', -apple-system, system-ui, sans-serif;
    --font-mono:    'JetBrains Mono', 'SF Mono', Menlo, monospace;
    --r-sm: 4px; --r-md: 6px; --r-lg: 10px;
    --shadow-soft: 0 1px 2px rgba(12,17,24,.04), 0 0 0 1px rgba(12,17,24,.03);
    --shadow-card: 0 1px 2px rgba(12,17,24,.05), 0 8px 24px -16px rgba(12,17,24,.18);
  }
  html, body, [data-testid="stAppViewContainer"] {
    background: var(--bg); color: var(--ink); font-family: var(--font-body);
  }
  [data-testid="stHeader"] { background: transparent; }
  .block-container { padding-top: 1.5rem !important; padding-bottom: 4rem; max-width: 1380px; }
  footer, #MainMenu { visibility: hidden; }

  /* sidebar */
  [data-testid="stSidebar"] { background: var(--ink); border-right: 1px solid #1a212c; }
  [data-testid="stSidebar"] * { color: #e5e2d8 !important; }
  [data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,[data-testid="stSidebar"] h3 {
    color: #fff !important; font-family: var(--font-display);
    font-weight: 600; letter-spacing: -0.01em;
  }
  [data-testid="stSidebar"] label,
  [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
    color: #aab0bc !important; font-size: 11px !important;
    font-weight: 600 !important; letter-spacing: 0.09em; text-transform: uppercase;
  }
  [data-testid="stSidebar"] [data-baseweb="select"] > div,
  [data-testid="stSidebar"] input[type="text"],
  [data-testid="stSidebar"] input[type="number"] {
    background: #1a212c !important; border: 1px solid #2a3340 !important;
    color: #e5e2d8 !important; border-radius: var(--r-md) !important;
  }
  [data-testid="stSidebar"] [data-baseweb="tag"] {
    background: var(--accent) !important; color: #fff !important;
    border-radius: 3px !important;
  }
  [data-testid="stSidebar"] hr { border-color: #232a35 !important; margin: 1rem 0 !important; }
  [data-testid="stSidebar"] .stCheckbox label p {
    color: #e5e2d8 !important; font-size: 13px !important;
    font-weight: 400 !important; text-transform: none !important; letter-spacing: normal !important;
  }
  [data-testid="stSidebar"] .stButton > button {
    background: var(--accent) !important; color: #fff !important;
    border: 1px solid var(--accent) !important; font-weight: 600 !important;
  }
  [data-testid="stSidebar"] .stButton > button:hover {
    background: var(--accent-ink) !important; border-color: var(--accent-ink) !important;
  }
  [data-testid="stSidebar"] .stButton > button[kind="secondary"] {
    background: transparent !important; border: 1px solid #2a3340 !important;
  }
  [data-testid="stSidebar"] .stSlider [data-baseweb="slider"] [role="slider"] {
    background: var(--accent) !important;
  }
  [data-testid="stSidebar"] [data-testid="stExpander"] {
    background: transparent !important; border: 1px solid #232a35 !important;
    border-radius: var(--r-md) !important; margin-bottom: 6px;
  }
  [data-testid="stSidebar"] [data-testid="stExpander"] summary {
    background: #131a24 !important; padding: 8px 12px !important;
  }
  [data-testid="stSidebar"] [data-testid="stExpander"] summary p {
    color: #ffffff !important; font-size: 11px !important;
    font-weight: 600 !important; letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
  }
  [data-testid="stSidebar"] [data-testid="stExpanderDetails"] { padding: 10px 12px 6px !important; }

  /* topbar */
  .ja-topbar {
    position: relative; background: var(--surface); border: 1px solid var(--line);
    border-radius: var(--r-lg); padding: 28px 32px; margin-bottom: 14px;
    box-shadow: var(--shadow-card); overflow: hidden;
  }
  .ja-topbar::before {
    content: ""; position: absolute; inset: 0;
    background:
      radial-gradient(800px 200px at 90% -10%, rgba(15,90,77,.07), transparent 60%),
      radial-gradient(600px 160px at 10% 110%, rgba(184,134,42,.05), transparent 60%);
    pointer-events: none;
  }
  .ja-topbar-row {
    position: relative; display: flex; justify-content: space-between;
    align-items: flex-end; gap: 24px; flex-wrap: wrap;
  }
  .ja-kicker {
    display: inline-flex; align-items: center; gap: 8px;
    color: var(--accent); font-family: var(--font-mono);
    font-size: 11px; font-weight: 600; letter-spacing: 0.18em;
    text-transform: uppercase; margin-bottom: 10px;
  }
  .ja-kicker::before {
    content: ""; width: 6px; height: 6px; border-radius: 50%;
    background: var(--accent); box-shadow: 0 0 0 4px rgba(15,90,77,.15);
  }
  .ja-title {
    font-family: var(--font-display); color: var(--ink);
    font-size: 46px; font-weight: 600; line-height: 1; margin: 0;
    letter-spacing: -0.025em;
  }
  .ja-title em { font-style: italic; font-weight: 500; color: var(--accent); }
  .ja-subtitle {
    color: var(--muted); font-size: 15px; margin-top: 12px;
    max-width: 620px; line-height: 1.5;
  }
  .ja-topbar-meta {
    display: flex; gap: 14px; align-items: center; flex-wrap: wrap;
    font-family: var(--font-mono); font-size: 11px; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.1em;
  }
  .ja-pulse {
    display: inline-flex; align-items: center; gap: 7px;
    padding: 4px 10px; border-radius: 999px;
    background: var(--accent-soft); color: var(--accent-ink);
    border: 1px solid rgba(15,90,77,.2);
  }
  .ja-pulse.warn { background: var(--gold-soft); color: var(--gold); border-color: rgba(184,134,42,.25); }
  .ja-pulse.bad  { background: var(--danger-soft); color: var(--danger); border-color: rgba(168,50,27,.2); }
  .ja-pulse::before {
    content: ""; width: 6px; height: 6px; border-radius: 50%;
    background: currentColor;
    animation: ja-pulse 2.4s ease-out infinite;
  }
  @keyframes ja-pulse {
    0%   { box-shadow: 0 0 0 0 currentColor; opacity: 1; }
    70%  { box-shadow: 0 0 0 6px transparent; opacity: 0.5; }
    100% { box-shadow: 0 0 0 0 transparent; opacity: 1; }
  }

  /* sections */
  .ja-section-title {
    font-family: var(--font-display); color: var(--ink);
    font-size: 26px; font-weight: 600; margin: 6px 0 4px;
    letter-spacing: -0.02em;
  }
  .ja-eyebrow {
    font-family: var(--font-mono); color: var(--muted);
    font-size: 10px; font-weight: 600; letter-spacing: 0.18em;
    text-transform: uppercase; margin-bottom: 4px;
  }
  .ja-note { color: var(--muted); font-size: 14px; line-height: 1.55; margin-bottom: 18px; max-width: 720px; }

  /* metric cards */
  div[data-testid="stMetric"] {
    background: var(--surface); border: 1px solid var(--line);
    border-radius: var(--r-md); padding: 14px 16px 12px; box-shadow: var(--shadow-soft);
  }
  div[data-testid="stMetricLabel"] {
    color: var(--muted) !important; font-size: 11px !important;
    font-weight: 600 !important; letter-spacing: 0.1em; text-transform: uppercase;
  }
  div[data-testid="stMetricValue"] {
    font-family: var(--font-display) !important; color: var(--ink) !important;
    font-size: 34px !important; font-weight: 600 !important;
    letter-spacing: -0.02em; line-height: 1.1;
  }

  /* tabs */
  div[data-testid="stTabs"] [data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid var(--line); background: transparent; }
  div[data-testid="stTabs"] [data-baseweb="tab"] { background: transparent; border-radius: 0; padding: 12px 18px !important; border-bottom: 2px solid transparent; margin-bottom: -1px; }
  div[data-testid="stTabs"] [data-baseweb="tab"] p { font-family: var(--font-body) !important; font-weight: 600 !important; font-size: 14px !important; color: var(--muted); }
  div[data-testid="stTabs"] [aria-selected="true"] { border-bottom-color: var(--accent); }
  div[data-testid="stTabs"] [aria-selected="true"] p { color: var(--ink) !important; }

  /* expanders */
  div[data-testid="stExpander"] {
    border: 1px solid var(--line); border-radius: var(--r-md);
    background: var(--surface); box-shadow: var(--shadow-soft); margin-bottom: 10px;
  }
  div[data-testid="stExpander"]:hover { border-color: var(--line-strong); box-shadow: var(--shadow-card); }
  div[data-testid="stExpander"] summary { padding: 16px 18px !important; }
  div[data-testid="stExpander"] summary p { font-size: 15px !important; font-weight: 600 !important; color: var(--ink) !important; letter-spacing: -0.01em; }
  div[data-testid="stExpander"] [data-testid="stExpanderDetails"] { padding: 4px 20px 20px; border-top: 1px solid var(--line); }

  /* chips */
  .ja-chip {
    display: inline-flex; align-items: center; gap: 5px;
    border: 1px solid var(--line); border-radius: 3px;
    padding: 3px 9px; margin: 0 6px 6px 0;
    color: var(--ink-soft); background: var(--surface-2);
    font-size: 11px; font-weight: 500;
    font-family: var(--font-mono); letter-spacing: 0.02em;
  }
  .ja-chip.good   { color: var(--accent-ink); background: var(--accent-soft); border-color: rgba(15,90,77,.2); }
  .ja-chip.warn   { color: var(--gold);       background: var(--gold-soft);   border-color: rgba(184,134,42,.25); }
  .ja-chip.danger { color: var(--danger);     background: var(--danger-soft); border-color: rgba(168,50,27,.2); }
  .ja-chip.info   { color: var(--info);       background: var(--info-soft);   border-color: rgba(31,77,138,.2); }
  .ja-chip.score  { font-weight: 700; font-family: var(--font-display); font-size: 13px; padding: 2px 10px; }
  .ja-muted { color: var(--muted); font-size: 13px; }

  .ja-card-body { font-size: 14px; color: var(--ink-soft); line-height: 1.6; }
  .ja-card-body strong { color: var(--ink); font-weight: 600; }
  .ja-divider { height: 1px; background: var(--line); margin: 16px 0; border: 0; }
  .ja-col-label {
    font-family: var(--font-mono); font-size: 10px; font-weight: 600;
    letter-spacing: 0.14em; color: var(--muted); text-transform: uppercase;
    margin-bottom: 6px;
  }

  .stButton > button, .stDownloadButton > button {
    border-radius: var(--r-md); border: 1px solid var(--line-strong);
    font-family: var(--font-body); font-weight: 600;
    font-size: 13px; padding: 7px 14px;
    background: var(--surface); color: var(--ink); transition: all .15s ease;
  }
  .stButton > button:hover, .stDownloadButton > button:hover { border-color: var(--ink-soft); background: var(--surface-2); }
  .stButton > button[kind="primary"] { background: var(--accent) !important; border-color: var(--accent) !important; color: #fff !important; }
  .stButton > button[kind="primary"]:hover { background: var(--accent-ink) !important; border-color: var(--accent-ink) !important; }

  a { color: var(--accent); text-decoration: none; font-weight: 600; border-bottom: 1px solid rgba(15,90,77,.3); }
  a:hover { border-bottom-color: var(--accent); }
  .ja-link-arrow { display: inline-flex; align-items: center; gap: 4px; font-family: var(--font-mono); font-size: 12px; letter-spacing: 0.04em; }

  code { font-family: var(--font-mono) !important; font-size: 12px !important; background: var(--bg-alt) !important; color: var(--ink) !important; padding: 1px 6px; border-radius: 3px; }
  pre code { background: var(--ink) !important; color: #e5e2d8 !important; }

  div[data-testid="stAlert"] { border-radius: var(--r-md); border: 1px solid var(--line); background: var(--surface); font-size: 13px; }
  hr { margin: 1.4rem 0 !important; border-color: var(--line) !important; }
  .stCaption, [data-testid="stCaptionContainer"] { color: var(--muted) !important; font-size: 12px !important; font-family: var(--font-mono); }
  h1,h2,h3,h4 { font-family: var(--font-display); color: var(--ink); letter-spacing: -0.015em; }
  h4 { font-weight: 600 !important; font-size: 17px !important; margin-top: 18px !important; }

  .ja-log-row {
    display: grid; grid-template-columns: 150px 80px 1fr; gap: 14px;
    padding: 8px 12px; font-family: var(--font-mono); font-size: 12px;
    border-bottom: 1px dashed var(--line); align-items: baseline;
  }
  .ja-log-row .ts { color: var(--muted); }
  .ja-log-row .kind { font-weight: 700; color: var(--accent); text-transform: uppercase; letter-spacing: 0.06em; }
  .ja-log-row .detail { color: var(--ink-soft); }

  .ja-run-row {
    display: flex; align-items: center; gap: 10px;
    padding: 9px 14px; background: var(--surface);
    border: 1px solid var(--line); border-radius: var(--r-md);
    margin-bottom: 6px; font-size: 13px;
  }
  .ja-run-row .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted-2); }
  .ja-run-row.ok .dot  { background: var(--accent); }
  .ja-run-row.err .dot { background: var(--danger); }
  .ja-run-row .stage { font-weight: 600; color: var(--ink); min-width: 80px; }
  .ja-run-row .meta { font-family: var(--font-mono); color: var(--muted); font-size: 11px; }
</style>
"""
