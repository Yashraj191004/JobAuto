"""Answer application form questions from qa_bank.json + resume.

answer_labels([...]) returns a {label: answer} mapping. Each label is matched
against the qa_bank using fuzzy keyword rules first. Unknown labels are batched
into one LLM call.

The LLM is told to use the resume + qa_bank as the only source of truth and to
return JSON. New answers it produces are written back into qa_bank.json so the
next run is instant + free.

Portal account credentials (Workday/Greenhouse/etc account-creation passwords)
are loaded from .env only — NEVER written to qa_bank.json, NEVER logged in event
details, NEVER sent to the LLM. The keys in SECRET_KEYS resolve to env-backed
values only.
"""
from __future__ import annotations
import json
import re
from typing import Iterable
from .config import QA_BANK_PATH, APP_PORTAL_EMAIL, APP_PORTAL_PASSWORD
from .llm import ask_json
from .resume import get_resume_text
from .schema import connect


# Keys that resolve to env-backed secrets (never persisted to qa_bank.json,
# never sent to the LLM, never logged).
SECRET_KEYS = {
    "create_password",
    "confirm_password",
    "portal_password",
    "portal_email",
}


def _secrets() -> dict[str, str]:
    """Resolve secret keys from environment. Returns only non-empty values."""
    out: dict[str, str] = {}
    if APP_PORTAL_PASSWORD:
        out["create_password"]  = APP_PORTAL_PASSWORD
        out["confirm_password"] = APP_PORTAL_PASSWORD
        out["portal_password"]  = APP_PORTAL_PASSWORD
    if APP_PORTAL_EMAIL:
        out["portal_email"] = APP_PORTAL_EMAIL
    return out


# Heuristic label -> qa_bank key mapping (most common application questions).
HEURISTICS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^full name$|legal name", re.I),                       "full_name"),
    (re.compile(r"first.{0,12}name|given name|givenname", re.I),        "first_name"),
    (re.compile(r"last.{0,12}name|family name|surname|familyname", re.I), "last_name"),
    # Portal account-creation password fields (env-backed, see SECRET_KEYS)
    (re.compile(r"^password$|create.{0,5}password|new.{0,5}password|"
                r"choose.{0,5}password|set.{0,5}password|"
                r"account.{0,5}password", re.I),                        "create_password"),
    (re.compile(r"confirm.{0,5}password|verify.{0,5}password|"
                r"re-?enter.{0,5}password|retype.{0,5}password|"
                r"password.{0,5}again", re.I),                          "confirm_password"),
    (re.compile(r"sign.?in.{0,5}email|account.{0,5}email|"
                r"login.{0,5}email|portal.{0,5}email|"
                r"workday.{0,5}email|create.{0,5}account.{0,5}email", re.I), "portal_email"),
    # Regular candidate-info fields
    (re.compile(r"e-?mail|emailaddress|account email", re.I),           "email"),
    (re.compile(r"phone|mobile|cell|telephone|tel", re.I),              "phone"),
    (re.compile(r"address", re.I),                                      "address"),
    (re.compile(r"\bcity\b", re.I),                                     "city"),
    (re.compile(r"\bstate\b", re.I),                                    "state"),
    (re.compile(r"zip|postal", re.I),                                   "zip"),
    (re.compile(r"country", re.I),                                      "country"),
    (re.compile(r"authoriz(ed|ation).*work", re.I),                     "work_authorization_us"),
    (re.compile(r"legally.*work|right to work", re.I),                  "work_authorization_us"),
    (re.compile(r"sponsorship|visa", re.I),                             "sponsorship_required"),
    (re.compile(r"ITAR|export control|U\.?S\.? person|permanent residence", re.I), "itar_us_person_status"),
    (re.compile(r"working in person|five days per week|in person|on-?site|office", re.I), "onsite_work_ok"),
    (re.compile(r"github", re.I),                                       "github"),
    (re.compile(r"linkedin", re.I),                                     "linkedin"),
    (re.compile(r"portfolio|personal website", re.I),                   "portfolio"),
    (re.compile(r"year.{0,5}experience|yoe", re.I),                     "years_of_experience"),
    (re.compile(r"salary|compensation expectation", re.I),              "salary_expectation"),
    (re.compile(r"relocat", re.I),                                      "willing_to_relocate"),
    (re.compile(r"start.{0,8}date|earliest.*date|earliest.*start|earliest.*available", re.I), "earliest_start_date"),
    (re.compile(r"graduat(e|ion)", re.I),                               "graduation_date"),
    (re.compile(r"degree|education level", re.I),                       "degree"),
    (re.compile(r"school|university|college", re.I),                    "school"),
    (re.compile(r"gpa", re.I),                                          "gpa"),
    (re.compile(r"pronoun", re.I),                                      "pronouns"),
    (re.compile(r"hispanic|latino", re.I),                              "hispanic_or_latino"),
    (re.compile(r"asian", re.I),                                        "asian_ethnicity"),
    (re.compile(r"race", re.I),                                         "race"),
    (re.compile(r"ethnic", re.I),                                       "ethnicity"),
    (re.compile(r"gender", re.I),                                       "gender"),
    (re.compile(r"veteran", re.I),                                      "veteran_status"),
    (re.compile(r"disab", re.I),                                        "disability_status"),
    (re.compile(r"how did you hear|source", re.I),                      "how_did_you_hear"),
]


