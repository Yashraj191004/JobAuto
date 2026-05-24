"""Common Job schema + SQLite tables. Every source normalizes into Job."""
from __future__ import annotations
import sqlite3
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Optional
from .config import JOBS_DB


@dataclass
class Job:
    source: str
    company: str
    title: str
    location: str
    url: str
    description: Optional[str] = None
    posted_at: Optional[str] = None     # ISO string
    track: Optional[str] = None         # e.g. 'new_grad', 'internship', 'cloud'
    raw: dict = field(default_factory=dict)
    job_id: str = ""                    # filled by __post_init__

    def __post_init__(self) -> None:
        if not self.job_id:
            key = f"{self.source}|{self.company.lower()}|{self.title.lower()}|{self.url}"
            self.job_id = hashlib.sha1(key.encode()).hexdigest()[:16]


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(JOBS_DB)
    con.row_factory = sqlite3.Row
    return con


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    company     TEXT NOT NULL,
    title       TEXT NOT NULL,
    location    TEXT,
    url         TEXT,
    description TEXT,
    posted_at   TEXT,
    track       TEXT,
    status      TEXT NOT NULL DEFAULT 'new',  -- new|scored|queued|applied|skipped|seen
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scores (
    job_id      TEXT PRIMARY KEY,
    score       INTEGER,
    verdict     TEXT,
    track_match TEXT,
    strengths   TEXT,
    gaps        TEXT,
    red_flags   TEXT,
    raw_json    TEXT,
    scored_at   TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);

CREATE TABLE IF NOT EXISTS applications (
    job_id        TEXT PRIMARY KEY,
    resume_path   TEXT,
    cover_path    TEXT,
    applied_at    TEXT,
    submitted_at  TEXT,        -- set when extension reports submit
    notes         TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT,
    kind        TEXT NOT NULL,     -- ingest|score|tailor|view|fill|submit|skip|error
    detail      TEXT,
    ts          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stage       TEXT NOT NULL,     -- ingest|score|deliver
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    status      TEXT,              -- ok|error|running
    detail      TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status  ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_track   ON jobs(track);
CREATE INDEX IF NOT EXISTS idx_jobs_posted  ON jobs(posted_at);
CREATE INDEX IF NOT EXISTS idx_scores_score ON scores(score);
CREATE INDEX IF NOT EXISTS idx_events_kind  ON events(kind);
CREATE INDEX IF NOT EXISTS idx_events_job   ON events(job_id);
"""


def init_db() -> None:
    con = connect()
    con.executescript(SCHEMA)
    con.commit()
    con.close()


def log_event(kind: str, job_id: str | None = None, detail: str | None = None) -> None:
    init_db()
    con = connect()
    con.execute(
        "INSERT INTO events (job_id, kind, detail, ts) VALUES (?,?,?,?)",
        (job_id, kind, detail, datetime.now(UTC).isoformat()),
    )
    con.commit()
    con.close()


def start_run(stage: str) -> int:
    init_db()
    con = connect()
    cur = con.execute(
        "INSERT INTO pipeline_runs (stage, started_at, status) VALUES (?,?,?)",
        (stage, datetime.now(UTC).isoformat(), "running"),
    )
    rid = cur.lastrowid
    con.commit()
    con.close()
    return rid


def end_run(run_id: int, status: str, detail: str | None = None) -> None:
    con = connect()
    con.execute(
        "UPDATE pipeline_runs SET ended_at=?, status=?, detail=? WHERE id=?",
        (datetime.now(UTC).isoformat(), status, detail, run_id),
    )
    con.commit()
    con.close()


def upsert_jobs(jobs: list[Job]) -> tuple[int, int]:
    """Insert new jobs, refresh last_seen for existing.

    Duplicate postings often arrive from more than one source. Treat exact
    URL matches and same company/title pairs as the same opportunity so
    reruns do not keep surfacing old jobs through a different feed.

    Returns (new_count, updated_count).
    """
    init_db()
    con = connect()
    now = datetime.now(UTC).isoformat()
    new_count = updated_count = 0
    for j in jobs:
        cur = con.execute(
            """SELECT job_id FROM jobs
               WHERE job_id=?
                  OR (url IS NOT NULL AND url != '' AND url=?)
                  OR (lower(company)=lower(?) AND lower(title)=lower(?))
               ORDER BY first_seen ASC
               LIMIT 1""",
            (j.job_id, j.url, j.company, j.title),
        )
        existing = cur.fetchone()
        if existing:
            con.execute(
                """UPDATE jobs
                   SET last_seen=?,
                       description=COALESCE(NULLIF(description, ''), ?),
                       posted_at=COALESCE(posted_at, ?),
                       location=COALESCE(NULLIF(location, ''), ?)
                   WHERE job_id=?""",
                (now, j.description, j.posted_at, j.location, existing["job_id"]),
            )
            updated_count += 1
        else:
            con.execute(
                """INSERT INTO jobs
                   (job_id, source, company, title, location, url, description,
                    posted_at, track, status, first_seen, last_seen)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (j.job_id, j.source, j.company, j.title, j.location, j.url,
                 j.description, j.posted_at, j.track, "new", now, now),
            )
            new_count += 1
    con.commit()
    con.close()
    return new_count, updated_count
