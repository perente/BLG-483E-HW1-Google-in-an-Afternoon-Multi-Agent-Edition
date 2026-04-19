# BLG 483E - Google in an Afternoon (Multi-Agent Edition)

An asynchronous web crawler and search system with a React frontend.
Supports concurrent multi-job crawling, frontend UI search, and assignment-compatible search through API/CLI.

## Features

- Multi-job crawling: up to 2 concurrent crawl jobs with isolated frontier, seen set, and metrics.
- Frontend UI search with job scope selector: search all jobs or target a specific crawl job.
- UI search: field-weighted relevance over SQLite pages using title, headings, body text, fuzzy matching, and depth bonus. Auto-refreshes every 5 seconds while indexing is active.
- Assignment search: formula-based scoring from per-job exported `p_<job_id>.data` files. Available through API and CLI for completed jobs.
- Backpressure: per-page link cap, adaptive depth-based dropping, URL normalization/filtering, and backpressure event tracking.
- Pause and resume support through both CLI and API.
- Real-time monitoring: frontend polls `/jobs` and shows per-job crawl status.

## Architecture

- Frontend: React + Vite
- Backend API: Python stdlib HTTP server
- Crawl engine: per-job `asyncio` event loop with `aiohttp`
- Storage: SQLite in WAL mode

Each crawl job runs in its own thread with its own event loop, HTTP session, and politeness tracker.

## Quick Start

### Clone the repository

If you are starting from GitHub, clone the repository and enter the project folder:

```bash
git clone <repository-url>
cd BLG-483E-HW1-Google-in-an-Afternoon-Multi-Agent-Edition
```

### Prerequisites

- Python 3.12+
- Node.js 18+

### Install backend dependencies

Backend dependencies are installed through `requirements.txt`, which includes `aiohttp`.

```bash
pip install -r requirements.txt
```

### Install frontend dependencies

```bash
cd frontend
npm install
```

### Start backend

```bash
python -m crawler.server
```

### Start frontend

```bash
cd frontend
npm run dev
```

Open `http://localhost:5173`.

## Typical Local Workflow

1. Start the backend API from the project root.
2. Start the frontend from the `frontend/` directory.
3. Create a crawl job by providing an origin URL, maximum depth, and queue capacity.
4. Monitor job progress from the frontend or the CLI.
5. Run UI search while indexing is still active.
6. Pause and resume a crawl job when needed.
7. Run assignment search after a job has produced its `p_<job_id>.data` export.

## CLI

```bash
python -m crawler.main index https://example.com 2
python -m crawler.main search "python" --job 1 --limit 10
python -m crawler.main search-assignment "python" --job 1
python -m crawler.main status
python -m crawler.main stats
python -m crawler.main pause 1
python -m crawler.main resume
python -m crawler.main resume 3
```

### Using the CLI

The CLI exposes the same core backend behavior without requiring the frontend.

- `index <origin_url> <k>` starts a new crawl job from the given seed URL up to depth `k`
- `status` prints the most recent job snapshot
- `stats` prints global crawl statistics across stored jobs
- `pause <job_id>` requests a pause for a running or queued job
- `resume [job_id]` resumes the latest paused job or a specific paused job
- `search <query>` runs UI search over SQLite-backed indexed pages
- `search-assignment <query>` runs assignment-compatible search over exported per-job data

Optional CLI search arguments:

- `search <query> --job N` limits UI search to a single crawl job
- `search <query> --limit N` limits the number of returned UI search results
- `search-assignment <query> --job N` limits assignment search to one completed job export

Typical CLI-only workflow:

1. Start a crawl with `index <origin_url> <k>`.
2. Check progress with `status` or `stats`.
3. Pause the crawl with `pause <job_id>` if needed.
4. Resume later with `resume [job_id]`.
5. Run `search <query>` for live UI-style search over indexed SQLite content.
6. Run `search-assignment <query>` after export data is available for a completed job.

## API