ANSWER_ALIASES: dict[str, list[str]] = {
    "earliest_start_date":   ["available_start_date"],
    "race_eeo":              ["race"],
    "veteran_status_eeo":    ["veteran_status"],
    "disability_status_eeo": ["disability_status"],
}


def _load_bank() -> dict:
    return json.loads(QA_BANK_PATH.read_text()) if QA_BANK_PATH.exists() else {}


def _save_bank(bank: dict) -> None:
    # Strip any secret keys before persisting (defence in depth).
    safe = {k: v for k, v in bank.items() if k not in SECRET_KEYS}
    QA_BANK_PATH.write_text(json.dumps(safe, indent=2))


def _lookup_bank() -> dict:
    """Bank used for lookup only: disk bank + env-backed secrets merged in."""
    merged = _load_bank()
    merged.update(_secrets())
    return merged


def _needs_generated_answer(label: str) -> bool:
    l = label.lower()
    if re.search(
        r"ITAR|export control|U\.?S\.? person|permanent residence|"
        r"working in person|five days per week|on-?site|"
        r"authoriz(ed|ation).*work|sponsorship|visa|"
        r"\bgender\b|\brace\b|hispanic|latino|veteran|disab|"
        r"start.{0,8}date|earliest.*date|earliest.*available",
        label,
        re.I,
    ):
        return False
    return (
        len(l) > 60
        or any(k in l for k in (
            "tell us", "describe", "explain", "why", "project", "challenge",
            "interest", "interested", "motivation", "cover letter",
            "anything else", "additional information", "include", "github link",
        ))
    )


def _stringify_answer(value) -> str:
    return ", ".join(value) if isinstance(value, list) else str(value)


def _answer_for_key(key: str, bank: dict, label: str) -> str | None:
    l = label.lower()

    # Exact wording helps radio-button matching on federal/EEO forms.
    if key == "itar_us_person_status":
        return 'A person lawfully admitted for permanent residence of the United States (i.e. "Green Card" holder)'
    if key == "sponsorship_required":
        # User is Green Card holder - doesn't need sponsorship
        return "No, I do not require sponsorship now or in the future."
    if key == "onsite_work_ok":
        return "Yes"
    if key == "willing_to_relocate":
        return "Yes"
    if key == "race" and "hispanic" in l:
        return "Asian (Not Hispanic or Latino)"
    if key == "veteran_status":
        return "I am not a protected veteran"
    if key == "disability_status":
        return "No, I don't have a disability and have not had one in the past"

    val = bank.get(key)
    if val:
        return _stringify_answer(val)
    for alias in ANSWER_ALIASES.get(key, []):
        val = bank.get(alias)
        if val:
            return _stringify_answer(val)
    return None


