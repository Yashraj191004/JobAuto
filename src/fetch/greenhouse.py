"""Greenhouse Job Board API — free, public, no auth required.

API:
    GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
"""
from __future__ import annotations
import requests
from ..schema import Job


def fetch(board_token: str, company_name: str | None = None, timeout: int = 20) -> list[Job]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"
    try:
        r = requests.get(url, params={"content": "true"}, timeout=timeout)
    except Exception as e:
        print(f"[greenhouse:{board_token}] request failed: {e}")
        return []
    if r.status_code != 200:
        return []
    data = r.json()
    company = company_name or board_token

    out: list[Job] = []
    for j in data.get("jobs", []):
        out.append(Job(
            source="greenhouse",
            company=company,
            title=j.get("title", ""),
            location=(j.get("location") or {}).get("name", ""),
            url=j.get("absolute_url", ""),
            description=j.get("content"),     # HTML; stripped later when scoring
            posted_at=j.get("updated_at") or j.get("first_published"),
            track=None,                       # filled by normalize
            raw=j,
        ))
    return out
