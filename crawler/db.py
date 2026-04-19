"""
db.py

SQLite connection factory, schema initialization, WAL mode setup, and
per-job p_data export for assignment search.

Schema changes from v1:
  - pages.headings TEXT column (JSON list of {level, text})
  - crawl_jobs.back_pressure_events INTEGER column
  - crawl_jobs.queue_cap INTEGER column
"""

import json
import re
import sqlite3
import unicodedata
from pathlib import Path

try:
    from . import config
except ImportError:  # Support running as `python crawler/main.py`
    import config


def get_connection(read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout = 3000")

    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS crawl_jobs (
            id          INTEGER PRIMARY KEY,
            origin_url  TEXT    NOT NULL,
            max_depth   INTEGER NOT NULL,
            queue_cap   INTEGER NOT NULL DEFAULT 1000,
            state       TEXT    NOT NULL DEFAULT 'running',
            started_at  INTEGER NOT NULL,
            finished_at INTEGER,
            back_pressure_events INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS pages (
            id          INTEGER PRIMARY KEY,
            url         TEXT    NOT NULL UNIQUE,
            title       TEXT,
            headings    TEXT,
            body_text   TEXT,
            fetched_at  INTEGER NOT NULL,
            status      INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pages_url ON pages(url);

        CREATE TABLE IF NOT EXISTS page_discoveries (
            id          INTEGER PRIMARY KEY,
            page_id     INTEGER NOT NULL REFERENCES pages(id),
            job_id      INTEGER NOT NULL REFERENCES crawl_jobs(id),
            origin_url  TEXT    NOT NULL,
            depth       INTEGER NOT NULL,
            UNIQUE (page_id, job_id)
        );
        CREATE INDEX IF NOT EXISTS idx_pd_job  ON page_discoveries(job_id);
        CREATE INDEX IF NOT EXISTS idx_pd_page ON page_discoveries(page_id);

        CREATE TABLE IF NOT EXISTS frontier (
            id          INTEGER PRIMARY KEY,
            job_id      INTEGER NOT NULL REFERENCES crawl_jobs(id),
            url         TEXT    NOT NULL,
            origin_url  TEXT    NOT NULL,
            depth       INTEGER NOT NULL,
            state       TEXT    NOT NULL DEFAULT 'pending',
            enqueued_at INTEGER NOT NULL,
            UNIQUE (job_id, url)
        );
        CREATE INDEX IF NOT EXISTS idx_frontier_state ON frontier(job_id, state);

        CREATE TABLE IF NOT EXISTS seen_urls (
            url    TEXT    NOT NULL,
            job_id INTEGER NOT NULL REFERENCES crawl_jobs(id),
            PRIMARY KEY (url, job_id)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
            title,
            body_text,
            content='pages',
            content_rowid='id',
            tokenize='porter unicode61'
        );
    """)

    _migrate_add_column(conn, "pages", "headings", "TEXT")
    _migrate_add_column(conn, "crawl_jobs", "back_pressure_events", "INTEGER NOT NULL DEFAULT 0")
    _migrate_add_column(conn, "crawl_jobs", "queue_cap", "INTEGER NOT NULL DEFAULT 1000")


def _migrate_add_column(conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
    try:
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            conn.commit()
    except Exception:
        pass


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _normalise_text(text: str) -> str:
    return (
        unicodedata.normalize("NFKD", text.lower())
        .encode("ascii", "ignore")
        .decode("ascii")
    )


def _tokenise(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(_normalise_text(text)) if len(t) >= 2]


def _storage_dir_candidates() -> list[Path]:
    candidates = [config.STORAGE_DIR]
    default_dir = Path(__file__).resolve().parent.parent / "data" / "storage"
    if default_dir not in candidates:
        candidates.append(default_dir)
    return candidates


def export_p_data(conn: sqlite3.Connection, job_id: int) -> int:
    rows = conn.execute("""
        SELECT p.url, pd.origin_url, pd.depth, p.title, p.headings, p.body_text
        FROM pages p
        JOIN page_discoveries pd ON p.id = pd.page_id
        WHERE pd.job_id = ?
    """, (job_id,)).fetchall()

    lines_written = 0
    last_error: OSError | None = None
    for storage_dir in _storage_dir_candidates():
        path = storage_dir / f"p_{job_id}.data"
        try:
            storage_dir.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                for row in rows:
                    url = row["url"]
                    origin_url = row["origin_url"]
                    depth = row["depth"]

                    text_parts = []
                    if row["title"]:
                        text_parts.append(row["title"])
                    if row["headings"]:
                        try:
                            headings = json.loads(row["headings"])
                            for heading in headings:
                                if heading.get("text"):
                                    text_parts.append(heading["text"])
                        except (json.JSONDecodeError, TypeError):
                            pass
                    if row["body_text"]:
                        text_parts.append(row["body_text"])

                    combined = " ".join(text_parts)
                    if not combined.strip():
                        continue

                    freq: dict[str, int] = {}
                    for token in _tokenise(combined):
                        freq[token] = freq.get(token, 0) + 1

                    for word, count in freq.items():
                        fh.write(f"{word}\t{url}\t{origin_url}\t{depth}\t{count}\n")
                        lines_written += 1
            return lines_written
        except OSError as exc:
            last_error = exc
            lines_written = 0

    if last_error is not None:
        raise last_error
    return lines_written


def get_p_data_path(job_id: int):
    filename = f"p_{job_id}.data"
    for storage_dir in _storage_dir_candidates():
        path = storage_dir / filename
        if path.exists():
            return path
    return config.STORAGE_DIR / filename


def get_latest_completed_job_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        """SELECT id FROM crawl_jobs
           WHERE state IN ('done', 'completed', 'stopped')
           ORDER BY COALESCE(finished_at, started_at) DESC
           LIMIT 1"""
    ).fetchone()
    return row["id"] if row else None


def read_pages_for_ui_search(conn: sqlite3.Connection, job_id: int | None = None) -> list[dict]:
    if job_id is not None:
        rows = conn.execute("""
            SELECT p.url, p.title, p.headings, p.body_text,
                   pd.origin_url, pd.depth, pd.job_id
            FROM pages p
            JOIN page_discoveries pd ON p.id = pd.page_id
            WHERE pd.job_id = ?
        """, (job_id,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT p.url, p.title, p.headings, p.body_text,
                   pd.origin_url, pd.depth, pd.job_id
            FROM pages p
            JOIN page_discoveries pd ON p.id = pd.page_id
        """).fetchall()
    return [dict(row) for row in rows]
