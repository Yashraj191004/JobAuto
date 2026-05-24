"""Ashby public job board API — free, no auth.

API:
    GET https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true
"""
from __future__ import annotations
import requests
from ..schema import Job


def fetch(board_token: str, company_name: str | None = None, timeout: int = 20) -> list[Job]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board_token}"
    try:
        r = requests.get(url, params={"includeCompensation": "true"}, timeout=timeout)
    except Exception as e:
        print(f"[ashby:{board_token}] request failed: {e}")
        return []
    if r.status_code != 200:
        return []
    data = r.json()
    company = company_name or board_token

    out: list[Job] = []
    for j in data.get("jobs", []):
        out.append(Job(
            source="ashby",
            company=company,
            title=j.get("title", ""),
            location=j.get("location") or "",
            url=j.get("jobUrl") or j.get("applyUrl", ""),
            description=j.get("descriptionPlain") or j.get("description"),
            posted_at=j.get("publishedAt"),
            track=None,
            raw=j,
        ))
    return out