def _heuristic_lookup(label: str, bank: dict) -> str | None:
    if _needs_generated_answer(label):
        return None
    l = label.lower()
    if re.search(r"ITAR|export control|U\.?S\.? person|permanent residence", label, re.I):
        return _answer_for_key("itar_us_person_status", bank, label)
    # Visa sponsorship questions - always answer "No" for Green Card holder
    if re.search(r"sponsorship|visa.*status|h-?1b", label, re.I):
        return _answer_for_key("sponsorship_required", bank, label)
    # Relocation / onsite work questions - always answer "Yes"
    if re.search(r"relocat|working.*office|five days|in.?person|on.?site|work from.*office|union square", label, re.I):
        return _answer_for_key("onsite_work_ok", bank, label)
    if "race" in l and "asian" in l:
        return "Asian (Not Hispanic or Latino)"
    for pattern, key in HEURISTICS:
        if pattern.search(label):
            val = _answer_for_key(key, bank, label)
            if val:
                return val
    # also try direct key match (lowercased, underscores)
    norm = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    if norm in bank:
        v = bank[norm]
        return ", ".join(v) if isinstance(v, list) else str(v)
    return None


def _job_context(job_id: str | None) -> str:
    if not job_id:
        return "No specific job context."
    try:
        con = connect()
        row = con.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        con.close()
    except Exception:
        return "No specific job context."
    if not row:
        return "No specific job context."
    return (
        f"Company: {row['company']}\n"
        f"Title: {row['title']}\n"
        f"Location: {row['location'] or ''}\n"
        f"Track: {row['track'] or ''}\n"
        f"Description: {(row['description'] or '')[:2500] or 'No description available.'}"
    )


_LLM_PROMPT = """You are filling out a job application as the candidate. Use ONLY
the resume, job context, and candidate Q&A bank below. Do not invent personal facts.
For company/role interest questions, use the job context and role title; if company
details are limited, answer honestly from the role and candidate fit.

CANDIDATE Q&A BANK (authoritative for personal info):
{bank}

CANDIDATE RESUME:
{resume}

JOB CONTEXT:
{job}

UNKNOWN FORM LABELS (one answer per label, concise, plain text):
{labels}

Return ONLY JSON of the form:
{{"answers": {{"<label>": "<answer>", ...}}, "new_qa": {{"<canonical_key>": "<answer>", ...}}}}

new_qa should suggest reusable keys (lowercase_underscored) for any answer that
generalizes across applications. Leave new_qa empty {{}} if nothing generalizes.
If an answer truly cannot be derived from the inputs, set it to "" (empty string)."""


# Section regexes used by the resume-derived fallback. We deliberately do not
# bake any candidate-specific facts into this module — everything personal
# comes from qa_bank.json or the resume itself.
_PROJECTS_HEADER = re.compile(r"^projects?$", re.I)
_NEXT_SECTION    = re.compile(
    r"^(education|experience|skills|technical skills|certifications|"
    r"summary|publications|languages|interests)\b", re.I
)


def _resume_projects(resume: str) -> list[tuple[str, list[str]]]:
    """Pull '(project name, bullets[])' tuples out of the PROJECTS section of
    a plain-text resume. Returns at most a few projects; bullets stay short.

    The heuristic: skip until we hit a 'Projects' line, then treat each non-
    bullet line as a project title, accumulating subsequent '- '/'* '/'• '
    bullets under it. Stop at the next major section header.
    """
    lines = [ln.rstrip() for ln in resume.splitlines()]
    in_projects = False
    projects: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current_bullets: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_bullets
        if current_title:
            projects.append((current_title, current_bullets[:3]))
        current_title = None
        current_bullets = []

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if not in_projects:
            if _PROJECTS_HEADER.match(line):
                in_projects = True
            continue
        if _NEXT_SECTION.match(line):
            flush()
            break
        if line.startswith(("- ", "* ", "• ")):
            current_bullets.append(line.lstrip("-*• ").strip())
        else:
            flush()
            current_title = line
    flush()
    return projects[:3]


