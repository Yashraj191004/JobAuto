"""SimplifyJobs publishes two community-maintained GitHub repos with JSON
dumps of current New Grad and Internship listings, updated multiple times
daily.

We pull the JSON directly from GitHub raw — no API key, no rate-limit issues
for personal use.

Public:
    fetch_all() -> list[Job]
"""
from __future__ import annotations
import requests
from datetime import datetime, timezone
from ..schema import Job

SOURCES = [
    {
        "url":   "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json",
        "track": "new_grad",
        "tag":   "simplifyjobs_newgrad",
    },
    {
        "url":   "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json",
        "track": "internship",
        "tag":   "simplifyjobs_intern",
    },
]


def _ts_to_iso(ts) -> str | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _fetch_one(source: dict) -> list[Job]:
    r = requests.get(source["url"], timeout=30)
    r.raise_for_status()
    listings = r.json()

    jobs: list[Job] = []
    for li in listings:
        # SimplifyJobs schema:
        #   company_name, title, location(s), url, date_posted, active, is_visible
        if not li.get("active", True):
            continue
        if li.get("is_visible") is False:
            continue
        locations = li.get("locations") or [li.get("location", "")]
        location  = "; ".join([loc for loc in locations if loc]) or ""

        jobs.append(Job(
            source=source["tag"],
            company=li.get("company_name", "") or li.get("company", ""),
            title=li.get("title", ""),
            location=location,
            url=li.get("url", "") or li.get("application_url", ""),
            description=None,                 # not provided; fetched later if needed
            posted_at=_ts_to_iso(li.get("date_posted")),
            track=source["track"],
            raw=li,
        ))
    return jobs


def fetch_all() -> list[Job]:
    out: list[Job] = []
    for src in SOURCES:
        try:
            out.extend(_fetch_one(src))
        except Exception as e:
            print(f"[simplifyjobs] {src['tag']} failed: {e}")
    return out


if __name__ == "__main__":
    js = fetch_all()
    print(f"Fetched {len(js)} listings from SimplifyJobs repos")
    for j in js[:5]:
        print(" ", j.company, "|", j.title, "|", j.location)
