"""Normalize raw jobs: strip HTML, infer track, apply profile filters.

Public:
    classify(job, profile)        -> Job   # sets job.track
    apply_filters(jobs, profile)  -> list[Job]
"""
from __future__ import annotations
import re
from datetime import datetime, timezone, timedelta
from html import unescape
from .schema import Job

_HTML_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def strip_html(text: str | None) -> str | None:
    if not text:
        return text
    text = unescape(text)
    text = _HTML_TAG.sub(" ", text)
    return _WS.sub(" ", text).strip()


def _matches_any(haystack: str, needles: list[str]) -> bool:
    h = haystack.lower()
    return any(n.lower() in h for n in needles if n)


def classify(job: Job, profile: dict) -> Job:
    """Infer track from job.title using profile.targets[*].titles.

    Special case: any title containing 'intern' wins the internship track,
    so 'SWE Intern' is not mis-classified as 'new_grad' via the 'swe' keyword.

    If the job already has a track set, the classifier reconfirms it against
    the profile and only re-classifies if the original track no longer matches.
    """
    title_l = job.title.lower()
    if "intern" in title_l:
        for t in profile.get("targets", []):
            if t.get("track") == "internship":
                job.track = "internship"
                return job

    if job.track:
        for t in profile.get("targets", []):
            if t.get("track") == job.track and _matches_any(job.title, t.get("titles") or []):
                return job
        job.track = None

    for t in profile.get("targets", []):
        titles = t.get("titles") or []
        if _matches_any(job.title, titles):
            job.track = t.get("track")
            return job
    return job


# Two-letter US state abbreviations, padded with a leading space so they
# match in the middle/end of comma-stripped location strings.
_US_STATE_HINTS = {
    " al", " ak", " az", " ar", " ca", " co", " ct", " de", " fl", " ga",
    " hi", " id", " il", " in", " ia", " ks", " ky", " la", " me", " md",
    " ma", " mi", " mn", " ms", " mo", " mt", " ne", " nv", " nh", " nj",
    " nm", " ny", " nc", " nd", " oh", " ok", " or", " pa", " ri", " sc",
    " sd", " tn", " tx", " ut", " vt", " va", " wa", " wv", " wi", " wy",
    " dc",
}


def _looks_us(loc_lc: str) -> bool:
    if "united states" in loc_lc or "usa" in loc_lc or "u.s." in loc_lc:
        return True
    padded = " " + loc_lc.replace(",", " ").replace(".", " ")
    return any(h in padded for h in _US_STATE_HINTS)


def _location_ok(loc: str, include: list[str], exclude_kw: list[str]) -> bool:
    if not loc:
        return True
    loc_l = loc.lower()
    if any(ex.lower() in loc_l for ex in exclude_kw):
        return False
    if not include:
        return True
    if any(inc.lower() in loc_l for inc in include):
        return True
    if "remote" in loc_l or "anywhere" in loc_l:
        return True
    if _looks_us(loc_l):
        return True
    return False


def _recent(posted_at: str | None, days: int) -> bool:
    if not posted_at or not days:
        return True
    try:
        dt = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
        return dt >= datetime.now(timezone.utc) - timedelta(days=days)
    except Exception:
        return True


def apply_filters(jobs: list[Job], profile: dict) -> list[Job]:
    locs       = profile.get("locations") or {}
    include    = locs.get("include") or []
    exclude_kw = locs.get("exclude_keywords") or []
    filt       = profile.get("filters") or {}
    excl_co    = {c.lower() for c in (filt.get("exclude_companies") or [])}
    days       = int(filt.get("posted_within_days") or 0)

    out: list[Job] = []
    for j in jobs:
        j.description = strip_html(j.description)
        classify(j, profile)

        if j.company.lower() in excl_co:
            continue
        if not _location_ok(j.location or "", include, exclude_kw):
            continue
        if not _recent(j.posted_at, days):
            continue
        # Must match at least one configured track to be worth keeping.
        if not j.track:
            continue

        out.append(j)
    return out
