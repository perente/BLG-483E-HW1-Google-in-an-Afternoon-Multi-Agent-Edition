# Web Crawler & Search System - Architecture Design v2

> Revised from v1. Changes: multi-job execution, dual search paths, frontend/API
> support, pause/resume lifecycle, and adaptive backpressure with durable frontier state.

---

## 1. Architecture Overview

The system is a single-machine crawler and search application with four logical layers:

- **Frontend layer** - React + Vite UI for crawl creation, search, and status monitoring
- **Query/control layer** - CLI plus HTTP API implemented with Python stdlib server utilities
- **Crawl engine** - per-job `asyncio` worker loop with bounded concurrency
- **Persistence layer** - SQLite in WAL mode plus per-job `p_<job_id>.data` exports

The backend supports multiple crawl jobs. Each job has isolated crawl state in the
database and runs with its own async HTTP session, politeness tracker, frontier
queue refill loop, and shared seen set.

Concurrency is hybrid by design:

- **Across jobs:** separate background threads when jobs are started through the API
- **Within one job:** `asyncio` tasks for concurrent fetch/parse/index work

SQLite WAL mode allows UI search to read committed data while the crawler writes.
Assignment-compatible search is intentionally separate and reads from per-job export
files after crawl completion.

**Languages / runtime:** Python 3.12+ for backend, JavaScript/React for frontend.  
**External dependency:** `aiohttp` for outbound async HTTP fetching in the crawler fetcher.

---

## 2. Main Components and Responsibilities

| Component | Module | Responsibility |
|---|---|---|
| CLI | `main.py` | Parses commands and dispatches to orchestrator, search, or status |
| HTTP API | `server.py` | Stdlib HTTP server layer that exposes crawl, status, pause/resume, and search endpoints |
| Frontend | `frontend/src/*` | UI for crawl submission, job monitoring, and UI search |
| Orchestrator | `orchestrator.py` | Creates jobs, rejects new jobs when the active-job cap is full, runs/resumes jobs, and manages queue refill loop |
| Frontier queue | `asyncio.Queue` + `frontier` table | In-memory execution queue backed by durable frontier state in SQLite |
| Worker pool | `worker.py` | Async workers that fetch, parse, index, and enqueue discovered links |
| Fetcher | `fetcher.py` | `aiohttp` session creation, retries, redirects, content-type checks, politeness tracking |
| Parser | `parser.py` | `html.parser`-based extraction of links, title, headings, and body text |
| Normalizer | `normalizer.py` | URL canonicalization plus low-value link filtering |
| Indexer | `indexer.py` | Atomic write of `pages`, `page_discoveries`, FTS row update, and frontier completion |
| Search | `search.py` | UI search over SQLite and assignment search over `p_<job_id>.data` exports |
| Status | `status.py` | Job snapshots, aggregate counts, CLI/API status formatting |
| DB layer | `db.py` | Connection factory, schema creation, WAL setup, and `p_data` export |

---

## 3. Data Flow: Crawl -> Search

```text
Seed URL (depth 0)
    |
    v
create_job()
    |
    v
frontier table (pending) + seen_urls
    |
    v
per-job asyncio.Queue refill loop
    |
    v
Worker dequeues (url, origin_url, depth)
    |
    v
Fetcher -> HTTP GET with retries + politeness
    |
    v
Parser -> extract links + title + headings + body text
    |
    v
Normalizer -> canonicalize + filter low-value URLs
    |
    +--> accepted links -> frontier insert + seen_urls insert
    |
    v
Indexer (single transaction):
  UPSERT pages
  INSERT page_discoveries
  refresh pages_fts row
  mark frontier row as done
    |
    +--> UI search reads committed SQLite data at any time
    |
    +--> on job completion: export_p_data(job_id)
             |
             v
       Assignment search reads p_<job_id>.data
```

Two different search products are built from the crawl output:

- **UI search** reads live SQLite-backed page data and is optimized for relevance quality
- **Assignment search** reads exported per-job files and preserves the assignment scoring formula

---

## 4. Concurrency Model

The system does **not** use a single global event loop for the entire product.
Instead, it uses:

- **One OS thread per active crawl job** when jobs are started from the HTTP API
- **One `asyncio` event loop per running job**
- **Multiple async worker tasks inside that event loop**

This model matches the product requirement for multiple isolated crawl jobs while
keeping each job internally async and lightweight.

The active-job cap is enforced at job creation time. If the configured limit is
already reached, the orchestrator rejects the new job request with an error rather
than silently placing it into an additional waiting queue.

### Within a single job

`orchestrator._run_event_loop()` creates:

- a bounded `asyncio.Queue`
- one shared `aiohttp.ClientSession`
- one per-job `PolitenessTracker`
- `MAX_CONCURRENT` async worker tasks

Workers do:

1. dequeue a frontier item
2. mark it `processing`
3. fetch the page
4. parse content
5. atomically index the page
6. persist discovered links to frontier/seen storage

### Across multiple jobs

`server.py` starts each crawl job in a background thread. Each thread calls
`orchestrator.run_job()`, which in turn creates its own event loop via `asyncio.run(...)`.

### Why this hybrid model

- **Why not only threads:** the per-job fetch work is still I/O-bound, so `asyncio`
  keeps the worker pool efficient within each job.
- **Why not only one global event loop:** the API needs multiple active jobs at once,
  and per-job thread isolation avoids sharing async session/lock state between jobs.
- **Why not multiprocessing:** shared database coordination and exact per-job seen-state
  would become more complex than needed for a single-machine educational system.

---

## 5. Back Pressure Strategy

Backpressure is a combination of durable and in-memory mechanisms, all configured
from `config.py`:

```python
MAX_CONCURRENT         = 5
QUEUE_CAP              = 500
LINKS_PER_PAGE_CAP     = 120
ADAPTIVE_BP_THRESHOLD  = 0.85
FRONTIER_BP_THRESHOLD  = 800
POLITENESS_DELAY       = 0.2
```

- **Bounded in-memory queue:** each job queue has a max size (`queue_cap` per job).
- **Refill threshold:** the orchestrator refills from durable frontier only when the
  in-memory queue drops below a threshold.
- **Per-page link cap:** only the first `LINKS_PER_PAGE_CAP` normalized links from a page
  are considered for enqueue.
- **Adaptive pressure drop:** if queue fill is high, deeper links (`next_depth > 1`) are dropped.
- **Frontier-aware pressure drop:** if pending frontier rows already exceed
  `FRONTIER_BP_THRESHOLD`, deeper links are dropped even if the in-memory queue still has room.
- **Politeness delay:** per-domain request spacing reduces burst pressure against one host.
- **Backpressure accounting:** each dropped link under pressure increments the job's
  `back_pressure_events` counter.

The important design choice is that not all pressure handling blocks producers.
Some pressure responses are **selective dropping** of lower-value deeper links,
which keeps shallower pages prioritized and prevents unbounded backlog growth.

---

## 6. Persistence / Database Design

SQLite runs in **WAL mode** (`journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=3000`).
This supports concurrent read access during crawl writes and keeps the architecture simple.

### 6.1 Schema

#### `crawl_jobs` - durable job metadata and lifecycle

```sql
CREATE TABLE crawl_jobs (
  id                    INTEGER PRIMARY KEY,
  origin_url            TEXT    NOT NULL,
  max_depth             INTEGER NOT NULL,
  queue_cap             INTEGER NOT NULL DEFAULT 1000,
  state                 TEXT    NOT NULL DEFAULT 'running',
  started_at            INTEGER NOT NULL,
  finished_at           INTEGER,
  back_pressure_events  INTEGER NOT NULL DEFAULT 0
);
```

This table is the source of truth for job state, active-job limits, queue cap,
and pause/resume status.

#### `pages` - canonical page storage

```sql
CREATE TABLE pages (
  id          INTEGER PRIMARY KEY,
  url         TEXT    NOT NULL UNIQUE,
  title       TEXT,
  headings    TEXT,
  body_text   TEXT,
  fetched_at  INTEGER NOT NULL,
  status      INTEGER NOT NULL
);
CREATE INDEX idx_pages_url ON pages(url);
```

`headings` is stored as JSON so UI search can give different weights to `h1`, `h2`, and `h3`.
It is used for structured scoring in Python rather than as a separate FTS column.

#### `page_discoveries` - crawl context per job

```sql
CREATE TABLE page_discoveries (
  id          INTEGER PRIMARY KEY,
  page_id     INTEGER NOT NULL REFERENCES pages(id),
  job_id      INTEGER NOT NULL REFERENCES crawl_jobs(id),
  origin_url  TEXT    NOT NULL,
  depth       INTEGER NOT NULL,
  UNIQUE (page_id, job_id)
);
CREATE INDEX idx_pd_job  ON page_discoveries(job_id);
CREATE INDEX idx_pd_page ON page_discoveries(page_id);
```

This is the key multi-job design choice: the same canonical page content can be shared
in `pages`, while each crawl job keeps its own `(origin_url, depth)` view in
`page_discoveries`.

#### `frontier` - durable crawl backlog

