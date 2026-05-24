"""Score 'new' jobs against the resume + profile. Updates SQLite.

Public:
    score_one(job_id) -> dict   # score exactly one selected job
    run(limit, tracks) -> dict  # batch-score all 'new' jobs
"""
from __future__ import annotations
import json
import re
from datetime import datetime, UTC
from .config import load_profile
from .schema import connect, init_db, start_run, end_run, log_event
from .llm import ask_json
from .resume import get_resume_text

SCORE_PROMPT = """Score this job fit for the candidate. Return ONLY JSON.

Candidate: graduating {graduation}; {authorization}; needs sponsorship: {needs_sponsorship}.
Target track: {track}
Resume summary:
{resume}

Job: {company} | {title} | {location}
Description:
{description}

JSON schema:
{{
  "score": <integer 1-10>,
  "track_match": "{track}" or "none",
  "verdict": "apply" | "maybe" | "skip",
  "strengths": [<up to 3 short bullets>],
  "gaps": [<up to 3 short bullets>],
  "red_flags": [<up to 3 short bullets>]
}}"""


# Section headers commonly seen in resumes. We keep lines under these headers
# plus all bullet lines, regardless of whose resume this is.
_SECTION_HEADERS = re.compile(
    r"^(education|experience|projects?|technical skills|skills|"
    r"summary|objective|certifications|publications|work authorization|"
    r"languages|web development|databases|tools|concepts|"
    r"operating systems)\b",
    re.IGNORECASE,
)


def _resume_summary(resume: str, limit: int = 1800) -> str:
    """Compact the resume for prompt budget.

    Heuristic: keep section headers (Education / Experience / Projects / Skills
    / Summary / Certifications / etc.) and all bullet lines (lines starting
    with '-', '*', or '•'). Stop once we hit the character budget. This is
    resume-agnostic — no candidate-specific keywords.
    """
    lines: list[str] = []
    running = 0
    for raw in resume.splitlines():
        line = raw.strip()
        if not line:
            continue
        keep = (
            _SECTION_HEADERS.match(line)
            or line.startswith(("- ", "* ", "• "))
            or ":" in line[:30]      # short "Key: value" lines (skills, GPA, etc.)
        )
        if not keep:
            continue
        running += len(line) + 1
        if running > limit:
            break
        lines.append(line)

    summary = "\n".join(lines)
    return summary[:limit] or resume[:limit]


def _prompt_for(job_row, profile, resume) -> str:
    track = job_row["track"] or "none"
    return SCORE_PROMPT.format(
        graduation=profile["profile"].get("graduation", ""),
        authorization=profile["profile"].get("authorization", ""),
        needs_sponsorship=profile["profile"].get("needs_sponsorship", False),
        resume=_resume_summary(resume),
        company=job_row["company"],
        title=job_row["title"],
        location=job_row["location"] or "",
        track=track,
        description=(job_row["description"] or "No description provided.")[:1800],
    )


