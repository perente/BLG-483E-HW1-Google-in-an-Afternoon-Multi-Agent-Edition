# Web Crawler & Search System - Frontend Implementation Plan

---

## 1. Scope and Inputs

This plan defines the **frontend implementation scope** for the React + Vite user
interface.

This frontend plan focuses on implementing the user-facing interface on top of the existing backend contract. 

---

## 2. Final Frontend Folder Structure

```text
frontend/
+-- package.json
+-- vite.config.js
+-- index.html
+-- src/
|   +-- main.jsx
|   +-- App.jsx
|   +-- index.css
|   +-- components/
|       +-- CrawlForm.jsx
|       +-- JobsPanel.jsx
|       +-- SearchForm.jsx
|       +-- SearchResultCard.jsx
|       +-- SearchResultsList.jsx
|       +-- SystemStatusPanel.jsx
```

The frontend remains intentionally small. State ownership should stay close to the top
level `App.jsx`, while presentational concerns live in leaf components.

---

## 3. Each Frontend Module's Exact Purpose

| File | Purpose |
|---|---|
| `main.jsx` | React entrypoint. Mounts the app and loads global styles. |
| `App.jsx` | Main state owner and screen coordinator. Handles polling, API calls, view switching, and top-level UI state. |
| `index.css` | Global visual system: theme variables, layout, panels, controls, states, and responsive rules. |
| `CrawlForm.jsx` | Start-crawl form. Captures origin URL, depth, and queue capacity, validates input, and submits to parent handler. |
| `JobsPanel.jsx` | Displays job cards, active-job counts, key job metrics, and pause/resume controls. |
| `SearchForm.jsx` | Collects UI search query and optional job scope. |
| `SearchResultsList.jsx` | Renders empty/loading/no-results/results states for search output. |
| `SearchResultCard.jsx` | Displays one search result row with title, URL, origin URL, depth, and optional score. |
| `SystemStatusPanel.jsx` | Reusable status panel component for job snapshot presentation. It may remain optional if `JobsPanel` already covers the primary status view. |

---

## 4. Frontend State Model

Top-level UI state should live in `App.jsx`.

Recommended state groups:

### Navigation / view state

- `view`
  - values: `crawl` | `search`

### Job state

- `jobs`
- `jobError`
- polling interval refs / cleanup refs

Derived job state:

- `activeJobs`
- `hasActive`
- `atCap`

### Search state

- `results`
- `searchQuery`
- `searchJobId`
- `searchLoading`
- `searchError`
- search auto-refresh interval refs

The frontend should keep data flow simple:

- `App.jsx` owns network requests and state mutation
- child components receive data + callbacks
- child components do local form-state handling only

---

## 5. API Integration Contract

The frontend should interact only with backend HTTP endpoints and should not contain
backend logic.

### Expected endpoints

```text
POST /index
POST /pause/<job_id>
POST /resume/<job_id>
GET  /jobs
GET  /index/<job_id>
GET  /search
```

Assignment-search UI is **not** part of the main frontend scope in this plan. The
frontend should focus on UI search and job monitoring.

### Request/response expectations

#### Start crawl

```text
POST /index
body: { origin, k, queue_cap }
response: { job_id, status }
```

#### Jobs list

`GET /jobs` returns job snapshots used by the crawl dashboard. The frontend should
expect fields such as:

- `job_id`
- `origin_url`
- `max_depth`
- `queue_cap`
- `status`
- `indexed_pages`
- `discovered_pages`
- `queue_depth`
- `in_flight`
- `back_pressure`
- `back_pressure_events`
- `failed_pages`
- optional `error`

#### UI search

```text
GET /search?query=...&job_id=...
```

Expected result fields:

- `relevant_url`
- `origin_url`
- `depth`
- optional `title`
- optional `score`

### Development proxy

`vite.config.js` should proxy backend calls to the local Python API server:

```text
/index   -> http://localhost:8000
/search  -> http://localhost:8000
/jobs    -> http://localhost:8000
/pause   -> http://localhost:8000
/resume  -> http://localhost:8000
```

This keeps frontend code simple by allowing relative fetch paths.

---

## 6. Component Behavior Guidelines

### `App.jsx`

Responsibilities:

- fetch `/jobs` on initial load
- poll `/jobs` every few seconds
- start crawls through `POST /index`
- pause and resume jobs
- run UI search through `/search`
- auto-refresh search results while indexing is active
- switch between `crawl` and `search` views

