# Web Crawler & Search System - Implementation Plan

---

## 1. Final Project Folder Structure

This implementation plan covers the **backend implementation scope** only.

```text
project-root/
+-- crawler/
|   +-- main.py
|   +-- server.py
|   +-- config.py
|   +-- db.py
|   +-- orchestrator.py
|   +-- worker.py
|   +-- fetcher.py
|   +-- parser.py
|   +-- normalizer.py
|   +-- indexer.py
|   +-- search.py
|   +-- status.py
+-- data/
|   +-- storage/
+-- requirements.txt
+-- README.md
+-- product_prd.md
```

`crawler.db` is created at runtime in the project root via `config.DB_PATH`.

---

## 2. Each Module's Exact Purpose

| File | Purpose |
|---|---|
| `main.py` | CLI entrypoint. Parses backend commands and delegates to orchestrator, search, or status. |
| `server.py` | HTTP API layer built with Python stdlib server utilities. Starts jobs, exposes job snapshots, and serves search endpoints. |
| `config.py` | All crawler/runtime tuning in one place: queue limits, concurrency, politeness, retries, and storage paths. |
| `db.py` | SQLite connection factory, schema creation, WAL setup, and per-job `p_data` export for assignment search. |
| `orchestrator.py` | Job lifecycle manager. Validates requests, enforces active-job cap, creates jobs, resumes jobs, and drives queue refill/event-loop control. |
| `worker.py` | Async crawl worker. Dequeues frontier items, fetches pages, parses content, writes indexed data, and persists discovered links. |
| `fetcher.py` | Outbound async HTTP client using `aiohttp`, including retry logic, redirects, content-type filtering, and politeness enforcement. |
| `parser.py` | Stdlib HTML parser that extracts links, title, headings, and body text from HTML responses. |
| `normalizer.py` | URL canonicalization and crawl-worthiness filtering (`should_enqueue`). |
| `indexer.py` | Atomic per-page write path: `pages`, `page_discoveries`, `pages_fts`, and frontier completion in one transaction. |
| `search.py` | Backend search layer with two paths: UI search over SQLite and assignment search over per-job exports. |
| `status.py` | CLI/API snapshot builder for job state, frontier counts, backpressure status, and global statistics. |

---

## 3. Key Classes/Functions Per File

### `config.py`

```python
DB_PATH                  = "crawler.db"
USER_AGENT               = "BLG483CrawlerBot/1.0 (+http://localhost; educational localhost crawler)"
ACCEPT_LANGUAGE          = "en-US,en;q=0.9"

REQUEST_TIMEOUT          = 10
CONNECT_TIMEOUT          = 5
READ_TIMEOUT             = 10
REQUEST_RETRIES          = 2
RETRY_BACKOFF            = 1.5
MAX_REDIRECTS            = 5

MAX_CONCURRENT           = 5
MAX_CONCURRENT_PER_HOST  = 5
POLITENESS_DELAY         = 0.2

QUEUE_CAP                = 500
MAX_QUEUE_CAP            = 1000
MAX_ACTIVE_JOBS          = 2

LINKS_PER_PAGE_CAP       = 120
ADAPTIVE_BP_THRESHOLD    = 0.85
FRONTIER_BP_THRESHOLD    = 800
MAX_BODY_SIZE            = 500_000

STORAGE_DIR              = Path(... / "data" / "storage")
```

### `db.py`

```python
def get_connection(read_only: bool = False) -> sqlite3.Connection
    # read_only=True  -> opens URI mode=ro
    # read_only=False -> enables WAL, synchronous=NORMAL, foreign_keys, busy_timeout

def init_schema(conn: sqlite3.Connection) -> None
    # Creates backend schema and FTS table if missing.
    # Ensures pages.headings, crawl_jobs.queue_cap, and
    # crawl_jobs.back_pressure_events columns exist.

def export_p_data(conn: sqlite3.Connection, job_id: int) -> int
    # Exports one job's indexed content into data/storage/p_<job_id>.data

def get_p_data_path(job_id: int) -> Path
    # Resolves the export path for assignment search

def get_latest_completed_job_id(conn: sqlite3.Connection) -> int | None
    # Finds the most recent completed job for assignment search fallback

def read_pages_for_ui_search(conn: sqlite3.Connection, job_id: int | None = None) -> list[dict]
    # Reads pages joined with page_discoveries for Python-side UI scoring
```

