"""
fetcher.py

Async HTTP fetcher using aiohttp.

Politeness state (domain locks, last-request timestamps) is scoped
per-session — not module-global — so multiple concurrent crawl jobs
running in different threads / event loops are safe.
"""

import aiohttp
import asyncio
import sys
import time
from urllib.parse import urlparse

try:
    from . import config
except ImportError:  # Support running as `python crawler/main.py`
    import config


class PolitenessTracker:
    """
    Per-session politeness state.

    Each crawl job gets its own PolitenessTracker (via its own aiohttp session).
    This avoids sharing asyncio.Lock objects across event loops, which would
    cause errors when multiple jobs run in different threads.
    """

    def __init__(self, delay: float = None):
        self._delay = delay if delay is not None else config.POLITENESS_DELAY
        self._domain_locks: dict[str, asyncio.Lock] = {}
        self._last_request_at: dict[str, float] = {}

    def _get_domain_lock(self, domain: str) -> asyncio.Lock:
        lock = self._domain_locks.get(domain)
        if lock is None:
            lock = asyncio.Lock()
            self._domain_locks[domain] = lock
        return lock

    async def wait(self, url: str) -> None:
        """Enforce per-domain politeness delay without serializing the sleep itself."""
        if self._delay <= 0:
            return
        domain = urlparse(url).netloc.lower()
        if not domain:
            return
        lock = self._get_domain_lock(domain)
        async with lock:
            now = time.monotonic()
            last = self._last_request_at.get(domain)
            scheduled_at = now if last is None else max(now, last + self._delay)
            self._last_request_at[domain] = scheduled_at

        wait_time = scheduled_at - time.monotonic()
        if wait_time > 0:
            await asyncio.sleep(wait_time)


def _retry_delay(attempt_number: int, retry_after: str | None = None) -> float:
    if retry_after:
        try:
            return max(float(retry_after), 0.0)
        except ValueError:
            pass
    return config.RETRY_BACKOFF * attempt_number


async def create_session() -> tuple[aiohttp.ClientSession, PolitenessTracker]:
    """
    Create an aiohttp session paired with its own PolitenessTracker.

    Returns (session, politeness_tracker).
    """
    timeout = aiohttp.ClientTimeout(
        total=config.REQUEST_TIMEOUT,
        connect=config.CONNECT_TIMEOUT,
        sock_read=config.READ_TIMEOUT,
    )
    headers = {
        "User-Agent": config.USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": config.ACCEPT_LANGUAGE,
    }
    connector = aiohttp.TCPConnector(
        limit=max(config.MAX_CONCURRENT, 1),
        limit_per_host=max(config.MAX_CONCURRENT_PER_HOST, 1),
        enable_cleanup_closed=sys.version_info < (3, 14, 2),
    )
    session = aiohttp.ClientSession(timeout=timeout, headers=headers, connector=connector)
    tracker = PolitenessTracker()
    return session, tracker


async def fetch(session: aiohttp.ClientSession, url: str,
                tracker: PolitenessTracker | None = None) -> tuple[int, str]:
    """
    Fetch a URL. Returns (status_code, html_text).
    If tracker is provided, enforces per-domain politeness delay.
    """
    last_status = 0

    for attempt in range(config.REQUEST_RETRIES + 1):
        try:
            if tracker:
                await tracker.wait(url)
            async with session.get(
                url,
                allow_redirects=True,
                max_redirects=config.MAX_REDIRECTS,
            ) as response:
                last_status = response.status

                if response.status in {429, 500, 502, 503, 504} and attempt < config.REQUEST_RETRIES:
                    retry_after = response.headers.get("Retry-After")
                    await asyncio.sleep(_retry_delay(attempt + 1, retry_after))
                    continue

                content_type = response.headers.get("Content-Type", "").lower()
                if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                    return (response.status, "")

                html = await response.text(errors="ignore")
                return (response.status, html)

        except (aiohttp.ClientError, asyncio.TimeoutError):
            if attempt < config.REQUEST_RETRIES:
                await asyncio.sleep(_retry_delay(attempt + 1))
                continue
            return (last_status, "")
        except Exception:
            return (last_status, "")

    return (last_status, "")
