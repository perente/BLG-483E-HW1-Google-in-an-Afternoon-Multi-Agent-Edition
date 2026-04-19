# Multi-Agent Web Crawler and Search System - PRD

## Goal
Build a localhost web crawler and search system that can:
- crawl from a given origin URL up to a maximum depth `k`
- support multiple crawl jobs with isolated job state
- avoid crawling the same page more than once within a job
- store discovered pages and searchable index data persistently
- provide live UI search over indexed content during crawling
- provide assignment-compatible search from exported per-job data
- expose indexing progress and system state through CLI, API, and frontend
- support pause/resume for crawl jobs
- support controlled load through back pressure
- be designed using a multi-agent AI workflow

## Assumptions
- The system runs on a single machine
- Only HTML pages are processed
- `Depth(origin) = 0`
- URLs are normalized for deduplication
- `origin_url` always refers to the original seed URL of a crawl job
- Simple and explainable keyword-based relevance is sufficient for UI search
- Assignment-compatible search is separate from UI search

## Functional Requirements
- `index(origin, k)`
- depth-limited crawling
- multi-job crawl support
- duplicate prevention per job
- link extraction and normalization
- persistent storage (SQLite)
- UI search over SQLite-backed indexed pages
- assignment search over `p_<job_id>.data` exports
- incremental indexing (UI search works during indexing)
- job-scoped search
- pause/resume support
- back pressure (bounded queue / rate limiting / link dropping under pressure)
- CLI interface
- HTTP API interface
- frontend interface
- system state visibility

## Non-Functional Requirements
- scalable on a single machine
- simple and explainable architecture
- fault tolerant enough for local pause/resume workflows
- local execution only
- clear isolation between crawl jobs
- persistent and inspectable system state

## Constraints
- must run on localhost
- must remain SQLite-based for storage
- avoid heavy external libraries and infrastructure
- must demonstrate multi-agent workflow
- should remain educational and easy to explain

## Non-Goals
- distributed crawling
- advanced ranking algorithms
- semantic/vector search
- full browser rendering
- production-grade deployment architecture
- robots.txt support as a required completed feature

## Acceptance Criteria
- crawl works with depth `k`
- multiple jobs can exist with isolated state
- no duplicate URLs are crawled within a job
- UI search returns results from indexed content during crawling
- assignment search returns results from exported per-job data
- search preserves correct `url`, `origin_url`, and `depth` semantics
- job-scoped search does not leak results across jobs
- pause/resume works
- back pressure exists
- CLI works
- API works
- frontend works
- documentation files included

## CLI Commands (Suggested)
`index <origin> <k>`

`search <query>`

`search-assignment <query>`

`status`

`pause <job_id>`

`resume [job_id]`

## Key Design Questions
- How to design the frontier queue for multi-job crawling?
- How to implement back pressure without losing important shallow pages?
- How to store index data efficiently while keeping search available during indexing?
- How to separate UI search from assignment-compatible search cleanly?
- How to preserve job isolation across crawl state, search, and exports?
- How to resume after interruption or pause?
- How should CLI, API, and frontend map to the same backend product model?
