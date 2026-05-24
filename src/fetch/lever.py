"""Lever postings API — free, public, no auth required.

API:
    GET https://api.lever.co/v0/postings/{company}?mode=json
"""
from __future__ import annotations
import requests
from datetime import datetime, timezone
from ..schema import Job


def _ms_to_iso(ms) -> str | None:
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return None


def _lever_location(categories: dict) -> str:
    """Prefer `categories.location`; fall back to the first allLocations entry.

    The previous implementation had a precedence bug:

        cats.get("location", "")
        or cats.get("allLocations", [""])[0]
            if cats.get("allLocations")
            else cats.get("location", "")

    Python parses this as `A or (B if C else A)`, so when both `location` and
    `allLocations` are present, we needlessly compute `allLocations[0]` and
    `location` always wins anyway. When `location` is empty but `allLocations`
    is missing entirely, the ternary's else branch returns `""` — fine — but
    the whole expression depends on a brittle truthiness chain. This rewrite
    is explicit instead.
    """
    primary = categories.get("location") or ""
    if primary:
        return primary
    all_locations = categories.get("allLocations") or []
    if all_locations:
        return all_locations[0] or ""
    return ""


def fetch(board_token: str, company_name: str | None = None, timeout: int = 20) -> list[Job]:
    url = f"https://api.lever.co/v0/postings/{board_token}"
    try:
        r = requests.get(url, params={"mode": "json"}, timeout=timeout)
    except Exception as e:
        print(f"[lever:{board_token}] request failed: {e}")
        return []
    if r.status_code != 200:
        return []
    company = company_name or board_token

    out: list[Job] = []
    for j in r.json():
        cats = j.get("categories") or {}
        out.append(Job(
            source="lever",
            company=company,
            title=j.get("text", ""),
            location=_lever_location(cats),
            url=j.get("hostedUrl", ""),
            description=j.get("descriptionPlain") or j.get("description"),
            posted_at=_ms_to_iso(j.get("createdAt")),
            track=None,
            raw=j,
        ))
    return out
