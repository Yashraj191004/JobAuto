"""Discover companies + their ATS via the YC OSS directory.

The community-maintained YC OSS list publishes a JSON of every YC company
along with their careers page. We use that to seed our fetchers — no
hardcoded list.

Public:
    list_companies() -> list[dict]    # each has at least: name, ats, board_token, careers_url
"""
from __future__ import annotations
import re
import requests

YC_COMPANIES_JSON = "https://yc-oss.github.io/api/companies/all.json"

ATS_HOST_PATTERNS = {
    "greenhouse": [
        re.compile(r"boards\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9\-]+)", re.I),
        re.compile(r"job-boards\.greenhouse\.io/([a-z0-9\-]+)", re.I),
    ],
    "lever": [
        re.compile(r"jobs\.lever\.co/([a-z0-9\-]+)", re.I),
    ],
    "ashby": [
        re.compile(r"jobs\.ashbyhq\.com/([a-z0-9\-]+)", re.I),
    ],
}


def _detect_ats(url: str) -> tuple[str, str] | None:
    if not url:
        return None
    for ats, patterns in ATS_HOST_PATTERNS.items():
        for p in patterns:
            m = p.search(url)
            if m:
                return ats, m.group(1).lower()
    return None


def list_companies(timeout: int = 20) -> list[dict]:
    """Return [{name, ats, board_token, careers_url}, ...] for YC companies
    whose careers URL points at a known ATS."""
    r = requests.get(YC_COMPANIES_JSON, timeout=timeout)
    r.raise_for_status()
    data = r.json()

    results = []
    seen: set[tuple[str, str]] = set()

    for c in data:
        # Probe a few common fields for any ATS link.
        candidates = [c.get("website"), c.get("careers_url"), c.get("url")]
        for k in ("description", "one_liner", "long_description"):
            v = c.get(k)
            if isinstance(v, str):
                candidates.append(v)

        for cand in candidates:
            if not cand:
                continue
            hit = _detect_ats(cand)
            if hit:
                ats, token = hit
                key = (ats, token)
                if key in seen:
                    continue
                seen.add(key)
                results.append({
                    "name": c.get("name", token),
                    "ats":  ats,
                    "board_token": token,
                    "careers_url": cand,
                })
                break

    return results


if __name__ == "__main__":
    cos = list_companies()
    print(f"Found {len(cos)} YC companies with detectable ATS")
    for c in cos[:10]:
        print(" ", c)
