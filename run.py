"""Single CLI for the whole pipeline.

Usage:
    python run.py ingest [tracks]         # discover + fetch + normalize → SQLite
                                           #   e.g.  ingest internship
                                           #         ingest internship,regular_sde
    python run.py score  [limit] [tracks] # batch-score 'new' jobs
                                           #   e.g.  score 25
                                           #         score 25 data
    python run.py tailor <job_id>         # tailor resume + cover letter
    python run.py server                  # localhost API for the extension
    python run.py dashboard               # open Streamlit UI
    python run.py clear  [--keep-cache]   # wipe jobs.db (and llm_cache.db
                                           # unless --keep-cache is passed)
"""
from __future__ import annotations
import sys
import subprocess
from pathlib import Path


def _help() -> None:
    print(__doc__)
    sys.exit(0)


def _parse_tracks(value: str | None) -> list[str] | None:
    if not value:
        return None
    tracks = [part.strip() for part in value.split(",") if part.strip()]
    return tracks or None


def _cmd_ingest(argv: list[str]) -> None:
    tracks = _parse_tracks(argv[0]) if argv else None
    from src.ingest import run
    run(tracks=tracks)


def _cmd_score(argv: list[str]) -> None:
    from src.config import DEFAULT_SCORE_LIMIT
    from src.score import run

    limit = int(argv[0]) if argv else (DEFAULT_SCORE_LIMIT or None)
    tracks = _parse_tracks(argv[1]) if len(argv) >= 2 else None
    run(limit=limit, tracks=tracks)


def _cmd_tailor(argv: list[str]) -> None:
    if not argv:
        print("tailor needs a job_id")
        sys.exit(1)
    from src.tailor import tailor
    tailor(argv[0])


def _cmd_server(_argv: list[str]) -> None:
    from src.server import main
    main()


def _cmd_dashboard(_argv: list[str]) -> None:
    dash = Path(__file__).parent / "src" / "deliver" / "dashboard.py"
    subprocess.run(["streamlit", "run", str(dash)])


def _cmd_clear(argv: list[str]) -> None:
    from src.config import JOBS_DB, CACHE_DB

    keep_cache = "--keep-cache" in argv
    targets = [JOBS_DB] if keep_cache else [JOBS_DB, CACHE_DB]

    cleared: list[str] = []
    for path in targets:
        if path.exists():
            path.unlink()
            cleared.append(path.name)
    # Also wipe -journal/-wal/-shm if present
    for path in targets:
        for suffix in ("-journal", "-wal", "-shm"):
            sidecar = path.with_name(path.name + suffix)
            if sidecar.exists():
                sidecar.unlink()
                cleared.append(sidecar.name)

    if cleared:
        print(f"[clear] removed: {', '.join(cleared)}")
    else:
        print("[clear] nothing to remove")

    # Re-initialize the schema so the next run doesn't error on missing tables.
    from src.schema import init_db
    init_db()
    print("[clear] schema re-initialized")


COMMANDS = {
    "ingest":    _cmd_ingest,
    "score":     _cmd_score,
    "tailor":    _cmd_tailor,
    "server":    _cmd_server,
    "dashboard": _cmd_dashboard,
    "clear":     _cmd_clear,
}


def main() -> None:
    if len(sys.argv) < 2:
        _help()
    cmd = sys.argv[1]
    if cmd in ("-h", "--help", "help"):
        _help()

    handler = COMMANDS.get(cmd)
    if not handler:
        print(f"unknown command: {cmd}\n")
        _help()
    handler(sys.argv[2:])


if __name__ == "__main__":
    main()
