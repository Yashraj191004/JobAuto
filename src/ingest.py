"""End-to-end discovery pipeline:

    discover (YC + SimplifyJobs + JSearch)
      ─► fetch (Greenhouse + Lever + Ashby)
        ─► normalize + filter
          ─► dedupe + upsert into SQLite

Run as a module:
    python -m src.ingest
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from .config import load_profile
from .schema import Job, upsert_jobs, init_db, start_run, end_run, log_event
from .discover import yc, simplifyjobs, jsearch
from .fetch import greenhouse, lever, ashby
from .normalize import apply_filters


FETCHERS = {
    "greenhouse": greenhouse.fetch,
    "lever":      lever.fetch,
    "ashby":      ashby.fetch,
}


def _select_targets(profile: dict, tracks: list[str] | None) -> dict:
    """Narrow profile.targets to a subset of track names. No-op if tracks is None."""
    if not tracks:
        return profile
    wanted = {t.strip() for t in tracks if t.strip()}
    profile = dict(profile)
    profile["targets"] = [
        target for target in profile.get("targets", [])
        if target.get("track") in wanted
    ]
    if not profile["targets"]:
        raise ValueError(f"No matching tracks in search_profile.yaml: {sorted(wanted)}")
    return profile


def _track_counts(jobs: list[Job]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for job in jobs:
        key = job.track or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _print_track_summary(jobs: list[Job], label: str) -> None:
    counts = _track_counts(jobs)
    if not counts:
        return
    summary = ", ".join(f"{track}={count}" for track, count in sorted(counts.items()))
    print(f"[ingest] {label} by track: {summary}")


def _dedupe_raw_jobs(jobs: list[Job]) -> list[Job]:
    """Collapse obvious duplicates before filtering and DB upsert.

    Two jobs collapse when their URLs match (case-insensitive), or — for jobs
    without a URL — when company + title match. The earliest record wins;
    later records fill in any blank description, location, posted_at, or track.
    """
    seen: dict[str, Job] = {}
    order: list[str] = []
    for job in jobs:
        url = (job.url or "").strip().lower()
        if url:
            key = f"url:{url}"
        else:
            key = f"role:{job.company.strip().lower()}|{job.title.strip().lower()}"
        if key in seen:
            existing = seen[key]
            existing.description = existing.description or job.description
            existing.posted_at   = existing.posted_at   or job.posted_at
            existing.location    = existing.location    or job.location
            existing.track       = existing.track       or job.track
            continue
        seen[key] = job
        order.append(key)
    return [seen[k] for k in order]


def _fetch_company(c: dict) -> list[Job]:
    fn = FETCHERS.get(c["ats"])
    if not fn:
        return []
    return fn(c["board_token"], company_name=c["name"])


def run(tracks: list[str] | None = None) -> dict:
    init_db()
    run_id = start_run("ingest")
    try:
        profile = _select_targets(load_profile(), tracks)
        enabled = [t.get("track") for t in profile.get("targets", [])]
        print(f"[ingest] enabled tracks: {', '.join(enabled)}")

        print("[ingest] discovering companies via YC OSS …")
        companies = yc.list_companies()
        print(f"[ingest]   → {len(companies)} companies with detectable ATS")

        print("[ingest] fetching job boards (Greenhouse / Lever / Ashby) in parallel …")
        raw_jobs: list[Job] = []
        with ThreadPoolExecutor(max_workers=16) as ex:
            futs = [ex.submit(_fetch_company, c) for c in companies]
            for i, f in enumerate(as_completed(futs), 1):
                try:
                    raw_jobs.extend(f.result())
                except Exception as e:
                    print(f"[ingest] fetcher error: {e}")
                if i % 100 == 0:
                    print(f"[ingest]   … {i}/{len(futs)} boards done")
        print(f"[ingest]   → {len(raw_jobs)} raw jobs from ATS boards")

        print("[ingest] fetching SimplifyJobs new-grad + internship listings …")
        raw_jobs.extend(simplifyjobs.fetch_all())

        targets  = profile.get("targets") or []
        locs_inc = (profile.get("locations") or {}).get("include") or []
        print("[ingest] keyword search via JSearch…")
        raw_jobs.extend(jsearch.search(targets, locs_inc, profile.get("filters") or {}))

        before = len(raw_jobs)
        raw_jobs = _dedupe_raw_jobs(raw_jobs)
        print(f"[ingest] dedupe: {before} raw -> {len(raw_jobs)} unique")

        print(f"[ingest] {len(raw_jobs)} raw jobs total — normalizing + filtering …")
        keep = apply_filters(raw_jobs, profile)
        _print_track_summary(keep, "kept")
        for job in keep[:10]:
            print(f"[ingest]   {job.track}: {job.company} - {job.title} "
                  f"({job.location or 'location unknown'})")
        print(f"[ingest]   → {len(keep)} jobs pass filters")

        new, updated = upsert_jobs(keep)
        print(f"[ingest] DB: {new} new, {updated} refreshed")
        detail = f"raw={len(raw_jobs)} kept={len(keep)} new={new} updated={updated}"
        log_event("ingest", detail=detail)
        end_run(run_id, "ok", detail)
        return {"raw": len(raw_jobs), "kept": len(keep), "new": new, "updated": updated}
    except Exception as e:
        end_run(run_id, "error", str(e))
        log_event("error", detail=f"ingest: {e}")
        raise


if __name__ == "__main__":
    run()
