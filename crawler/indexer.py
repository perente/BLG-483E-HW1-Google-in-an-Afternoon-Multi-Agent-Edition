"""
indexer.py

Atomic per-page transaction: pages + page_discoveries + FTS5 + frontier.
"""

import json
import time
import sqlite3


def write_page(
    conn: sqlite3.Connection,
    url: str,
    title: str,
    body_text: str,
    status: int,
    job_id: int,
    origin_url: str,
    depth: int,
    headings: list[dict] | None = None,
) -> None:
    """
    Write a single page atomically: pages + page_discoveries + FTS5 + frontier.

    headings: list of {"level": int, "text": str} dicts, stored as JSON.
    """
    fetched_at = int(time.time())
    headings_json = json.dumps(headings or [], ensure_ascii=False)

    with conn:
        existing_row = conn.execute(
            "SELECT id, title, body_text FROM pages WHERE url = ?",
            (url,),
        ).fetchone()

        cursor = conn.execute(
            """
            INSERT INTO pages (url, title, headings, body_text, fetched_at, status)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title      = excluded.title,
                headings   = excluded.headings,
                body_text  = excluded.body_text,
                fetched_at = excluded.fetched_at,
                status     = excluded.status
            """,
            (url, title, headings_json, body_text, fetched_at, status),
        )

        row = conn.execute(
            "SELECT id FROM pages WHERE url = ?",
            (url,),
        ).fetchone()
        page_id = row["id"]

        # page_discoveries
        conn.execute(
            """
            INSERT OR IGNORE INTO page_discoveries (page_id, job_id, origin_url, depth)
            VALUES (?, ?, ?, ?)
            """,
            (page_id, job_id, origin_url, depth),
        )

        # FTS5 update
        if existing_row is not None:
            conn.execute(
                """
                INSERT INTO pages_fts (pages_fts, rowid, title, body_text)
                VALUES ('delete', ?, ?, ?)
                """,
                (
                    existing_row["id"],
                    existing_row["title"],
                    existing_row["body_text"],
                ),
            )

        conn.execute(
            """
            INSERT INTO pages_fts (rowid, title, body_text)
            VALUES (?, ?, ?)
            """,
            (page_id, title, body_text),
        )

        # frontier update
        conn.execute(
            """
            UPDATE frontier SET state = 'done'
            WHERE job_id = ? AND url = ?
            """,
            (job_id, url),
        )
