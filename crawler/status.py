"""
status.py

Job status snapshots for CLI and API.
"""

import sqlite3
import time

try:
    from . import config
except ImportError:  # Support running as `python crawler/main.py`
    import config


def _frontier_counts(conn: sqlite3.Connection, job_id: int | None = None) -> dict[str, int]:
    if job_id is None:
        rows = conn.execute("SELECT state, COUNT(*) AS cnt FROM frontier GROUP BY state").fetchall()
    else:
        rows = conn.execute(
            "SELECT state, COUNT(*) AS cnt FROM frontier WHERE job_id = ? GROUP BY state",
            (job_id,),
        ).fetchall()
    return {row["state"]: row["cnt"] for row in rows}


def get_job_snapshot(conn: sqlite3.Connection, job_id: int | None = None) -> dict | None:
    if job_id is None:
        job = conn.execute("SELECT * FROM crawl_jobs ORDER BY id DESC LIMIT 1").fetchone()
    else:
        job = conn.execute("SELECT * FROM crawl_jobs WHERE id = ?", (job_id,)).fetchone()

    if job is None:
        return None

    return _build_snapshot(conn, job)


def get_all_jobs_snapshot(conn: sqlite3.Connection) -> list[dict]:
    jobs = conn.execute("SELECT * FROM crawl_jobs ORDER BY id DESC").fetchall()
    return [_build_snapshot(conn, job) for job in jobs]


def _build_snapshot(conn: sqlite3.Connection, job) -> dict:
    counts = _frontier_counts(conn, job["id"])
    indexed_pages = conn.execute(
        "SELECT COUNT(*) AS cnt FROM page_discoveries WHERE job_id = ?",
        (job["id"],),
    ).fetchone()["cnt"]
    discovered_pages = conn.execute(
        "SELECT COUNT(*) AS cnt FROM frontier WHERE job_id = ?",
        (job["id"],),
    ).fetchone()["cnt"]

    queue_depth = counts.get("pending", 0) + counts.get("queued", 0)
    in_flight = counts.get("processing", 0)
    failed_pages = counts.get("failed", 0)
    queue_cap = job["queue_cap"] if "queue_cap" in job.keys() else config.QUEUE_CAP
    bp_events = job["back_pressure_events"] if "back_pressure_events" in job.keys() else 0

    back_pressure = "active" if (
        queue_depth >= queue_cap or in_flight >= config.MAX_CONCURRENT
    ) else "idle"

    snapshot = {
        "job_id": job["id"],
        "origin_url": job["origin_url"],
        "max_depth": job["max_depth"],
        "queue_cap": queue_cap,
        "status": job["state"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "indexed_pages": indexed_pages,
        "discovered_pages": discovered_pages,
        "queue_depth": queue_depth,
        "in_flight": in_flight,
        "back_pressure": back_pressure,
        "back_pressure_events": bp_events,
        "failed_pages": failed_pages,
    }
    if job["state"] == "error":
        snapshot["error"] = "crawl failed"
    elif failed_pages > 0 and indexed_pages == 0:
        snapshot["error"] = "No pages were indexed. The origin page may have rejected the crawler request."
    return snapshot


def print_status(conn: sqlite3.Connection) -> None:
    snapshot = get_job_snapshot(conn)
    if snapshot is None:
        print("No crawl jobs found.")
        return

    started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(snapshot["started_at"]))
    finished = (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(snapshot["finished_at"]))
        if snapshot["finished_at"]
        else "-"
    )
    counts = _frontier_counts(conn, snapshot["job_id"])

    print("-" * 50)
    print("Most Recent Crawl Job")
    print("-" * 50)
    print(f"  Job ID     : {snapshot['job_id']}")
    print(f"  Origin URL : {snapshot['origin_url']}")
    print(f"  Max depth  : {snapshot['max_depth']}")
    print(f"  Queue cap  : {snapshot['queue_cap']}")
    print(f"  State      : {snapshot['status']}")
    print(f"  Started at : {started}")
    print(f"  Finished at: {finished}")
    print(f"  Indexed    : {snapshot['indexed_pages']}")
    print(f"  Discovered : {snapshot['discovered_pages']}")
    print(f"  Queue depth: {snapshot['queue_depth']}")
    print(f"  In flight  : {snapshot['in_flight']}")
    print(f"  Backpressure: {snapshot['back_pressure']}")
    print(f"  BP events  : {snapshot['back_pressure_events']}")

    print()
    print("Frontier state counts:")
    for state in ("pending", "queued", "processing", "done", "failed", "skipped"):
        print(f"  {state:<12}: {counts.get(state, 0)}")
    print("-" * 50)


def print_stats(conn: sqlite3.Connection) -> None:
    total_pages = conn.execute("SELECT COUNT(*) AS cnt FROM pages").fetchone()["cnt"]
    total_discoveries = conn.execute("SELECT COUNT(*) AS cnt FROM page_discoveries").fetchone()["cnt"]
    total_frontier = conn.execute("SELECT COUNT(*) AS cnt FROM frontier").fetchone()["cnt"]
    total_jobs = conn.execute("SELECT COUNT(*) AS cnt FROM crawl_jobs").fetchone()["cnt"]

    print("-" * 50)
    print("Global Crawl Statistics")
    print("-" * 50)
    print(f"  Total pages indexed  : {total_pages}")
    print(f"  Total discoveries    : {total_discoveries}")
    print(f"  Total frontier entries: {total_frontier}")
    print(f"  Total crawl jobs     : {total_jobs}")

    if total_frontier > 0:
        frontier_rows = conn.execute(
            "SELECT state, COUNT(*) AS cnt FROM frontier GROUP BY state"
        ).fetchall()
        print()
        print("Frontier breakdown (all jobs):")
        for row in frontier_rows:
            print(f"  {row['state']:<12}: {row['cnt']}")

    print("-" * 50)