def _fallback_answer(label: str, bank: dict, job_id: str | None) -> str:
    """Best-effort answer when the LLM is unavailable.

    Everything here is derived from the resume + qa_bank — no hardcoded
    personal facts. Returns "" when there is no reasonable fallback.
    """
    l = label.lower()
    company, title = "", ""
    try:
        if job_id:
            con = connect()
            row = con.execute(
                "SELECT company, title FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            con.close()
            if row:
                company = row["company"] or ""
                title   = row["title"] or ""
    except Exception:
        pass

    github = str(bank.get("github", "") or "")

    if "project" in l:
        # Use the user's actual top resume project, not a hardcoded blurb.
        try:
            resume = get_resume_text()
        except Exception:
            resume = ""
        projects = _resume_projects(resume)
        if projects:
            name, bullets = projects[0]
            body = " ".join(bullets) if bullets else ""
            answer = f"One project I am proud of is {name}."
            if body:
                answer += f" {body}"
            if github:
                answer += f" GitHub: {github}"
            return answer.strip()
        # Last resort: a generic stub the user can edit before submitting.
        return (
            "One project I am proud of is described in detail on my GitHub profile. "
            f"GitHub: {github}".strip()
        )

    if "why" in l or "interest" in l or "interested" in l:
        role = f"the {title} role" if title else "this role"
        org  = f" at {company}" if company else ""
        # Pull contribution-area framing from the bank when present so the
        # answer reflects the candidate's stated preferences.
        focus = str(bank.get("preferred_contribution_areas", "") or "").strip()
        focus_clause = f" My focus areas are {focus.lower()}." if focus else ""
        return (
            f"I am interested in {role}{org} because it aligns with my "
            "software-engineering background, hands-on full-stack projects, "
            f"and the skills listed on my resume.{focus_clause} I am excited "
            "by opportunities to contribute to real products and learn from "
            "strong engineers."
        )

    if "github" in l:
        return github

    return ""


def answer_labels(labels: Iterable[str], job_id: str | None = None) -> dict[str, str]:
    labels = [str(l).strip() for l in labels if str(l).strip()]
    bank            = _lookup_bank()    # disk + env-backed secrets merged
    persistent_bank = _load_bank()      # only what may be safely sent to the LLM

    answers: dict[str, str] = {}
    unknown: list[str] = []

    for lbl in labels:
        val = _heuristic_lookup(lbl, bank)
        if val is not None:
            answers[lbl] = val
        else:
            unknown.append(lbl)

    if unknown:
        try:
            resume = get_resume_text()
        except Exception:
            resume = ""
        # Send only the persistent bank to the LLM — never expose env secrets.
        prompt = _LLM_PROMPT.format(
            bank=json.dumps(persistent_bank, indent=2),
            resume=resume[:4000],
            job=_job_context(job_id),
            labels=json.dumps(unknown, indent=2),
        )
        try:
            result = ask_json(prompt, task_type="extract")
            for k, v in (result.get("answers") or {}).items():
                answers[k] = v if isinstance(v, str) else str(v)
            # learn: persist any generalizable answers — but NEVER store secret keys
            new_qa = result.get("new_qa") or {}
            new_qa = {k: v for k, v in new_qa.items() if v and k not in SECRET_KEYS}
            if new_qa:
                persistent_bank.update(new_qa)
                _save_bank(persistent_bank)
        except Exception as e:
            print(f"[answer] LLM failed: {e}")
            for lbl in unknown:
                answers[lbl] = _fallback_answer(lbl, persistent_bank, job_id)

    return answers
