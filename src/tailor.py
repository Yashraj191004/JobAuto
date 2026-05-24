"""Generate tailored resume bullets + cover letter for a specific job."""
from __future__ import annotations
from .schema import connect, init_db
from .config import OUTPUTS_DIR
from .llm import ask
from .resume import get_resume_text

RESUME_PROMPT = """You are rewriting a resume for a specific job application.

Goal: surface the candidate's most relevant experience, align language with the
job description for ATS keyword matching, and keep all content factual to the
original resume. Use exact technologies, role names, and requirement language
from the job only when the resume supports them. Do NOT invent experience,
skills, metrics, education, authorization, or dates.

ORIGINAL RESUME:
{resume}

JOB:
Company: {company}
Title:   {title}
Location: {location}

JOB DESCRIPTION:
{description}

Return a tailored Markdown resume. Reorder bullets so the most JD-relevant ones
appear first under each role. Keep section structure. Add a one-line "Summary"
at the top tied to this role. Add a short "Core Skills" line using only skills
present in the resume and relevant to the job description.
"""

COVER_PROMPT = """Write a concise cover letter (max 250 words) for the job below.
Use only facts present in the resume. Tone: confident, specific, no clichés.

CANDIDATE RESUME:
{resume}

JOB:
Company: {company}
Title:   {title}

JOB DESCRIPTION:
{description}

Return ONLY the cover letter body (no header, no signature).
"""


def _fmt(template: str, row, resume: str) -> str:
    return template.format(
        resume=resume[:8000],
        company=row["company"],
        title=row["title"],
        location=row["location"] or "",
        description=(row["description"] or "")[:6000],
    )


def tailor(job_id: str) -> dict:
    init_db()
    con = connect()
    row = con.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if not row:
        raise SystemExit(f"job {job_id} not found")
    resume = get_resume_text()

    out_dir = OUTPUTS_DIR / f"{row['company'].replace(' ', '_')}_{job_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[tailor] {row['company']} — {row['title']}")
    resume_md = ask(_fmt(RESUME_PROMPT, row, resume), task_type="tailor")
    cover_md  = ask(_fmt(COVER_PROMPT,  row, resume), task_type="cover")

    resume_path = out_dir / "resume.md"
    cover_path  = out_dir / "cover_letter.md"
    resume_path.write_text(resume_md)
    cover_path.write_text(cover_md)

    con.execute(
        """INSERT OR REPLACE INTO applications
           (job_id, resume_path, cover_path, applied_at, notes)
           VALUES (?, ?, ?, NULL, NULL)""",
        (job_id, str(resume_path), str(cover_path)),
    )
    con.execute("UPDATE jobs SET status='queued' WHERE job_id=?", (job_id,))
    con.commit()
    con.close()

    print(f"[tailor] → {resume_path}")
    print(f"[tailor] → {cover_path}")
    return {"resume": str(resume_path), "cover": str(cover_path)}
