"""
main.py — CLI entrypoint for the crawler.

Commands:
  index <origin_url> <max_depth>   Start a new crawl
  search <query>                   UI search (rich scoring)
  search-assignment <query>        Assignment search (formula-based)
  status                           Current job state
  stats                            Global statistics
  pause <job_id>                   Pause a running crawl
  resume [job_id]                  Resume interrupted crawl
"""

import argparse

try:
    from . import db, orchestrator, search, status
except ImportError:  # Support running as `python crawler/main.py`
    import db
    import orchestrator
    import search
    import status


def main():
    parser = argparse.ArgumentParser(prog="crawler", description="Web Crawler & Search System")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="Start a new crawl")
    p_index.add_argument("origin_url")
    p_index.add_argument("max_depth", type=int)

    p_search = sub.add_parser("search", help="Search indexed pages (UI search)")
    p_search.add_argument("query")
    p_search.add_argument("--job", type=int, default=None, dest="job_id")
    p_search.add_argument("--limit", type=int, default=None)

    p_asearch = sub.add_parser("search-assignment", help="Assignment search (formula-based)")
    p_asearch.add_argument("query")
    p_asearch.add_argument("--job", type=int, default=None, dest="job_id")

    sub.add_parser("status")
    sub.add_parser("stats")

    p_pause = sub.add_parser("pause")
    p_pause.add_argument("job_id", type=int)

    p_resume = sub.add_parser("resume")
    p_resume.add_argument("job_id", type=int, nargs="?", default=None)

    args = parser.parse_args()

    if args.command == "index":
        orchestrator.index_command(args.origin_url, args.max_depth)

    elif args.command == "search":
        results = search.ui_search(args.query, job_id=args.job_id, limit=args.limit)
        search.print_results(results)

    elif args.command == "search-assignment":
        results = search.assignment_search(args.query, job_id=args.job_id)
        if not results:
            print("No results found.")
        else:
            for r in results:
                print(f"[score={r['score']}] freq={r['frequency']} depth={r['depth']}  {r['url']}  (origin: {r['origin_url']})")

    elif args.command == "status":
        conn = db.get_connection()
        try:
            status.print_status(conn)
        finally:
            conn.close()

    elif args.command == "stats":
        conn = db.get_connection()
        try:
            status.print_stats(conn)
        finally:
            conn.close()

    elif args.command == "resume":
        orchestrator.resume_command(job_id=args.job_id)

    elif args.command == "pause":
        orchestrator.pause_command(args.job_id)


if __name__ == "__main__":
    main()