| Endpoint | Method | Description |
|---|---|---|
| `/index` | POST | Start a crawl job |
| `/index/<job_id>` | GET | Get one job snapshot |
| `/jobs` | GET | List jobs with status snapshots |
| `/pause/<job_id>` | POST | Pause a running or queued job |
| `/resume/<job_id>` | POST | Resume a paused job |
| `/search?query=...&job_id=N` | GET | UI search. Optional `job_id` scope. Used by the frontend. |
| `/search/assignment?query=...&job_id=N` | GET | Assignment search from p_data export. API/CLI only. |

### Example crawl request

```json
POST /index
{
  "origin": "https://example.com",
  "k": 2,
  "queue_cap": 500
}
```

### Example search response

```json
[
  {
    "relevant_url": "https://example.com/docs",
    "origin_url": "https://example.com",
    "depth": 1,
    "title": "Example Docs",
    "score": 87.5
  }
]
```

The HTTP API returns `relevant_url` in UI search responses. Internal search logic and
CLI output use the same field under the name `url`.

## Search Modes

### UI Search

UI search is the frontend search experience. It reads directly from SQLite and is designed for relevance quality:

- title importance
- heading importance
- body term frequency
- phrase matching
- fuzzy matching
- depth bonus

Because it reads from WAL-backed SQLite, it can reflect newly indexed pages while crawling is still active. The frontend auto-refreshes UI search results every 5 seconds during active indexing.

### Assignment Search

Assignment search is kept separate and is available through the API and CLI. It reads from per-job export files:

```text
data/storage/p_<job_id>.data
```

Each line is:

```text
word<TAB>url<TAB>origin_url<TAB>depth<TAB>frequency
```

Scoring formula:

```text
score = (frequency * 10) + 1000 - (depth * 5)
```

This separation keeps the UI search useful while preserving exact assignment-compatible scoring.

## Job States

Each crawl job moves through a small lifecycle:

- `queued`: job has been accepted and is waiting for execution
- `running`: workers are actively crawling and indexing
- `pausing`: pause has been requested and the worker loop is shutting down cleanly
- `paused`: durable state is preserved and the job can be resumed
- `done`: crawl completed successfully
- `error`: crawl stopped because of an unrecoverable failure

The frontend and status commands expose these states directly so job progress can be
inspected without reading the database manually.

## Active Job Cap

- Maximum 2 concurrent active jobs by default
- `running`, `queued`, and `pausing` count toward the cap
- `paused` does not count
- If the cap is full, a new crawl request is rejected instead of being placed in a hidden waiting queue

## Backpressure

- Per-page link cap: 120
- Adaptive threshold: deeper links are dropped under pressure
- Frontier-aware backlog control
- Duplicate suppression is not counted as backpressure

## origin_url Semantics

`origin_url` always means the original seed URL for that crawl job, not the parent page that discovered the link.

## Persistence

- `crawler.db` stores crawl jobs, canonical pages, page discoveries, frontier rows, seen URLs, and FTS support data
- `data/storage/p_<job_id>.data` stores per-job exports for assignment-compatible search
- SQLite runs in WAL mode so UI search can read committed rows while crawling continues

This keeps live product search and assignment-compatible search separate while using
the same crawl output.

## Project Structure

```text
crawler/
  __init__.py
  config.py
  db.py
  fetcher.py
  indexer.py
  main.py
  normalizer.py
  orchestrator.py
  parser.py
  search.py
  server.py
  status.py
  worker.py
  tests/

data/
  storage/

frontend/
  index.html
  package.json
  vite.config.js
  src/
    App.jsx
    components/
      CrawlForm.jsx
      JobsPanel.jsx
      SearchForm.jsx
      SearchResultCard.jsx
      SearchResultsList.jsx
      SystemStatusPanel.jsx

agents/
  backend_implementation_plan.md
  frontend_implementation_plan.md
  test_implementation_plan.md
```

## Limitations

- SQLite is still single-writer
- Assignment search requires crawl completion and does not auto-refresh
- Assignment search is exposed through API/CLI, not the frontend
- Only HTML pages are processed
- No JavaScript rendering
- No robots.txt parsing

## Tests

```bash
python -m unittest discover -s crawler/tests -v
```
