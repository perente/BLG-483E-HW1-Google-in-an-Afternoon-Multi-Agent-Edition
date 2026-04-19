"""
search.py

Two separate search implementations:

1. ui_search()  — Rich, field-weighted search over SQLite pages.
   - Used by the frontend and /search API endpoint.
   - Scores using title, headings, body frequency, fuzzy matching, depth.
   - Works during active indexing via read-only connection + WAL.

2. assignment_search()  — Raw-formula search over p_<job_id>.data exports.
   - Used by the assignment-compatible /search/assignment endpoint.
   - Formula: score = (frequency * 10) + 1000 - (depth * 5)
   - Only available for completed jobs (requires exported data file).

These are intentionally separate because the UI search aims for relevance
quality, while the assignment search satisfies the required scoring formula.
Merging them would weaken the UI experience.
"""

import difflib
import json
import re
import sqlite3
import unicodedata

try:
    from . import config, db
except ImportError:  # Support running as `python crawler/main.py`
    import config
    import db

# ── UI search weights (match reference project) ─────────────────
W_PHRASE_TITLE    = 50
W_PHRASE_HEADING  = 30
W_PHRASE_BODY     = 15

W_TITLE_TERM      = 10
W_H1_TERM         =  6
W_H2_TERM         =  4
W_H3_TERM         =  2
W_BODY_FREQ       =  1
W_BODY_FREQ_CAP   = 20

W_COVERAGE        =  5
W_FUZZY_TITLE     =  4
W_FUZZY_HEADING   =  2
FUZZY_THRESHOLD   = 0.82

MAX_DEPTH_BONUS   =  3
MIN_TERMS_FOR_MULTIWORD = 2

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _normalise(text: str) -> str:
    """Lowercase + strip diacritics for cross-language matching."""
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode("ascii")


def _tokenise(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(_normalise(text)) if len(t) > 1]


def _fuzzy_match_any(term: str, candidates: list[str]) -> bool:
    for candidate in candidates:
        if difflib.SequenceMatcher(None, term, candidate).ratio() >= FUZZY_THRESHOLD:
            return True
    return False


# ── 1) UI Search ─────────────────────────────────────────────────

def ui_search(
    query: str,
    job_id: int | None = None,
    limit: int | None = None,
) -> list[dict]:
    """
    Rich field-weighted search over indexed pages in SQLite.
    Works during active indexing via read-only WAL connection.
    """
    query = query.strip()
    if not query:
        return []

    terms = _tokenise(query)
    if not terms:
        return []

    min_matched = MIN_TERMS_FOR_MULTIWORD if len(terms) >= 2 else 1

    try:
        conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return []
    conn.row_factory = sqlite3.Row

    pages = db.read_pages_for_ui_search(conn, job_id=job_id)
    conn.close()

    results = []
    for page in pages:
        score, matched_count = _score_page(page, query, terms)
        if matched_count < min_matched:
            continue
        if score > 0:
            results.append({
                "url": page["url"],
                "title": page.get("title"),
                "origin_url": page["origin_url"],
                "depth": page["depth"],
                "score": score,
                "job_id": page.get("job_id"),
            })

    results.sort(key=lambda r: r["score"], reverse=True)

    if limit is not None:
        results = results[:limit]

    return results


