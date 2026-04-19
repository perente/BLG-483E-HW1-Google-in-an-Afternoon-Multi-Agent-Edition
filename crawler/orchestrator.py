"""
orchestrator.py

Job lifecycle management: create, run, resume.
"""

import asyncio
import time

try:
    from . import config, db, fetcher, worker
except ImportError:  # Support running as `python crawler/main.py`
    import config
    import db
    import fetcher
    import worker


def validate_index_request(origin_url: str, max_depth: int, queue_cap: int | None = None) -> None:
    if not origin_url.startswith(("http://", "https://")):
        raise ValueError("origin_url must start with http:// or https://")
    if max_depth < 0:
        raise ValueError("max_depth must be >= 0")
    if queue_cap is not None and queue_cap < 1:
        raise ValueError("queue_cap must be >= 1")
    if queue_cap is not None and queue_cap > config.MAX_QUEUE_CAP:
        raise ValueError(f"queue_cap must be <= {config.MAX_QUEUE_CAP}")


def _count_active_jobs(conn) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM crawl_jobs WHERE state IN ('running', 'queued', 'pausing')"
    ).fetchone()
    return row["cnt"]


def create_job(
    origin_url: str,
    max_depth: int,
    state: str = "running",
    queue_cap: int | None = None,
) -> int:
    queue_cap = queue_cap if queue_cap is not None else config.QUEUE_CAP
    validate_index_request(origin_url, max_depth, queue_cap)

    conn = db.get_connection()
    db.init_schema(conn)

    active = _count_active_jobs(conn)
    if active >= config.MAX_ACTIVE_JOBS:
        conn.close()
        raise ValueError(
            f"Maximum {config.MAX_ACTIVE_JOBS} active crawl jobs allowed. "
            f"Currently {active} active. Wait for a job to finish or stop one first."
        )

    now = int(time.time())
    cursor = conn.execute(
        """
        INSERT INTO crawl_jobs (origin_url, max_depth, queue_cap, state, started_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (origin_url, max_depth, queue_cap, state, now),
    )
    conn.commit()
    job_id = cursor.lastrowid

    conn.execute(
        """
        INSERT OR IGNORE INTO frontier
        (job_id, url, origin_url, depth, state, enqueued_at)
        VALUES (?, ?, ?, 0, 'pending', ?)
        """,
        (job_id, origin_url, origin_url, now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO seen_urls (url, job_id) VALUES (?, ?)",
        (origin_url, job_id),
    )
    conn.commit()
    conn.close()

    return job_id


def set_job_state(job_id: int, state: str, finished_at: int | None = None) -> None:
    conn = db.get_connection()
    try:
        conn.execute(
            "UPDATE crawl_jobs SET state = ?, finished_at = ? WHERE id = ?",
            (state, finished_at, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_job_row(job_id: int):
    conn = db.get_connection()
    try:
        db.init_schema(conn)
        return conn.execute(
            "SELECT * FROM crawl_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    finally:
        conn.close()


def _update_bp_count(job_id: int, bp_events: int) -> None:
    conn = db.get_connection()
    try:
        conn.execute(
            "UPDATE crawl_jobs SET back_pressure_events = ? WHERE id = ?",
            (bp_events, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def request_pause(job_id: int) -> bool:
    conn = db.get_connection()
    try:
        db.init_schema(conn)
        row = conn.execute(
            "SELECT state FROM crawl_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if row is None or row["state"] not in {"running", "queued"}:
            return False
        conn.execute(
            "UPDATE crawl_jobs SET state = 'pausing', finished_at = NULL WHERE id = ?",
            (job_id,),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def resume_job(job_id: int) -> tuple[str, int] | None:
    conn = db.get_connection()
    try:
        db.init_schema(conn)
        row = conn.execute(
            "SELECT origin_url, max_depth, state FROM crawl_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if row is None or row["state"] != "paused":
            return None
        conn.execute(
            "UPDATE frontier SET state = 'pending' WHERE job_id = ? AND state IN ('processing', 'queued')",
            (job_id,),
        )
        conn.execute(
            "UPDATE crawl_jobs SET state = 'queued', finished_at = NULL WHERE id = ?",
            (job_id,),
        )
        conn.commit()
        return row["origin_url"], row["max_depth"]
    finally:
        conn.close()


def run_job(job_id: int, max_depth: int) -> None:
    set_job_state(job_id, "running")

    bp_counter = [0]
    paused = asyncio.run(_run_event_loop(job_id, max_depth, bp_counter))

    _update_bp_count(job_id, bp_counter[0])

    if paused:
        return

    current = get_job_row(job_id)
    if current is not None and current["state"] == "error":
        return

    try:
        conn = db.get_connection()
        lines = db.export_p_data(conn, job_id)
        conn.close()
        print(f"[Job {job_id}] p_data export done - {lines} lines written")
    except Exception as exc:
        print(f"[Job {job_id}] p_data export failed: {exc}")

    set_job_state(job_id, "done", int(time.time()))


def index_command(origin_url: str, max_depth: int, queue_cap: int | None = None) -> int | None:
    try:
        job_id = create_job(origin_url, max_depth, state="running", queue_cap=queue_cap)
    except ValueError as exc:
        print(f"Error: {exc}")
        return None

    print(f"Crawl started. Job ID: {job_id}  Origin: {origin_url}  Max depth: {max_depth}")
    run_job(job_id, max_depth)
    print("Crawl finished.")
    return job_id


def resume_command(job_id: int | None = None) -> None:
    conn = db.get_connection()
    db.init_schema(conn)

    if job_id is not None:
        row = conn.execute(
            "SELECT id FROM crawl_jobs WHERE id = ? AND state = 'paused'",
            (job_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM crawl_jobs WHERE state = 'paused' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    conn.close()

    if row is None:
        print("No paused crawl job found to resume.")
        return

    job_id = row["id"]
    result = resume_job(job_id)
    if result is None:
        print(f"Job {job_id} is not paused.")
        return
    origin_url, max_depth = result

    print(f"Resuming job {job_id} from {origin_url}")
    run_job(job_id, max_depth)
    print("Crawl finished.")

def pause_command(job_id: int) -> bool:
    paused = request_pause(job_id)
    if paused:
        print(f"Pause requested for job {job_id}.")
    else:
        print(f"Job {job_id} is not running or queued.")
    return paused


def _is_pause_requested(job_id: int) -> bool:
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT state FROM crawl_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        return row is not None and row["state"] == "pausing"
    finally:
        conn.close()


def _mark_job_paused(job_id: int) -> None:
    conn = db.get_connection()
    try:
        with conn:
            conn.execute(
                "UPDATE frontier SET state = 'pending' WHERE job_id = ? AND state IN ('queued', 'processing')",
                (job_id,),
            )
            conn.execute(
                "UPDATE crawl_jobs SET state = 'paused', finished_at = NULL WHERE id = ?",
                (job_id,),
            )
    finally:
        conn.close()


def _get_frontier_remaining(job_id: int) -> int:
    """Count remaining active frontier rows (sync, for use with asyncio.to_thread)."""
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM frontier WHERE job_id = ? AND state IN ('pending', 'queued', 'processing')",
            (job_id,),
        ).fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()


async def _run_event_loop(job_id: int, max_depth: int, bp_counter: list) -> bool:
    conn = db.get_connection()

    job_row = conn.execute(
        "SELECT origin_url, queue_cap FROM crawl_jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    job_origin = job_row["origin_url"] if job_row else ""
    queue_cap = job_row["queue_cap"] if job_row and job_row["queue_cap"] else config.QUEUE_CAP

    pending_count = conn.execute(
        "SELECT COUNT(*) AS cnt FROM frontier WHERE job_id = ? AND state = 'pending'",
        (job_id,),
    ).fetchone()["cnt"]

    seen_rows = conn.execute(
        "SELECT url FROM seen_urls WHERE job_id = ?",
        (job_id,),
    ).fetchall()
    conn.close()

    seen: set[str] = {row["url"] for row in seen_rows}

    if pending_count == 0:
        print("No pending URLs in frontier. Nothing to crawl.")
        return False

    queue: asyncio.Queue = asyncio.Queue(maxsize=queue_cap)
    session, tracker = await fetcher.create_session()
    paused = False
    bp_state = {
        "frontier_pending": pending_count,
        "frontier_pending_at": time.monotonic(),
    }

    tasks = [
        asyncio.create_task(
            worker.worker(
                queue, session, tracker, seen, job_id, max_depth,
                job_origin, bp_counter, bp_state=bp_state,
            )
        )
        for _ in range(config.MAX_CONCURRENT)
    ]

    _last_pause_check = 0.0
    _pause_check_interval = 0.1
    _last_bp_flush = 0.0
    _bp_flush_interval = 5.0
    _last_bp_value = 0

    try:
        while True:
            now = time.monotonic()

            # Pause check: frequent enough to keep pause/resume responsive.
            if now - _last_pause_check >= _pause_check_interval:
                if await asyncio.to_thread(_is_pause_requested, job_id):
                    paused = True
                    break
                _last_pause_check = now

            if _should_refill_queue(queue):
                queued_now = await _fill_queue_from_frontier(job_id, queue)
                if queued_now > 0:
                    bp_state["frontier_pending"] = max(
                        0,
                        bp_state.get("frontier_pending", 0) - queued_now,
                    )
                    bp_state["frontier_pending_at"] = time.monotonic()

            remaining = await asyncio.to_thread(_get_frontier_remaining, job_id)

            if remaining == 0 and queue.empty():
                break

            # Flush bp count periodically (only when changed)
            if bp_counter[0] != _last_bp_value and now - _last_bp_flush >= _bp_flush_interval:
                _last_bp_value = bp_counter[0]
                _last_bp_flush = now
                await asyncio.to_thread(_update_bp_count, job_id, bp_counter[0])

            await asyncio.sleep(0.1)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await session.close()
        if paused:
            _mark_job_paused(job_id)
    return paused


def _should_refill_queue(queue: asyncio.Queue) -> bool:
    if queue.maxsize <= 0:
        return True
    refill_threshold = max(1, queue.maxsize // 4)
    return queue.qsize() <= refill_threshold


def _fill_frontier_batch_sync(job_id: int, available_slots: int) -> list[tuple]:
    """Read pending frontier rows and mark them as 'queued' (sync, for asyncio.to_thread)."""
    if available_slots <= 0:
        return []

    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT url, origin_url, depth
            FROM frontier
            WHERE job_id = ? AND state = 'pending'
            ORDER BY depth ASC, enqueued_at ASC, id ASC
            LIMIT ?
            """,
            (job_id, available_slots),
        ).fetchall()

        if not rows:
            return []

        with conn:
            conn.executemany(
                "UPDATE frontier SET state = 'queued' WHERE job_id = ? AND url = ? AND state = 'pending'",
                [(job_id, row["url"]) for row in rows],
            )

        return [(row["url"], row["origin_url"], row["depth"]) for row in rows]
    finally:
        conn.close()


async def _fill_queue_from_frontier(job_id: int, queue: asyncio.Queue) -> int:
    available_slots = queue.maxsize - queue.qsize() if queue.maxsize else 0
    if available_slots <= 0:
        return 0

    items = await asyncio.to_thread(_fill_frontier_batch_sync, job_id, available_slots)

    for url, origin_url, depth in items:
        queue.put_nowait((url, origin_url, depth))

    return len(items)
