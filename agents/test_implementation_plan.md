# Web Crawler & Search System - Test Implementation Plan

---

## 1. Scope

This plan defines the verification strategy for the crawler backend, the HTTP API,
and the React frontend.

The test surface is organized around three layers:

- backend unit behavior
- backend integration behavior
- frontend verification behavior

The goal is to confirm that the implemented system matches the documented product
and architecture behavior while keeping verification concerns separate from the
runtime modules.

---

## 2. Final Test Folder Structure

```
project-root/
+-- crawler/
|   +-- tests/
|       +-- test_normalizer.py
|       +-- test_parser.py
|       +-- test_indexer.py
|       +-- test_search.py
|       +-- test_integration.py
+-- frontend/
|   +-- src/
|   +-- ...
+-- README.md
```

The backend test suite lives under `crawler/tests/`.

Frontend verification may remain lightweight and behavior-focused. The important
point is that frontend validation should cover user-visible flows even if those
checks begin as smoke tests.

---

## 3. Test Areas and Responsibilities

| Area | Focus |
|---|---|
| URL normalization | canonicalization, filtering, dedup behavior |
| HTML parsing | link extraction, title extraction, heading extraction, body text rules |
| Atomic indexing | `pages`, `page_discoveries`, `pages_fts`, frontier state changes |
| Search behavior | UI search scoring path and assignment-search export path |
| Job lifecycle | create, run, pause, resume, completion, active-job-cap behavior |
| Backpressure | queue pressure, frontier pressure, per-page link cap, dropped-link accounting |
| API behavior | crawl creation, job snapshots, pause/resume, search endpoints |
| Frontend behavior | crawl form, jobs dashboard, scoped UI search, live refresh, error states |

---

## 4. Backend Unit Test Plan

### `test_normalizer.py`

Purpose:

- verify canonical URL normalization
- verify low-value URL filtering
- verify deduplication helper behavior

Recommended checks:

- relative URL resolution
- fragment stripping
- host/scheme normalization
- invalid scheme rejection
- wiki namespace rejection
- action/revision query rejection
- optional same-origin restriction
- `filter_new()` returns only unseen accepted URLs

### `test_parser.py`

Purpose:

- verify HTML extraction rules independent of network and storage

Recommended checks:

- title extraction
- `h1`, `h2`, `h3` heading extraction
- visible text extraction
- script/style/noscript exclusion
- hyperlink extraction
- malformed HTML tolerance
- heading text stored separately from body text
- empty HTML safety

### `test_indexer.py`

Purpose:

- verify per-page atomic writes and index consistency

Recommended checks:

- insert page row successfully
- upsert same URL without duplicate `pages` rows
- `page_discoveries` row is created for the job
- frontier row is marked `done`
- FTS row is refreshed when the page is rewritten
- headings JSON is stored
- duplicate write remains idempotent

### `test_search.py`

Purpose:

- verify the two search paths independently

Recommended checks for UI search:

- title match boosts score
- heading match contributes score
- body-only match still returns results
- wrong `job_id` returns no results
- multi-word matching behaves sensibly
- results are ordered by descending UI score

Recommended checks for assignment search:

- exported file format is valid
- assignment scoring formula is respected
- multi-word token scores aggregate per URL
- latest completed job fallback works
- wrong job scope returns empty results

---

## 5. Backend Integration Test Plan

### `test_integration.py`

Purpose:

- verify end-to-end crawler behavior across multiple modules together

Recommended integration scenarios:

### Single-job crawl

- start a local fake HTTP site
- crawl from `/`
- confirm expected pages are indexed
- confirm frontier drains to completion
- confirm UI search returns indexed content

### Multi-job isolation

- create two jobs with different origins
- run both jobs
- confirm `page_discoveries` stay job-scoped
- confirm UI search filtering by `job_id` works
- confirm assignment-search exports stay separate per job

### Pause / resume

- start a crawl with enough work to pause mid-run
- request pause
- confirm job reaches `paused`
- confirm `queued` / `processing` rows are reset appropriately
- resume job
- confirm crawl finishes successfully

### Backpressure

- use a fan-out page set with many discovered links
- verify per-page link cap is enforced
- verify deep links are dropped under queue/frontier pressure
- verify backpressure counters increase

