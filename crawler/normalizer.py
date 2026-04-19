"""
normalizer.py

URL normalisation and filtering.

Two separate concerns:
  canonicalize(url, base)  — pure URL canonicalisation (scheme, host, fragment)
  should_enqueue(url, ...) — content-quality / low-value link filtering

Filter categories applied by should_enqueue():
  1. Wiki namespace filter  — skips /Special:, /Talk:, /User:, /File:, etc.
  2. Edit/action filter     — skips ?action=edit, ?oldid=, ?diff=, etc.
  3. Same-host restriction  — OFF by default. Pass restrict_to_origin=True.
"""

import re
from urllib.parse import urljoin, urlparse, urlunparse, parse_qs, unquote


_ALLOWED_SCHEMES = {"http", "https"}

# ---------------------------------------------------------------------------
# Wiki namespace prefixes — path segments indicating non-content pages.
# ---------------------------------------------------------------------------
_WIKI_SKIP_NAMESPACES = {
    "special", "special_talk",
    "talk", "user", "user_talk", "wikipedia", "wikipedia_talk",
    "file", "file_talk", "mediawiki", "mediawiki_talk", "template",
    "template_talk", "help", "help_talk", "category", "category_talk",
    "portal", "portal_talk", "timedtext", "timedtext_talk",
    "module", "module_talk",
    # Turkish Wikipedia equivalents
    "özel", "özel_tartışma",
    "kullanıcı", "dosya", "vikipedi", "şablon", "yardım",
    "kategori", "kategori_tartışma",
    "portal_tartışma",
}

_WIKI_NS_RE = re.compile(
    r"/(?:" + "|".join(re.escape(ns) for ns in _WIKI_SKIP_NAMESPACES) + r"):",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Query-string parameters that indicate a non-canonical page view.
# ---------------------------------------------------------------------------
_SKIP_QUERY_PARAMS = {
    "action",       # ?action=edit, ?action=history, ?action=raw
    "oldid",        # ?oldid=12345 — specific revision
    "diff",         # ?diff=123    — diff view
    "curid",        # internal page ID redirect
    "printable",
    "mobileaction",
    "veaction",
    "redlink",
}


def canonicalize(url: str, base: str = "") -> str | None:
    """
    Canonicalise a URL.  Returns None if the URL is unfetchable.
    Does NOT apply content-quality filters — call should_enqueue() for that.
    """
    try:
        if base:
            url = urljoin(base, url)

        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()

        if scheme not in _ALLOWED_SCHEMES:
            return None
        if not netloc:
            return None

        normalized = parsed._replace(
            scheme=scheme,
            netloc=netloc,
            fragment="",
        )
        return urlunparse(normalized)
    except Exception:
        return None


def should_enqueue(
    url: str,
    origin: str | None = None,
    restrict_to_origin: bool = False,
) -> bool:
    """
    Return True if url is worth crawling, False if it should be dropped.

    Filters applied (in order, cheapest first):
      1. Wiki namespace check  — path contains /Namespace:
      2. Action/query check    — query string contains low-value params
      3. Same-host restriction — only if restrict_to_origin=True (off by default)

    Called after canonicalize() so url is already canonical.
    External links are allowed by default (restrict_to_origin=False).
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    path = unquote(parsed.path or "")

    # 1. Wiki namespace filter
    if _WIKI_NS_RE.search(path):
        return False

    # 2. Edit / action / revision filter
    if parsed.query:
        try:
            params = parse_qs(parsed.query, keep_blank_values=False)
        except Exception:
            params = {}
        if _SKIP_QUERY_PARAMS.intersection(params.keys()):
            return False

    # 3. Same-host restriction — off by default
    if restrict_to_origin and origin:
        try:
            if urlparse(url).netloc.lower() != urlparse(origin).netloc.lower():
                return False
        except Exception:
            return False

    return True


def filter_new(links: list[str], seen: set[str], base: str = "",
               origin: str | None = None) -> list[str]:
    """
    Canonicalize, quality-filter, and deduplicate links against seen set.
    Returns only new, high-quality URLs.
    """
    result = []
    for link in links:
        url = canonicalize(link, base)
        if url is None or url in seen:
            continue
        if not should_enqueue(url, origin=origin):
            continue
        seen.add(url)
        result.append(url)
    return result