### `orchestrator.py`

```python
def validate_index_request(origin_url: str, max_depth: int, queue_cap: int | None = None) -> None
    # Validates URL, depth, and queue-cap constraints

def create_job(origin_url: str, max_depth: int, state: str = "running",
               queue_cap: int | None = None) -> int
    # Enforces active-job cap, inserts crawl_jobs row, seeds frontier and seen_urls

def index_command(origin_url: str, max_depth: int, queue_cap: int | None = None) -> int | None
    # CLI entrypoint for starting a job synchronously

def run_job(job_id: int, max_depth: int) -> None
    # Sets state=running, runs asyncio event loop, exports p_data, marks job done

def request_pause(job_id: int) -> bool
    # Marks a running/queued job as pausing

def pause_command(job_id: int) -> bool
    # CLI wrapper for request_pause()

def resume_job(job_id: int) -> tuple[str, int] | None
    # Validates paused state, resets recoverable frontier rows, returns job metadata

def resume_command(job_id: int | None = None) -> None
    # CLI entrypoint for resuming the latest or explicit paused job

async def _run_event_loop(job_id: int, max_depth: int, bp_counter: list) -> bool
    # Rebuilds seen set, creates queue/session/tracker, spawns workers,
    # refills queue from frontier, handles pause detection, and closes resources
```

### `worker.py`

```python
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
) -> None
    # Main worker loop:
    #   get frontier item
    #   mark processing
    #   fetch page
    #   parse content
    #   write indexed page atomically
    #   persist discovered child links
    #   mark worker failures as failed, never leave stranded processing rows

def _enqueue_discovered_links(...) -> None
    # Handles page-level dedup, link cap, adaptive pressure dropping, and seen tracking

def _persist_discovered_links(...) -> int
    # Persists accepted links into frontier and seen_urls
```

### `fetcher.py`

```python
class PolitenessTracker:
    # Maintains per-domain delay state for one crawl session

async def create_session() -> tuple[aiohttp.ClientSession, PolitenessTracker]
    # Creates per-job aiohttp session + politeness tracker

async def fetch(session: aiohttp.ClientSession, url: str,
                tracker: PolitenessTracker | None = None) -> tuple[int, str]
    # Outbound GET with retries, redirect handling, content-type filtering, and politeness wait
```

### `parser.py`

```python
class CrawlParser(html.parser.HTMLParser):
    # Extracts links, title, headings, and visible body text

def parse(html_text: str, base_url: str = "") -> tuple[list[str], str, str, list[dict]]
    # Returns (links, body_text, title, headings)
```

### `normalizer.py`

```python
def canonicalize(url: str, base: str = "") -> str | None
    # Resolves relative URLs, lowercases scheme/host, strips fragment,
    # rejects unfetchable schemes

def should_enqueue(url: str, origin: str | None = None,
                   restrict_to_origin: bool = False) -> bool
    # Filters low-value wiki/action/revision pages and optional off-origin links

def filter_new(links: list[str], seen: set[str], base: str = "",
               origin: str | None = None) -> list[str]
    # Combined canonicalize + filter + dedup helper
```

### `indexer.py`

```python
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
) -> None
    # One transaction:
    #   upsert pages row (including headings JSON)
    #   insert page_discoveries row
    #   refresh pages_fts row
    #   mark frontier row as done
```

### `search.py`

```python
def ui_search(query: str, job_id: int | None = None,
              limit: int | None = None) -> list[dict]
    # Read-only SQLite search using Python-side field-weighted scoring

def assignment_search(query: str, job_id: int | None = None) -> list[dict]
    # Reads p_<job_id>.data and applies assignment score formula

def search(query: str, job_id: int | None = None,
           limit: int | None = None) -> list[dict]
    # Backward-compatible alias for ui_search()

def print_results(results: list[dict]) -> None
    # CLI output formatter
```