### Failure handling

- simulate fetch failure or worker exception
- confirm frontier rows move to `failed`
- confirm rows are not stranded in `processing`
- confirm successful pages still remain queryable

### Active-job cap

- create jobs until the configured active limit is reached
- confirm an additional job request is rejected clearly

---

## 6. API Verification Plan

The API layer should be verified as a separate surface, not only indirectly through
CLI or crawler internals.

Recommended checks:

- `POST /index` starts a job with valid input
- `POST /index` rejects invalid input
- `GET /jobs` returns job snapshots
- `GET /index/<job_id>` returns one job snapshot
- `POST /pause/<job_id>` transitions a running job toward pause
- `POST /resume/<job_id>` resumes a paused job
- `GET /search` returns UI search payload in expected shape
- `GET /search/assignment` returns assignment-search payload in expected shape
- invalid job IDs return proper error responses

---

## 7. Frontend Verification Plan

The frontend should be validated against user-visible behavior, not only static markup.

Core flows:

### Crawl dashboard

- crawl form accepts valid URL, depth, and queue capacity
- invalid values show inline warnings
- crawl button disables when the active-job cap is reached
- jobs list refreshes while active work exists
- pause button disables during `pausing`
- resume button disables when resume is not valid

### Search flow

- user can switch between `crawl` and `search` views
- search can run across all jobs
- search can be scoped to one selected job
- result list shows placeholder, loading, empty, and populated states correctly
- result cards show title, URL, origin URL, depth, and score when available

### Live refresh behavior

- UI search refreshes while indexing is active
- timers clean up correctly when view or activity state changes
- polling failures do not crash the interface

### Responsive behavior

- crawl dashboard collapses to one column on smaller screens
- controls remain clickable and readable on mobile widths

These checks may begin as manual smoke verification if a dedicated frontend runner
is not yet part of the project.

---

## 8. Test Data and Fixtures

The test suite should use deterministic local fixtures wherever possible.

Recommended fixture styles:

- short HTML strings for parser/unit tests
- temporary SQLite databases for index/search tests
- a local fake HTTP server for crawl integration tests
- small two-site topologies for job-isolation tests
- fan-out pages for backpressure tests

Good fixture properties:

- easy to reason about
- small enough to inspect manually
- stable across repeated runs
- explicit about expected titles, headings, and tokens

---

## 9. Execution Strategy

### Backend automated suite

Primary command:

```bash
python -m unittest discover -s crawler/tests -v
```

Useful narrower runs:

```bash
python -m unittest crawler.tests.test_normalizer -v
python -m unittest crawler.tests.test_parser -v
python -m unittest crawler.tests.test_indexer -v
python -m unittest crawler.tests.test_search -v
python -m unittest crawler.tests.test_integration -v
```

### Frontend smoke verification

Recommended manual run order:

1. start backend API
2. start Vite frontend
3. create a crawl job
4. observe `/jobs`-driven updates in the UI
5. run UI search while indexing is active
6. pause and resume a job

---

## 10. Step-by-Step Build Order

### Step 1 - Core backend unit tests

- implement `test_normalizer.py`
- implement `test_parser.py`
- implement `test_indexer.py`
- implement `test_search.py`

### Step 2 - End-to-end backend integration

- implement `test_integration.py`
- cover single-job crawl
- cover multi-job isolation
- cover pause/resume
- cover backpressure
- cover worker failure handling

### Step 3 - API verification pass

- add endpoint-level assertions to the integration suite
- verify request/response shapes and error paths

### Step 4 - Frontend verification pass

- exercise crawl form behavior
- exercise jobs dashboard state transitions
- exercise scoped UI search
- exercise live refresh behavior

### Step 5 - Final test hardening

- remove flaky timing assumptions
- keep fixtures deterministic
- ensure tests clean up temporary files and local servers
- confirm test output is readable enough for debugging

---

## Summary

This document owns verification planning for:

- backend unit behavior
- backend integration behavior
- API endpoint behavior
- frontend smoke behavior
- test execution order and fixture strategy

The purpose of the plan is to keep verification aligned with the implemented product
without coupling tests too tightly to incidental implementation details.
