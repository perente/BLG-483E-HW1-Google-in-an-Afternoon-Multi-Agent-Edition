"""
server.py - HTTP API for the crawler frontend.
"""

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

try:
    from . import db, orchestrator, search, status
except ImportError:  # Support running as `python crawler/server.py`
    import db
    import orchestrator
    import search
    import status


JOB_ERRORS: dict[int, str] = {}
JOB_THREADS: dict[int, threading.Thread] = {}
JOB_LOCK = threading.Lock()


def _run_job_in_background(job_id: int, max_depth: int) -> None:
    try:
        orchestrator.run_job(job_id, max_depth)
    except Exception as exc:
        with JOB_LOCK:
            JOB_ERRORS[job_id] = str(exc)
        orchestrator.set_job_state(job_id, "error")
    finally:
        with JOB_LOCK:
            JOB_THREADS.pop(job_id, None)


def _thread_is_alive(job_id: int) -> bool:
    with JOB_LOCK:
        thread = JOB_THREADS.get(job_id)
        return thread is not None and thread.is_alive()


def _start_background_job(job_id: int, max_depth: int) -> None:
    thread = threading.Thread(
        target=_run_job_in_background,
        args=(job_id, max_depth),
        daemon=True,
    )
    with JOB_LOCK:
        JOB_THREADS[job_id] = thread
    thread.start()


class CrawlerAPIHandler(BaseHTTPRequestHandler):
    server_version = "CrawlerHTTP/1.0"

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/index":
            self._handle_start_crawl()
            return

        if parsed.path.startswith("/pause/"):
            self._handle_pause(parsed.path)
            return

        if parsed.path.startswith("/resume/"):
            self._handle_resume(parsed.path)
            return

        self._send_json(404, {"error": "not found"})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path.startswith("/index/"):
            self._handle_get_job(parsed.path)
            return
        if parsed.path == "/jobs":
            self._handle_list_jobs()
            return
        if parsed.path == "/search/assignment":
            self._handle_assignment_search(parsed.query)
            return
        if parsed.path == "/search":
            self._handle_search(parsed.query)
            return
        self._send_json(404, {"error": "not found"})

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._add_cors_headers()
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        return

    def _handle_start_crawl(self) -> None:
        try:
            body = self._read_json_body()
            origin = body.get("origin", "")
            max_depth = int(body.get("k"))
            queue_cap = body.get("queue_cap")
            queue_cap = int(queue_cap) if queue_cap is not None else None
            job_id = orchestrator.create_job(origin, max_depth, state="queued", queue_cap=queue_cap)
        except (TypeError, ValueError) as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON body"})
            return
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})
            return

        _start_background_job(job_id, max_depth)

        self._send_json(200, {"job_id": job_id, "status": "queued"})

    def _handle_pause(self, path: str) -> None:
        try:
            job_id = int(path.rsplit("/", 1)[-1])
        except ValueError:
            self._send_json(400, {"error": "invalid job id"})
            return

        if not _thread_is_alive(job_id):
            row = orchestrator.get_job_row(job_id)
            if row is None:
                self._send_json(404, {"error": "job not found"})
                return
            if row["state"] == "paused":
                self._send_json(200, {"job_id": job_id, "status": "paused"})
                return

        if not orchestrator.request_pause(job_id):
            self._send_json(409, {"error": "job is not running or queued"})
            return

        self._send_json(200, {"job_id": job_id, "status": "pausing"})

    def _handle_get_job(self, path: str) -> None:
        try:
            job_id = int(path.rsplit("/", 1)[-1])
        except ValueError:
            self._send_json(400, {"error": "invalid job id"})
            return

        conn = db.get_connection()
        try:
            snapshot = status.get_job_snapshot(conn, job_id)
        finally:
            conn.close()

        if snapshot is None:
            self._send_json(404, {"error": "job not found"})
            return

        with JOB_LOCK:
            error = JOB_ERRORS.get(job_id)
        if error:
            snapshot["error"] = error
            snapshot["status"] = "error"

        self._send_json(200, snapshot)

    def _handle_list_jobs(self) -> None:
        conn = db.get_connection()
        try:
            db.init_schema(conn)
            snapshots = status.get_all_jobs_snapshot(conn)
        finally:
            conn.close()

        with JOB_LOCK:
            for snapshot in snapshots:
                error = JOB_ERRORS.get(snapshot["job_id"])
                if error:
                    snapshot["error"] = error
                    snapshot["status"] = "error"

        self._send_json(200, snapshots)

    def _handle_search(self, query_string: str) -> None:
        params = parse_qs(query_string)
        query = params.get("query", params.get("q", [""]))[0]
        job_id = params.get("job_id", [None])[0]

        try:
            rows = search.ui_search(query, job_id=int(job_id) if job_id else None)
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})
            return

        payload = []
        for row in rows:
            item = {
                "relevant_url": row["url"],
                "origin_url": row["origin_url"],
                "depth": row["depth"],
            }
            if row.get("title"):
                item["title"] = row["title"]
            if row.get("score") is not None:
                item["score"] = row["score"]
            payload.append(item)

        self._send_json(200, payload)

    def _handle_assignment_search(self, query_string: str) -> None:
        params = parse_qs(query_string)
        query = params.get("query", params.get("q", [""]))[0]
        job_id = params.get("job_id", [None])[0]

        try:
            rows = search.assignment_search(query, job_id=int(job_id) if job_id else None)
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})
            return

        self._send_json(200, rows)

    def _handle_resume(self, path: str) -> None:
        try:
            job_id = int(path.rsplit("/", 1)[-1])
        except ValueError:
            self._send_json(400, {"error": "invalid job id"})
            return

        if _thread_is_alive(job_id):
            self._send_json(409, {"error": "job is already running"})
            return

        result = orchestrator.resume_job(job_id)
        if result is None:
            self._send_json(409, {"error": "job is not paused"})
            return

        _, max_depth = result
        _start_background_job(job_id, max_depth)
        self._send_json(200, {"job_id": job_id, "status": "queued"})

    def _read_json_body(self) -> dict:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _add_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, status_code: int, payload) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(body)


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    conn = db.get_connection()
    db.init_schema(conn)
    conn.close()

    httpd = ThreadingHTTPServer((host, port), CrawlerAPIHandler)
    print(f"Crawler API listening on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="HTTP API for the crawler frontend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