### `status.py`

```python
def get_job_snapshot(conn: sqlite3.Connection, job_id: int | None = None) -> dict | None
    # Returns one job snapshot for CLI/API use

def get_all_jobs_snapshot(conn: sqlite3.Connection) -> list[dict]
    # Returns all jobs for /jobs API

def print_status(conn: sqlite3.Connection) -> None
    # Prints most recent job summary

def print_stats(conn: sqlite3.Connection) -> None
    # Prints global crawl totals
```

### `server.py`

```python
def serve(host: str = "127.0.0.1", port: int = 8000) -> None
    # Starts ThreadingHTTPServer and initializes DB schema

class CrawlerAPIHandler(BaseHTTPRequestHandler):
    # POST /index
    # POST /pause/<job_id>
    # POST /resume/<job_id>
    # GET  /index/<job_id>
    # GET  /jobs
    # GET  /search
    # GET  /search/assignment
```

---

## 4. SQLite Schema Creation Code

The backend schema should be implemented directly in `db.py:init_schema()`:

```python
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
```

The implementation should also ensure these additive migrations are present:

```python
_migrate_add_column(conn, "pages", "headings", "TEXT")
_migrate_add_column(conn, "crawl_jobs", "back_pressure_events", "INTEGER NOT NULL DEFAULT 0")
_migrate_add_column(conn, "crawl_jobs", "queue_cap", "INTEGER NOT NULL DEFAULT 1000")
```

---

## 5. Crawl Lifecycle Pseudocode

```text
-- index_command(origin_url, max_depth, queue_cap=None) ----------------------

validate_index_request(origin_url, max_depth, queue_cap)
job_id = create_job(origin_url, max_depth, state="running", queue_cap=queue_cap)
print "Crawl started..."
run_job(job_id, max_depth)
print "Crawl finished."


-- create_job(origin_url, max_depth, state, queue_cap) -----------------------

open DB connection
init schema
count active jobs where state in ('running', 'queued', 'pausing')
if active >= MAX_ACTIVE_JOBS:
    raise ValueError

insert crawl_jobs row
insert seed URL into frontier as depth=0, state='pending'
insert seed URL into seen_urls
return job_id


-- run_job(job_id, max_depth) ------------------------------------------------

set_job_state(job_id, "running")
paused = asyncio.run(_run_event_loop(job_id, max_depth, bp_counter))
flush back_pressure_events to crawl_jobs

if paused:
    return

if job state != error:
    export_p_data(job_id)
    set_job_state(job_id, "done", finished_at=now)


-- _run_event_loop(job_id, max_depth, bp_counter) ----------------------------

load job metadata (origin_url, queue_cap)
load pending frontier count
load seen_urls into in-memory set
if pending frontier count == 0:
    print "Nothing to crawl"
    return False

queue   = asyncio.Queue(maxsize=queue_cap)
session, tracker = await fetcher.create_session()
spawn MAX_CONCURRENT worker tasks

loop:
    if pause requested:
        paused = True
        break

    if queue needs refill:
        move frontier rows pending -> queued
        enqueue (url, origin_url, depth) tuples into queue

    if no remaining frontier work and queue is empty:
        break

    periodically flush bp_counter to crawl_jobs
    await sleep(0.1)

cancel workers
close session
if paused:
    mark queued/processing frontier rows back to pending
    set job state to paused
return paused


-- worker(queue, session, tracker, seen, ...) --------------------------------

while True:
    item = await queue.get()
    mark frontier row as processing

    if depth > max_depth:
        mark frontier row as skipped
        queue.task_done()
        continue

    status, html = await fetcher.fetch(session, url, tracker=tracker)
    if status != 200 or html is empty:
        mark frontier row as failed
        queue.task_done()
        continue

    links, body_text, title, headings = parser.parse(html, base_url=url)

    indexer.write_page(
        conn, url, title, body_text, status,
        job_id, origin_url, depth, headings=headings
    )

    if depth < max_depth:
        enqueue_discovered_links(...)

    queue.task_done()
```

---

## 6. Search Lifecycle Pseudocode