```sql
CREATE TABLE frontier (
  id          INTEGER PRIMARY KEY,
  job_id      INTEGER NOT NULL REFERENCES crawl_jobs(id),
  url         TEXT    NOT NULL,
  origin_url  TEXT    NOT NULL,
  depth       INTEGER NOT NULL,
  state       TEXT    NOT NULL DEFAULT 'pending',
  enqueued_at INTEGER NOT NULL,
  UNIQUE (job_id, url)
);
CREATE INDEX idx_frontier_state ON frontier(job_id, state);
```

The durable frontier supports these states in practice:

- `pending`
- `queued`
- `processing`
- `done`
- `failed`
- `skipped`

This is more expressive than a purely in-memory queue and is what makes pause/resume
and crash-tolerant recovery possible.

#### `seen_urls` - exact deduplication journal

```sql
CREATE TABLE seen_urls (
  url     TEXT    NOT NULL,
  job_id  INTEGER NOT NULL REFERENCES crawl_jobs(id),
  PRIMARY KEY (url, job_id)
);
```

The in-memory seen set is reconstructed from this table per job.

#### `pages_fts` - FTS5 support table

```sql
CREATE VIRTUAL TABLE pages_fts USING fts5(
  title,
  body_text,
  content='pages',
  content_rowid='id',
  tokenize='porter unicode61'
);
```

FTS5 is maintained transactionally with page writes, but it is **not** the main scoring
path for UI search. The `pages_fts` table indexes `title` and `body_text`; `headings`
remain in `pages.headings` and are read separately for structured scoring in Python.

### 6.2 Search Model

The product has two search paths.

#### UI search

UI search:

- opens a read-only SQLite connection
- reads `pages` joined with `page_discoveries`
- computes ranking in Python
- uses title, heading, body frequency, phrase match, fuzzy match, and depth bonus
- reads headings from `pages.headings`, not from a separate FTS field
- optionally filters by `job_id`

This choice makes the ranking logic easy to explain and tune for the frontend.

#### Assignment search

Assignment search:

- resolves a job ID (explicit or latest completed)
- reads `data/storage/p_<job_id>.data`
- applies the course formula:

```text
score = (frequency * 10) + 1000 - (depth * 5)
```

- sums token scores across multi-word queries

This keeps assignment compatibility separate from the richer UI relevance model.

---

## 7. Search While Indexing Is Active

UI search works during active indexing because it uses a **dedicated read-only SQLite
connection** against a WAL-mode database.

This gives the search path three useful properties:

- readers do not block the active crawler write transaction
- search sees only committed pages
- results can be refreshed repeatedly from the frontend while a job is still running

The frontend uses the API to poll job status and can re-run UI search while indexing
continues. This is a core product behavior, not just an implementation side effect.

Assignment search is different: it depends on per-job export files and is therefore
expected mainly for completed jobs.

---

## 8. Consistency Guarantees

### 8.1 Transaction boundaries

Each indexed page is written atomically in `indexer.write_page(...)`:

```python
with conn:
    upsert page in pages, including headings JSON
    insert discovery row in page_discoveries
    refresh pages_fts row
    mark frontier row as done
```

These changes succeed together or fail together.

### 8.2 Preventing partial crawl state

Workers explicitly move frontier rows through durable states:

- `pending` / `queued` -> `processing` when work starts
- `processing` -> `done` after a successful index write
- `processing` -> `failed` on fetch or worker failure
- `queued` / `processing` -> `pending` again when resuming a paused job

This prevents a page from being left permanently stranded in a transient state.

### 8.3 Pause/resume consistency

Pause is a coordinated state transition:

1. a pause request changes the job state to `pausing`
2. the orchestrator loop notices this state
3. worker tasks are cancelled
4. frontier rows in `queued` or `processing` are reset to `pending`
5. the job state becomes `paused`

Resume reverses this by resetting recoverable frontier rows to `pending` and then
starting the job again from durable state.

### 8.4 Search consistency

UI search only sees committed page rows. It may not include pages being
processed by workers, which is correct for a live system. Assignment search only sees
the exported snapshot for a completed job.

---

## 9. aiohttp vs Standard Library

`aiohttp` is the one backend dependency outside the standard library. It is used
by the crawler fetcher for outbound HTTP requests, while the HTTP API itself is
implemented with Python's standard library server utilities. The justification
follows directly from the architecture because each running job uses its own async
HTTP session and connector settings.

Why `aiohttp` fits this design:

- native `asyncio` integration
- per-job connection pooling
- request timeouts and redirect handling
- retry-friendly error handling
- easy session-level headers (`User-Agent`, `Accept-Language`)
- clean per-host connection limits

Why stdlib alternatives were not chosen:

- `urllib.request` and `http.client` are synchronous
- wrapping sync calls in threads would undercut the per-job async design
- raw socket HTTP would add unnecessary protocol complexity for an educational crawler

**Decision:** keep `aiohttp`, and keep the rest of the stack lightweight.

---

## 10. Resume Strategy

Resume is job-specific and durable.

When resuming a paused job:

1. read the target job from `crawl_jobs`
2. verify it is in `paused` state
3. reset frontier rows in `processing` or `queued` back to `pending`
4. set the job state to `queued`
5. start a fresh job event loop for that job
6. rebuild in-memory state (`seen` set and queue) from SQLite

Queue reconstruction is handled by:

- loading `seen_urls` into an in-memory set
- counting pending frontier rows
- refilling the in-memory queue from durable frontier rows in depth/enqueue order

If there are no pending rows, the job exits cleanly with nothing to crawl.

---

## 11. Key Tradeoffs and Rejected Alternatives

| Decision | Chosen | Rejected | Reason |
|---|---|---|---|
| Job concurrency | thread-per-job + `asyncio` within job | single global event loop | Per-job isolation fits pause/resume and API-triggered parallel jobs |
| Worker concurrency | `asyncio` tasks | pure threading | HTTP fetching is I/O-bound and async fits `aiohttp` naturally |
| Search model | dual search paths | one merged search function | UI relevance and assignment scoring have different goals |
| UI ranking | Python field-weighted scoring | FTS-only BM25 ranking | Easier to tune title/headings/depth/fuzzy behavior for product UX |
| Assignment search | per-job export files | live SQLite scoring | Preserves exact assignment-style format and decouples it from UI logic |
| Deduplication | in-memory set + `seen_urls` table | in-memory only | Needed for durable per-job recovery |
| Frontier design | durable `frontier` table + queue refill | queue-only design | Required for pause/resume and multi-job observability |
| Backpressure | queue cap + link cap + adaptive depth dropping | queue cap only | Better control of backlog growth and shallow-page priority |
| HTTP client | `aiohttp` | stdlib sync HTTP | Native async support and better fit for the worker model |

---

## 12. Module / File Structure

```text
project-root/
+-- crawler/
|   +-- __init__.py
|   +-- main.py           # CLI entrypoint
|   +-- server.py         # HTTP API server for frontend + local clients
|   +-- config.py         # Concurrency, politeness, backpressure, storage config
|   +-- db.py             # Connections, schema init, WAL setup, p_data export
|   +-- orchestrator.py   # Job creation, lifecycle, queue refill, run/resume/pause
|   +-- worker.py         # Async worker loop
|   +-- fetcher.py        # aiohttp session + fetch logic + politeness tracker
|   +-- parser.py         # HTML parsing: links, title, headings, body text
|   +-- normalizer.py     # URL canonicalization and enqueue filtering
|   +-- indexer.py        # Atomic page/discovery/FTS/frontier write
|   +-- search.py         # UI search + assignment search
|   +-- status.py         # CLI/API job snapshots and stats
|   +-- tests/
+-- frontend/
|   +-- src/
|   |   +-- App.jsx
|   |   +-- components/
|   |       +-- CrawlForm.jsx
|   |       +-- JobsPanel.jsx
|   |       +-- SearchForm.jsx
|   |       +-- SearchResultCard.jsx
|   |       +-- SearchResultsList.jsx
|   |       +-- SystemStatusPanel.jsx
|   +-- vite.config.js
+-- data/
|   +-- storage/          # per-job p_<job_id>.data exports
+-- crawler.db            # created at runtime
```

### Dependency graph

```text
crawler/main.py
 +-- crawler/orchestrator.py -> crawler/worker.py -> crawler/fetcher.py
 |                                               -> crawler/parser.py
 |                                               -> crawler/normalizer.py
 |                                               -> crawler/indexer.py -> crawler/db.py
 +-- crawler/search.py -> crawler/db.py
 +-- crawler/status.py

crawler/server.py
 +-- crawler/orchestrator.py
 +-- crawler/search.py
 +-- crawler/status.py
 +-- crawler/db.py

frontend/src/*
 +-- HTTP calls -> crawler/server.py endpoints
```

The frontend never talks to SQLite directly. All frontend state flows through the API.

---

## CLI Reference

```text
index <origin_url> <k>         Start a new crawl job
search <query>                 UI search over indexed SQLite pages
search-assignment <query>      Assignment-compatible search over exported p_data
status                         Show the most recent crawl job snapshot
stats                          Show global crawl statistics
pause <job_id>                 Request pause for a running/queued job
resume [job_id]                Resume the latest or specified paused job
```