def _write_score(con, row, result: dict) -> None:
    con.execute(
        """INSERT OR REPLACE INTO scores
           (job_id, score, verdict, track_match, strengths, gaps, red_flags, raw_json, scored_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            row["job_id"],
            int(result.get("score") or 0),
            result.get("verdict") or "skip",
            result.get("track_match") or "none",
            json.dumps(result.get("strengths") or []),
            json.dumps(result.get("gaps") or []),
            json.dumps(result.get("red_flags") or []),
            json.dumps(result),
            datetime.now(UTC).isoformat(),
        ),
    )
    con.execute("UPDATE jobs SET status='scored' WHERE job_id=?", (row["job_id"],))
    con.commit()


def _score_row(con, row, profile, resume) -> bool:
    prompt = _prompt_for(row, profile, resume)
    try:
        result = ask_json(prompt, task_type="score")
    except Exception as e:
        print(f"[score] {row['job_id']} failed: {e}")
        log_event("error", job_id=row["job_id"], detail=f"score: {e}")
        result = _fallback_score(row)
    _write_score(con, row, result)
    return True


def _fallback_score(row) -> dict:
    """Deterministic backup when CLI providers are unavailable or slow."""
    title = (row["title"] or "").lower()
    desc  = (row["description"] or "").lower()
    track = row["track"] or "none"
    text  = f"{title} {desc}"

    score = 5
    strengths: list[str] = []
    gaps:      list[str] = []
    red_flags: list[str] = []

    if track in ("internship", "new_grad", "regular_sde"):
        score += 2
        strengths.append("Software engineering track matches candidate projects and skills.")
    if any(k in text for k in ("python", "javascript", "react", "flask", "node", "sql", "ai", "automation")):
        score += 1
        strengths.append("Relevant technical keywords overlap with resume.")
    if "intern" in title and track == "internship":
        score += 1
        strengths.append("Internship level aligns with graduation timeline.")
    if any(k in text for k in ("senior", "staff", "principal", "lead", "manager")):
        score -= 3
        red_flags.append("Title appears above entry-level.")
    if any(k in text for k in ("5+ years", "5 years", "7+ years", "10+ years")):
        score -= 2
        red_flags.append("Description may require more experience.")
    if any(k in text for k in ("sponsorship not", "no sponsorship", "clearance required")):
        red_flags.append("Potential authorization or clearance constraint.")

    score = max(1, min(10, score))
    if score >= 7:
        verdict = "apply"
    elif score >= 5:
        verdict = "maybe"
    else:
        verdict = "skip"
    if not gaps:
        gaps.append("LLM scorer unavailable; review manually before applying.")
    return {
        "score": score,
        "track_match": track,
        "verdict": verdict,
        "strengths": strengths[:3] or ["Role broadly matches configured track."],
        "gaps":      gaps[:3],
        "red_flags": red_flags[:3],
        "fallback":  True,
    }


def score_one(job_id: str) -> dict:
    """Score exactly one selected job."""
    init_db()
    run_id = start_run("score")
    try:
        profile = load_profile()
        resume  = get_resume_text()
        con     = connect()
        row = con.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            con.close()
            raise ValueError(f"Job not found: {job_id}")
        scored = 1 if _score_row(con, row, profile, resume) else 0
        con.close()
        detail = f"job_id={job_id} scored={scored}"
        log_event("score", job_id=job_id, detail=detail)
        end_run(run_id, "ok", detail)
        return {"scored": scored}
    except Exception as e:
        end_run(run_id, "error", str(e))
        log_event("error", job_id=job_id, detail=f"score_one: {e}")
        raise


def run(limit: int | None = None, tracks: list[str] | None = None) -> dict:
    init_db()
    run_id = start_run("score")
    try:
        profile = load_profile()
        resume  = get_resume_text()

        con = connect()
        clauses = ["status='new'"]
        params: list = []
        if tracks:
            clauses.append(f"track IN ({','.join('?' * len(tracks))})")
            params.extend(tracks)
        rows = con.execute(
            "SELECT * FROM jobs WHERE " + " AND ".join(clauses)
            + " ORDER BY first_seen DESC"
            + (f" LIMIT {int(limit)}" if limit else ""),
            params,
        ).fetchall()
        print(f"[score] {len(rows)} jobs to score")

        scored = 0
        for row in rows:
            if _score_row(con, row, profile, resume):
                scored += 1
            if scored and scored % 10 == 0:
                print(f"[score]   … {scored}/{len(rows)}")
        con.close()
        print(f"[score] done: {scored} scored")
        log_event("score", detail=f"scored={scored}")
        end_run(run_id, "ok", f"scored={scored}")
        return {"scored": scored}
    except Exception as e:
        end_run(run_id, "error", str(e))
        log_event("error", detail=f"score: {e}")
        raise


if __name__ == "__main__":
    run()
