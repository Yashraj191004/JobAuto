"""Local HTTP API used by the Chrome extension.

Endpoints:
  GET  /health                        → {"ok": true, "counts": {...}}
  GET  /queue                         → list of queued jobs (+ tailored doc paths)
  GET  /documents                     → {resume, transcript} paths on disk
  GET  /apply/<job_id>                → 302 to the job URL, marks queued + logs
  POST /activate/<job_id>             → same as /apply, no redirect
  GET  /active_application            → currently-open job, if recent
  POST /answer        body: {labels: [...], job_id?: ...}  → {"answers": {...}}
  POST /event         body: {job_id, kind, detail?}        → {"ok": true}
  POST /mark_applied  body: {job_id, url?}                 → {"ok": true}

Run:
    python -m src.server     # serves on 127.0.0.1:8765

The extension hits http://127.0.0.1:8765 with CORS open to all origins, since
this is a personal localhost service. Nothing is exposed to the network.
"""
from __future__ import annotations
import json
from datetime import datetime, UTC, timedelta
from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
from .schema import connect, init_db, log_event
from .answer import answer_labels
from .config import find_document

app = Flask(__name__)
CORS(app)   # allow Chrome extension origin


def _activate_job(job_id: str):
    init_db()
    con = connect()
    row = con.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if not row:
        con.close()
        return None

    now = datetime.now(UTC).isoformat()
    if row["status"] not in ("queued", "applied", "skipped"):
        con.execute("UPDATE jobs SET status='queued' WHERE job_id=?", (job_id,))
    con.execute(
        "INSERT INTO events (job_id, kind, detail, ts) VALUES (?,?,?,?)",
        (job_id, "view", "apply_open", now),
    )
    con.commit()
    row = con.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    con.close()
    return row


@app.get("/")
def index():
    return jsonify({
        "ok": True,
        "service": "JobAuto local API",
        "dashboard": "http://localhost:8501",
        "health": "http://127.0.0.1:8765/health",
        "message": (
            "This is the extension API server. "
            "Open the Streamlit dashboard at http://localhost:8501."
        ),
    })


@app.get("/health")
def health():
    init_db()
    con = connect()
    counts = {}
    for s in ("new", "scored", "queued", "applied", "skipped"):
        counts[s] = con.execute(
            "SELECT COUNT(*) FROM jobs WHERE status=?", (s,)
        ).fetchone()[0]
    con.close()
    return jsonify({"ok": True, "counts": counts, "ts": datetime.now(UTC).isoformat()})


@app.get("/queue")
def queue():
    init_db()
    con = connect()
    rows = con.execute(
        """SELECT j.*, a.resume_path, a.cover_path
           FROM jobs j LEFT JOIN applications a ON a.job_id = j.job_id
           WHERE j.status IN ('queued','scored','applied')
           ORDER BY j.first_seen DESC"""
    ).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])


@app.get("/documents")
def documents():
    docs = {}
    for kind in ("resume", "transcript"):
        path = find_document(kind)
        docs[kind] = str(path) if path else ""
    return jsonify({"ok": True, "documents": docs})


@app.get("/apply/<job_id>")
def open_apply(job_id: str):
    row = _activate_job(job_id)
    if not row:
        return jsonify({"ok": False, "error": "job not found"}), 404
    url = row["url"] or "http://localhost:8501"
    if "jobagent_autofill=1" not in url:
        sep = "&" if "#" in url else "#"
        url = f"{url}{sep}jobagent_autofill=1"
    return redirect(url)


@app.post("/activate/<job_id>")
def activate(job_id: str):
    row = _activate_job(job_id)
    if not row:
        return jsonify({"ok": False, "error": "job not found"}), 404
    return jsonify({"ok": True, "job": dict(row)})


@app.get("/active_application")
def active_application():
    init_db()
    con = connect()
    row = con.execute(
        """SELECT j.*, e.ts AS opened_at
           FROM events e JOIN jobs j ON j.job_id = e.job_id
           WHERE e.kind='view' AND e.detail='apply_open'
             AND j.status IN ('queued','scored','applied')
           ORDER BY e.id DESC
           LIMIT 1"""
    ).fetchone()
    con.close()

    if not row:
        return jsonify({"ok": True, "job": None})

    opened_at = None
    try:
        opened_at = datetime.fromisoformat(row["opened_at"])
    except (TypeError, ValueError):
        pass
    if opened_at and datetime.now(UTC) - opened_at > timedelta(minutes=30):
        return jsonify({"ok": True, "job": None})

    return jsonify({"ok": True, "job": dict(row)})


@app.post("/answer")
def answer():
    data   = request.get_json(force=True) or {}
    labels = data.get("labels") or []
    job_id = data.get("job_id")
    answers = answer_labels(labels, job_id=job_id)
    log_event("fill", job_id=job_id, detail=json.dumps({"labels": labels[:10]}))
    return jsonify({"answers": answers})


@app.post("/event")
def event():
    data = request.get_json(force=True) or {}
    log_event(
        kind=data.get("kind", "view"),
        job_id=data.get("job_id"),
        detail=data.get("detail"),
    )
    return jsonify({"ok": True})


@app.post("/mark_applied")
def mark_applied():
    data   = request.get_json(force=True) or {}
    job_id = data.get("job_id")
    if not job_id:
        return jsonify({"ok": False, "error": "job_id required"}), 400
    init_db()
    con = connect()
    con.execute("UPDATE jobs SET status='applied' WHERE job_id=?", (job_id,))
    now = datetime.now(UTC).isoformat()
    con.execute(
        """INSERT INTO applications (job_id, applied_at, submitted_at)
           VALUES (?, ?, ?)
           ON CONFLICT(job_id) DO UPDATE SET
               applied_at   = excluded.applied_at,
               submitted_at = excluded.submitted_at""",
        (job_id, now, now),
    )
    con.commit()
    con.close()
    log_event("submit", job_id=job_id, detail=data.get("url"))
    return jsonify({"ok": True})


def main() -> None:
    print("[server] http://127.0.0.1:8765")
    app.run(host="127.0.0.1", port=8765, debug=False)


if __name__ == "__main__":
    main()
