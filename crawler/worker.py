"""
worker.py

Async worker coroutine for the crawl engine.

Key behaviors:
  - origin_url propagation: always the seed URL of the job, not the parent page
  - Page-level link deduplication before enqueue
  - Per-page link cap (LINKS_PER_PAGE_CAP)
  - Adaptive back pressure: when queue fill >= 85% OR frontier pending >=
    FRONTIER_BP_THRESHOLD, drop deeper links (depth > 1)
  - Non-blocking enqueue: drop URLs on overflow, increment back_pressure_events
  - Integrates should_enqueue() filtering
  - Worker failures mark frontier rows as 'failed' (never stranded in 'processing')
"""

import asyncio
import sqlite3
import time

try:
    from . import config, db, fetcher, indexer, normalizer, parser
except ImportError:  # Support running as `python crawler/main.py`
    import config
    import db
    import fetcher
    import indexer
    import normalizer
    import parser


async def worker(
    queue: asyncio.Queue,
    session,
    tracker,
    seen: set[str],
    job_id: int,
    max_depth: int,
    job_origin: str,
    bp_counter: list,
    bp_state: dict | None = None,
) -> None:
    """
    Single async worker coroutine.

    Args:
        queue: asyncio.Queue of (url, origin_url, depth) tuples
        session: aiohttp.ClientSession
        tracker: PolitenessTracker (per-session)
        seen: shared seen-URL set for this job
        job_id: crawl job ID
        max_depth: max crawl depth
        job_origin: the original seed URL passed to index() for this job
        bp_counter: mutable [int] list for counting back_pressure_events
    """
    conn = db.get_connection()

    while True:
        try:
            item = await queue.get()
        except asyncio.CancelledError:
            break

        # url is initialised here so the except block can reference it
        # even if unpacking fails (set to None as sentinel).
        url = None
        try:
            url, origin_url, depth = item

            with conn:
                conn.execute(
                    "UPDATE frontier SET state = 'processing' WHERE job_id = ? AND url = ? AND state IN ('pending', 'queued')",
                    (job_id, url),
                )

            if depth > max_depth:
                with conn:
                    conn.execute(
                        "UPDATE frontier SET state = 'skipped' WHERE job_id = ? AND url = ?",
                        (job_id, url),
                    )
                continue

            status, html = await fetcher.fetch(session, url, tracker=tracker)

            if status != 200 or not html:
                with conn:
                    conn.execute(
                        "UPDATE frontier SET state = 'failed' WHERE job_id = ? AND url = ?",
                        (job_id, url),
                    )
                continue

            links, body_text, title, headings = parser.parse(html, base_url=url)

            indexer.write_page(
                conn, url, title, body_text, status,
                job_id, origin_url, depth,
                headings=headings,
            )

            if depth < max_depth:
                _enqueue_discovered_links(
                    conn, queue, links, seen, job_id,
                    job_origin, url, depth, bp_counter, bp_state=bp_state,
                )

        except Exception:
            # Don't leave this URL stranded in 'processing'.
            # Mark it as 'failed' so the job can still complete.
            if url is not None:
                try:
                    with conn:
                        conn.execute(
                            "UPDATE frontier SET state = 'failed' "
                            "WHERE job_id = ? AND url = ? AND state = 'processing'",
                            (job_id, url),
                        )
                except Exception:
                    pass  # best-effort — avoid masking the original error
            continue
        finally:
            queue.task_done()


def _enqueue_discovered_links(
    conn: sqlite3.Connection,
    queue: asyncio.Queue,
    raw_links: list[str],
    seen: set[str],
    job_id: int,
    job_origin: str,
    current_url: str,
    current_depth: int,
    bp_counter: list,
    bp_state: dict | None = None,
) -> None:
    """
    Process discovered links with filtering, dedup, capping, and backpressure.

    IMPORTANT: origin_url is always job_origin (the seed URL), NOT current_url.
    """
    next_depth = current_depth + 1

    # ── Step A: normalise + quality-filter, page-level deduplication ──
    seen_this_page: set[str] = set()
    candidate_links: list[str] = []

    for raw_link in raw_links:
        link = normalizer.canonicalize(raw_link, base=current_url)
        if link is None:
            continue
        if not normalizer.should_enqueue(link, origin=job_origin):
            continue
        if link in seen_this_page:
            continue
        seen_this_page.add(link)
        candidate_links.append(link)

    # ── Step B: per-page link cap ────────────────────────────────
    capped = candidate_links[:config.LINKS_PER_PAGE_CAP]

    # ── Step C: adaptive back pressure ───────────────────────────
    # Check both in-memory queue capacity AND durable frontier backlog.
    queue_fill = queue.qsize() / max(queue.maxsize, 1) if queue.maxsize else 0
    queue_pressure = queue_fill >= config.ADAPTIVE_BP_THRESHOLD

    # Frontier-aware: if too many pending rows accumulate in the DB,
    # treat the system as under pressure even if the in-memory queue
    # has capacity (because the frontier keeps feeding new work).
    frontier_pending = 0
    cache_state = bp_state if bp_state is not None else {}
    now = time.monotonic()
    cached_count = cache_state.get("frontier_pending")
    cached_at = cache_state.get("frontier_pending_at", 0.0)

    if cached_count is not None and now - cached_at < 0.5:
        frontier_pending = cached_count
    else:
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM frontier WHERE job_id = ? AND state = 'pending'",
                (job_id,),
            ).fetchone()
            frontier_pending = row["cnt"] if row else 0
            cache_state["frontier_pending"] = frontier_pending
            cache_state["frontier_pending_at"] = now
        except Exception:
            frontier_pending = cached_count or 0
    frontier_pressure = frontier_pending >= config.FRONTIER_BP_THRESHOLD

    under_pressure = queue_pressure or frontier_pressure
    accepted_links: list[str] = []

    for link in capped:
        # Adaptive BP: under pressure, drop deeper links (next_depth > 1)
        if under_pressure and next_depth > 1:
            bp_counter[0] += 1
            continue

        # Global dedup: skip if already seen in this job
        if link in seen:
            continue
        seen.add(link)
        accepted_links.append(link)

    if not accepted_links:
        return

    inserted_count = _persist_discovered_links(
        conn, accepted_links, job_id, job_origin, next_depth,
    )
    if bp_state is not None and inserted_count > 0:
        bp_state["frontier_pending"] = bp_state.get("frontier_pending", 0) + inserted_count
        bp_state["frontier_pending_at"] = time.monotonic()


def _persist_discovered_links(
    conn: sqlite3.Connection,
    links: list[str],
    job_id: int,
    job_origin: str,
    next_depth: int,
) -> int:
    now = int(time.time())
    frontier_rows = [(job_id, link, job_origin, next_depth, now) for link in links]
    seen_rows = [(link, job_id) for link in links]

    try:
        with conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO frontier
                (job_id, url, origin_url, depth, state, enqueued_at)
                VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                frontier_rows,
            )
            conn.executemany(
                "INSERT OR IGNORE INTO seen_urls (url, job_id) VALUES (?, ?)",
                seen_rows,
            )
        return len(links)
    except Exception:
        inserted = 0
        for link in links:
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO frontier
                        (job_id, url, origin_url, depth, state, enqueued_at)
                        VALUES (?, ?, ?, ?, 'pending', ?)
                        """,
                        (job_id, link, job_origin, next_depth, now),
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO seen_urls (url, job_id) VALUES (?, ?)",
                        (link, job_id),
                    )
                inserted += 1
            except Exception:
                continue
        return inserted