The component should prefer a small number of focused handlers:

- `pollJobs()`
- `handleStartCrawl()`
- `handlePause()`
- `handleResume()`
- `runSearch()`

### `CrawlForm.jsx`

Responsibilities:

- collect `origin`
- collect depth `k`
- collect `queueCap`
- validate:
  - URL starts with `http://` or `https://`
  - depth is numeric and bounded
  - queue capacity is numeric and bounded
- disable submission when active-job cap is reached

### `JobsPanel.jsx`

Responsibilities:

- sort jobs so active jobs appear first
- show only a manageable number of cards in the main view
- display key metrics in readable card form
- expose Pause / Resume buttons
- respect active-job-cap constraints when enabling Resume

The panel should clearly distinguish:

- `running`
- `queued`
- `pausing`
- `paused`
- `done`
- `error`

### `SearchForm.jsx`

Responsibilities:

- collect query string
- allow searching all jobs or one selected job
- keep submission lightweight
- disable the search button while loading or when the query is empty

### `SearchResultsList.jsx`

Responsibilities:

- show placeholder state before first search
- show loading state
- show no-result state
- render result cards

### `SearchResultCard.jsx`

Responsibilities:

- render decoded URL safely
- show title when available
- show origin URL and depth
- show score if present
- open result URLs in a new tab

---

## 7. UI / UX Direction

The frontend should preserve the current visual direction:

- terminal-inspired / control-room feel
- dark surfaces with amber/green/blue/red status accents
- compact, high-signal information density
- clear distinction between control panels and results panels

Important UX rules:

- primary actions should be obvious
- polling/active indexing should be visible without being noisy
- errors should be surfaced inline near the relevant action
- search scope should always be explicit
- active-job-cap state should be visible in crawl controls

Responsive expectations:

- two-column crawl layout on desktop
- single-column stacking on narrow screens
- controls remain usable on mobile widths

---

## 8. Frontend Data-Flow Pseudocode

```text
on app mount:
    call pollJobs()
    start jobs polling interval

pollJobs():
    GET /jobs
    update jobs state

handleStartCrawl({ origin, k, queueCap }):
    POST /index
    if success:
        refresh jobs
        stay on crawl view
    if error:
        show jobError

handlePause(jobId):
    POST /pause/<jobId>
    refresh jobs

handleResume(jobId):
    POST /resume/<jobId>
    refresh jobs

runSearch(query, jobId, silent=False):
    GET /search?query=...&job_id=...
    update results + search state
    switch to search view

if active jobs exist and search results are visible:
    refresh the same search periodically
```

---

## 9. Step-by-Step Build Order

### Step 1 - Frontend Skeleton

- create `main.jsx`, `App.jsx`, and base component files
- wire React root rendering
- add Vite React configuration

### Step 2 - Global Styling

- establish theme variables in `index.css`
- define layout containers, panels, buttons, inputs, badges, and notices
- add responsive rules for desktop/mobile layout

### Step 3 - Crawl Dashboard

- implement `CrawlForm.jsx`
- implement `JobsPanel.jsx`
- connect start/pause/resume handlers in `App.jsx`
- connect periodic `/jobs` polling

### Step 4 - Search Flow

- implement `SearchForm.jsx`
- implement `SearchResultsList.jsx`
- implement `SearchResultCard.jsx`
- connect UI search requests and result rendering

### Step 5 - Live Refresh Behavior

- auto-refresh search while active indexing exists
- ensure polling and search refresh timers clean up correctly
- avoid duplicate intervals on rerender

### Step 6 - Status Polish

- improve loading, empty, and error states
- verify badge/status mapping
- ensure action disabling matches backend job semantics

### Step 7 - Final Frontend Pass

- verify responsive layout
- verify proxy-based API requests in local development
- confirm no frontend action assumes assignment-search UI support

---

## 10. Frontend Verification Notes

The frontend implementation owner should at minimum verify:

- the crawl form validates obvious bad input
- the crawl button disables when the active-job cap is reached
- the jobs panel refreshes while crawls are active
- pause and resume buttons reflect valid job states
- the search form can scope to all jobs or one job
- search results refresh while indexing is active
- no-result and error states render clearly
- mobile layout remains usable

---

## Summary: What This Plan Owns

This document owns frontend implementation of:

- React app structure
- top-level UI state and polling flow
- crawl creation UI
- jobs/status dashboard UI
- UI search flow and search result presentation
- visual system and responsive layout