```text
-- CLI UI search --------------------------------------------------------------

results = search.ui_search(query, job_id=args.job_id, limit=args.limit)
print_results(results)


-- ui_search(query, job_id=None, limit=None) ---------------------------------

open read-only SQLite connection
rows = db.read_pages_for_ui_search(conn, job_id=job_id)
for each page:
    compute Python-side score from:
        title match
        heading match
        body frequency
        phrase match
        fuzzy match
        depth bonus
sort descending by score
apply optional limit
return results


-- assignment_search(query, job_id=None) -------------------------------------

if job_id is missing:
    resolve latest completed job from SQLite

open data/storage/p_<job_id>.data
for each matching token:
    score += (frequency * 10) + 1000 - (depth * 5)
aggregate by URL
sort descending by score
return results


-- HTTP API search ------------------------------------------------------------

GET /search?query=...&job_id=N
    -> search.ui_search(...)
    -> return JSON with relevant_url, origin_url, depth, optional title/score

GET /search/assignment?query=...&job_id=N
    -> search.assignment_search(...)
    -> return JSON rows directly
```

---

## 7. Backend Command / API Behavior

### CLI command behavior

```text
python -m crawler.main index <origin_url> <max_depth>
  - validates input
  - creates a new crawl job
  - runs the job synchronously
  - prints job ID, origin URL, and crawl completion message

python -m crawler.main search "<query>" [--job <job_id>] [--limit <n>]
  - runs UI search over SQLite-backed indexed pages
  - prints scored results or "No results found."

python -m crawler.main search-assignment "<query>" [--job <job_id>]
  - runs assignment search over exported p_data
  - prints formula-based results or "No results found."

python -m crawler.main status
  - prints the most recent job snapshot

python -m crawler.main stats
  - prints global crawl statistics across all jobs

python -m crawler.main pause <job_id>
  - marks a running/queued job as pausing

python -m crawler.main resume [job_id]
  - resumes the latest or explicit paused job
```

### HTTP API behavior

```text
POST /index
  - accepts JSON: { "origin": "...", "k": <depth>, "queue_cap": <optional> }
  - creates a queued job
  - starts the crawl in a background thread

POST /pause/<job_id>
  - requests pause for a running/queued job

POST /resume/<job_id>
  - resumes a paused job and restarts its worker thread

GET /index/<job_id>
  - returns one job snapshot

GET /jobs
  - returns all job snapshots

GET /search
  - returns UI search results for frontend/backend consumers

GET /search/assignment
  - returns assignment-search results
```

This document treats the API as part of backend implementation scope.
Frontend consumption of these endpoints belongs to the frontend implementation plan.

---

## 8. Minimal Config Values

```python
DB_PATH                 = "crawler.db"
USER_AGENT              = "BLG483CrawlerBot/1.0 (+http://localhost; educational localhost crawler)"
ACCEPT_LANGUAGE         = "en-US,en;q=0.9"

REQUEST_TIMEOUT         = 10
CONNECT_TIMEOUT         = 5
READ_TIMEOUT            = 10
REQUEST_RETRIES         = 2
RETRY_BACKOFF           = 1.5
MAX_REDIRECTS           = 5

MAX_CONCURRENT          = 5
MAX_CONCURRENT_PER_HOST = 5
POLITENESS_DELAY        = 0.2

QUEUE_CAP               = 500
MAX_QUEUE_CAP           = 1000
MAX_ACTIVE_JOBS         = 2

LINKS_PER_PAGE_CAP      = 120
ADAPTIVE_BP_THRESHOLD   = 0.85
FRONTIER_BP_THRESHOLD   = 800
MAX_BODY_SIZE           = 500_000
```

`requirements.txt`:

```text
aiohttp>=3.9
```

The backend dependency list stays intentionally small.

---

## 9. Backend Verification Notes

This implementation plan does **not** own the full dedicated test design. A separate
test-focused agent can expand unit, integration, and regression coverage in its own
document.

The backend implementation owner should still complete the following smoke checks
while building:

- schema initializes successfully and `crawler.db` is created
- a single CLI crawl can start and finish
- active-job cap rejects the third active job under the default configuration
- pause/resume transitions a job through `pausing` -> `paused` -> `queued` -> `running`
- UI search returns SQLite-backed results during or after indexing
- assignment search returns exported `p_<job_id>.data` results after completion
- `/jobs` and `/index/<job_id>` reflect job progress accurately
- API-started jobs run in the background without blocking the server process

Frontend verification and exhaustive automated test coverage are tracked separately.

---

## 10. Step-by-Step Build Order

Build in this order. Each step should leave the backend in a coherent, runnable state.

---

### Step 1 - Skeleton + Config

- Create the `crawler/` package and backend module files
- Write `config.py` with crawler, concurrency, retry, and storage constants
- Add `requirements.txt` with `aiohttp`
- Confirm the backend package imports cleanly

---

### Step 2 - Database Layer

- Implement `db.py`
- Add `get_connection()` with WAL/read-only behavior
- Add `init_schema()` with all backend tables and FTS setup
- Add migration helpers for `headings`, `queue_cap`, and `back_pressure_events`
- Confirm schema creation succeeds on a fresh database

---

### Step 3 - HTML Parsing Layer

- Implement `parser.py`
- Extract title, headings, body text, and links
- Exclude script/style/noscript content
- Cap stored body length using `MAX_BODY_SIZE`

---

### Step 4 - URL Normalization Layer

- Implement `normalizer.py`
- Add canonicalization for relative URLs and fragment stripping
- Add low-value URL filtering with `should_enqueue()`
- Keep same-host restriction optional rather than default

---

### Step 5 - Atomic Index Write Path

- Implement `indexer.py`
- Upsert canonical page rows
- Store headings as JSON
- Insert page discovery rows per job
- Refresh FTS rows transactionally
- Mark frontier rows as done in the same transaction

---

### Step 6 - Search Layer

- Implement `search.py`
- Add Python-side UI search scoring over SQLite rows
- Add assignment search over exported `p_data`
- Keep the two search paths separate in code and API behavior
- Add CLI-friendly result formatting

---

### Step 7 - HTTP Fetch Layer

- Implement `fetcher.py` with `aiohttp`
- Create per-job sessions and politeness trackers
- Add retries, redirect handling, and HTML-only filtering
- Add per-host connector limits and request headers

---

### Step 8 - Worker Loop

- Implement `worker.py`
- Mark frontier rows as processing/failed/skipped appropriately
- Parse successful responses and write pages atomically
- Persist discovered links with page-level dedup and backpressure rules
- Ensure failures never leave frontier rows stranded in `processing`

---

### Step 9 - Orchestrator

- Implement `orchestrator.py`
- Add request validation and active-job-cap enforcement
- Add job creation and seed frontier persistence
- Add `_run_event_loop()` queue refill loop
- Add backpressure counter flushing
- Add pause/resume lifecycle support
- Add post-completion `p_data` export

---

### Step 10 - CLI and API Surface

- Implement `main.py` CLI commands:
  - `index`
  - `search`
  - `search-assignment`
  - `status`
  - `stats`
  - `pause`
  - `resume`
- Implement `server.py` endpoints for job control, snapshots, and search
- Confirm API-started jobs run in background threads

---

### Step 11 - Status and Operational Visibility

- Implement `status.py`
- Add per-job snapshots for CLI/API use
- Report queue depth, in-flight work, failed pages, and backpressure state
- Add global stats for all jobs combined

---

### Step 12 - Backend Hardening Pass

- Recheck resource cleanup in async shutdown paths
- Confirm paused jobs reset `queued`/`processing` frontier rows back to `pending`
- Confirm active-job cap errors are surfaced clearly
- Confirm assignment export failures do not corrupt job completion state
- Confirm read-only search paths behave correctly when the DB is absent or empty

---

### Summary: What This Plan Owns

This document owns backend implementation of:

- crawl job lifecycle
- SQLite schema and persistence
- async fetch/parse/index pipeline
- CLI commands
- HTTP API endpoints
- UI search and assignment search logic
- pause/resume and backpressure behavior

