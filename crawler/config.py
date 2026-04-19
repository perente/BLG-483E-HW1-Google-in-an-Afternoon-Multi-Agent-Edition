import os
from pathlib import Path

DB_PATH = "crawler.db"

# Use a descriptive crawler identity so websites can distinguish this tool
# from an anonymous or spoofed browser client.
USER_AGENT = "BLG483CrawlerBot/1.0 (+http://localhost; educational localhost crawler)"

ACCEPT_LANGUAGE = "en-US,en;q=0.9"

REQUEST_TIMEOUT = 10  # seconds
CONNECT_TIMEOUT = 5  # seconds
READ_TIMEOUT = 10  # seconds
REQUEST_RETRIES = 2
RETRY_BACKOFF = 1.5  # seconds, multiplied by attempt number
MAX_REDIRECTS = 5

MAX_CONCURRENT = 5
MAX_CONCURRENT_PER_HOST = 5

POLITENESS_DELAY = 0.2  # seconds between requests to the same domain

QUEUE_CAP = 500
MAX_QUEUE_CAP = 1000

# ── Multi-job ────────────────────────────────────────────────────
# Maximum number of concurrently active crawl jobs.
# Jobs in 'running' or 'queued' state count toward this cap.
# Paused jobs do NOT count — they are suspended and not consuming resources.
MAX_ACTIVE_JOBS = 2

# ── Backpressure ─────────────────────────────────────────────────
# Per-page link cap: at most this many links enqueued from a single page
# after normalization, filtering, and page-level deduplication.
LINKS_PER_PAGE_CAP = 120

# Adaptive back pressure threshold: fraction of queue capacity.
# When queue fill >= this fraction, deeper links (next_depth > 1) are
# dropped immediately to prioritise shallower, higher-value pages.
ADAPTIVE_BP_THRESHOLD = 0.85

# Frontier-aware backpressure: when the number of 'pending' rows in the
# frontier DB exceeds this threshold, deeper links (next_depth > 1) are
# dropped even if the in-memory queue has capacity.  This prevents the
# durable frontier from accumulating unbounded backlog.
FRONTIER_BP_THRESHOLD = 800

# ── Body protection ─────────────────────────────────────────────
# Cap body text storage to avoid oversized rows in SQLite.
MAX_BODY_SIZE = 500_000  # characters

# ── Storage ──────────────────────────────────────────────────────
# Directory for per-job p_<job_id>.data exports (assignment search).
STORAGE_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent / "data" / "storage"
