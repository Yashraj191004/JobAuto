"""Single source of truth for paths, env vars, and the user's search profile."""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv
import yaml

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Paths
KNOWLEDGE_DIR = ROOT / "knowledge"
DB_DIR        = ROOT / "db"
OUTPUTS_DIR   = ROOT / "outputs"
PROFILE_PATH  = ROOT / "search_profile.yaml"
RESUME_PDF    = KNOWLEDGE_DIR / "resume.pdf"
RESUME_TXT    = KNOWLEDGE_DIR / "resume.txt"
QA_BANK_PATH  = KNOWLEDGE_DIR / "qa_bank.json"
JOBS_DB       = DB_DIR / "jobs.db"
CACHE_DB      = DB_DIR / "llm_cache.db"

for d in (KNOWLEDGE_DIR, DB_DIR, OUTPUTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Env — LLM / discovery
RAPIDAPI_KEY        = os.getenv("RAPIDAPI_KEY", "")
COPILOT_ASK_COMMAND = os.getenv("COPILOT_ASK_COMMAND", "")
CHATGPT_ASK_COMMAND = os.getenv("CHATGPT_ASK_COMMAND", "")
CODEX_MODEL            = os.getenv("CODEX_MODEL", "")
CODEX_REASONING_EFFORT = os.getenv("CODEX_REASONING_EFFORT", "low")

_score_limit_raw = os.getenv("DEFAULT_SCORE_LIMIT", "0").strip()
DEFAULT_SCORE_LIMIT = int(_score_limit_raw) if _score_limit_raw else 0

# Portal account credentials — used by the extension when a Workday/Greenhouse/etc
# application asks you to create or sign in to an account. Loaded from .env only;
# NEVER written to qa_bank.json, NEVER logged, NEVER sent to the LLM.
APP_PORTAL_EMAIL    = os.getenv("APP_PORTAL_EMAIL", "")
APP_PORTAL_PASSWORD = os.getenv("APP_PORTAL_PASSWORD", "")


def find_document(kind: str) -> Path | None:
    """Find a local upload document by kind for browser-extension hints.

    Looks in knowledge/ and outputs/ for the most recently modified file
    matching the kind's filename patterns. Returns None when nothing matches.
    """
    patterns = {
        "resume":     ["*resume*.pdf", "*resume*.docx", "*resume*.doc"],
        "transcript": ["*transcript*.pdf", "*transcript*.docx",
                       "*transcript*.doc", "*tsrpt*.pdf"],
    }.get(kind, [])
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(KNOWLEDGE_DIR.glob(pattern))
        candidates.extend(OUTPUTS_DIR.glob(pattern))
    files = [p for p in candidates if p.is_file()]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def load_profile() -> dict:
    with open(PROFILE_PATH) as f:
        return yaml.safe_load(f)
