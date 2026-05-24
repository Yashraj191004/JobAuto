"""Broad keyword search across Indeed/LinkedIn/Glassdoor via JSearch.

Skipped silently if RAPIDAPI_KEY is not set. Query volume is controlled by
search_profile.yaml so you can trade coverage against free-tier quota.
"""
from __future__ import annotations
import requests
from datetime import datetime, timezone
from ..config import RAPIDAPI_KEY
from ..schema import Job

ENDPOINT = "https://jsearch.p.rapidapi.com/search-v2"


class JSearchUnavailable(RuntimeError):
    """Raised when the JSearch endpoint indicates we cannot keep calling it
    (bad key, no subscription, or quota exhausted)."""


def _ms_to_iso(ms) -> str | None:
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(int(ms), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _date_window(days: int | None) -> str:
    if not days:
        return "month"
    if days <= 1:
        return "today"
    if days <= 3:
        return "3days"
    if days <= 7:
        return "week"
    return "month"


def _one_query(query: str, page: int = 1, date_posted: str = "month") -> list[dict]:
    headers = {
        "x-rapidapi-key":  RAPIDAPI_KEY,
        "x-rapidapi-host": "jsearch.p.rapidapi.com",
    }
    params = {
        "query":       query,
        "page":        str(page),
        "num_pages":   "1",
        "country":     "us",
        "date_posted": date_posted,
    }
    r = requests.get(ENDPOINT, headers=headers, params=params, timeout=30)
    if r.status_code in (401, 403):
        raise JSearchUnavailable("RapidAPI rejected the JSearch key or subscription")
    if r.status_code == 429:
        raise JSearchUnavailable("RapidAPI JSearch quota/rate limit reached")
    r.raise_for_status()
    payload = r.json()
    data = payload.get("data", []) if isinstance(payload, dict) else []
    if isinstance(data, dict):
        return data.get("jobs") or data.get("results") or data.get("data") or []
    return data or []


def search(
    targets: list[dict],
    locations_include: list[str],
    filters: dict | None = None,
) -> list[Job]:
    if not RAPIDAPI_KEY:
        print("[jsearch] RAPIDAPI_KEY not set; skipping")
        return []

    filters = filters or {}
    pages_per_query = max(1, min(int(filters.get("jsearch_pages_per_query") or 1), 5))
    query_count     = max(1, min(int(filters.get("jsearch_query_count_per_track") or 1), 8))
    date_posted     = _date_window(filters.get("posted_within_days"))

    out: list[Job] = []
    location_str = "United States"

    for target in targets:
        titles = (target.get("titles") or ["software engineer"])[:query_count]
        for title in titles:
            query = f"{title} {location_str}"
            for page in range(1, pages_per_query + 1):
                try:
                    for li in _one_query(query, page=page, date_posted=date_posted):
                        out.append(Job(
                            source="jsearch",
                            company=li.get("employer_name", "") or "",
                            title=li.get("job_title", "") or "",
                            location=li.get("job_city") or li.get("job_country") or "",
                            url=li.get("job_apply_link") or li.get("job_google_link") or "",
                            description=li.get("job_description"),
                            posted_at=_ms_to_iso(li.get("job_posted_at_timestamp")),
                            track=target.get("track"),
                            raw=li,
                        ))
                except JSearchUnavailable as e:
                    print(f"[jsearch] disabled: {e}")
                    return out
                except Exception as e:
                    print(f"[jsearch] query '{query}' page {page} failed: {e}")

    return out