def _score_page(page: dict, query: str, terms: list[str]) -> tuple[float, int]:
    """Score a page against query terms using weighted field matching."""
    score = 0.0

    title_lower = _normalise(page.get("title") or "")
    title_words = _tokenise(title_lower)

    # Parse headings JSON
    headings: list[dict] = []
    raw_headings = page.get("headings")
    if raw_headings:
        try:
            headings = json.loads(raw_headings)
        except (json.JSONDecodeError, TypeError):
            headings = []

    body_lower = _normalise(page.get("body_text") or "")

    h1_texts = [_normalise(h["text"]) for h in headings if h.get("level") == 1]
    h2_texts = [_normalise(h["text"]) for h in headings if h.get("level") == 2]
    h3_texts = [_normalise(h["text"]) for h in headings if h.get("level") == 3]
    all_heading_texts = h1_texts + h2_texts + h3_texts

    terms_matched: set[str] = set()

    for term in terms:
        term_matched = False

        if term in title_lower:
            score += W_TITLE_TERM
            term_matched = True

        if any(term in h for h in h1_texts):
            score += W_H1_TERM
            term_matched = True
        if any(term in h for h in h2_texts):
            score += W_H2_TERM
            term_matched = True
        if any(term in h for h in h3_texts):
            score += W_H3_TERM
            term_matched = True

        body_count = body_lower.count(term)
        if body_count > 0:
            score += min(body_count * W_BODY_FREQ, W_BODY_FREQ_CAP)
            term_matched = True

        if not term_matched:
            if _fuzzy_match_any(term, title_words):
                score += W_FUZZY_TITLE
                term_matched = True
            elif _fuzzy_match_any(term, _tokenise(" ".join(all_heading_texts))):
                score += W_FUZZY_HEADING
                term_matched = True

        if term_matched:
            terms_matched.add(term)

    # Phrase matching for multi-word queries
    if len(terms) >= 2:
        query_lower = _normalise(query)
        if query_lower in title_lower:
            score += W_PHRASE_TITLE
        if any(query_lower in h for h in all_heading_texts):
            score += W_PHRASE_HEADING
        if query_lower in body_lower:
            score += W_PHRASE_BODY

    # Coverage bonus
    score += len(terms_matched) * W_COVERAGE

    if not terms_matched:
        return 0.0, 0

    # Depth bonus: shallower = better
    score += max(0, MAX_DEPTH_BONUS - page["depth"])

    return score, len(terms_matched)


# ── 2) Assignment Search ────────────────────────────────────────

def assignment_search(
    query: str,
    job_id: int | None = None,
) -> list[dict]:
    """
    Assignment-compatible search over per-job p_<job_id>.data exports.

    Scoring formula:
        score = (frequency * 10) + 1000 - (depth * 5)

    For multi-word queries, matching token scores are summed per URL.

    Only available for completed jobs that have exported data files.
    If job_id is omitted, falls back to the latest completed job.
    """
    query = query.strip()
    if not query:
        return []

    query_tokens = _tokenise(query)
    if not query_tokens:
        return []

    # Determine which job to search
    if job_id is None:
        try:
            conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            job_id = db.get_latest_completed_job_id(conn)
            conn.close()
        except Exception:
            return []
    if job_id is None:
        return []

    path = db.get_p_data_path(job_id)
    if not path.exists():
        return []

    url_scores: dict[str, dict] = {}

    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue

            parts = line.split("\t")
            if len(parts) != 5:
                continue

            word, url, origin_url, depth_str, freq_str = parts
            try:
                depth = int(depth_str)
                frequency = int(freq_str)
            except ValueError:
                continue

            word_norm = _normalise(word)

            for token in query_tokens:
                if token == word_norm:
                    token_score = (frequency * 10) + 1000 - (depth * 5)

                    if url not in url_scores:
                        url_scores[url] = {
                            "word": word,
                            "url": url,
                            "origin_url": origin_url,
                            "depth": depth,
                            "frequency": frequency,
                            "score": 0,
                        }

                    url_scores[url]["score"] += token_score

                    # Keep highest-frequency word as representative
                    if frequency > url_scores[url]["frequency"]:
                        url_scores[url]["word"] = word
                        url_scores[url]["frequency"] = frequency

    results = list(url_scores.values())
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


# ── Backward-compatible aliases ──────────────────────────────────

def search(
    query: str,
    job_id: int | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Backward-compatible alias for ui_search. Used by CLI."""
    return ui_search(query, job_id=job_id, limit=limit)


def print_results(results: list[dict]) -> None:
    if not results:
        print("No results found.")
        return
    for r in results:
        score = r.get("score", 0)
        score_str = f"{score:.1f}" if isinstance(score, float) else str(score)
        print(f"[{score_str}] depth={r['depth']}  {r['url']}  (origin: {r['origin_url']})")
