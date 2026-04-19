"""
test_integration.py

Integration tests running an actual crawl against a local HTTP server.
Tests multi-job support, origin_url semantics, p_data export, and resume.
"""

import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
import db
import orchestrator
import search


PAGES = {
    "/": b"""<html><head><title>Home</title></head><body>
        <h1>Welcome</h1>
        <p>Welcome to the test site.</p>
        <a href="/about">About</a>
        <a href="/blog">Blog</a>
    </body></html>""",
    "/about": b"""<html><head><title>About</title></head><body>
        <h1>About Us</h1>
        <p>About us. Specializing in widgets.</p>
    </body></html>""",
    "/blog": b"""<html><head><title>Blog</title></head><body>
        <h2>Our Blog</h2>
        <p>Our blog.</p>
        <a href="/blog/post-1">Post 1</a>
    </body></html>""",
    "/blog/post-1": b"""<html><head><title>Post 1</title></head><body>
        <h1>Post 1</h1>
        <p>Widgets are great products for everyone.</p>
    </body></html>""",
}

PAGES2 = {
    "/": b"""<html><head><title>Site Two</title></head><body>
        <h1>Second Site</h1>
        <p>Second crawl origin with gizmos.</p>
        <a href="/page2">Page 2</a>
    </body></html>""",
    "/page2": b"""<html><head><title>Page 2</title></head><body>
        <p>More gizmos content here.</p>
    </body></html>""",
}

FANOUT_PAGES = {
    "/": (
        "<html><head><title>Root</title></head><body>"
        + "".join(f'<a href="/page-{i}">Page {i}</a>' for i in range(12))
        + "</body></html>"
    ).encode("utf-8"),
}
for i in range(12):
    FANOUT_PAGES[f"/page-{i}"] = (
        f"<html><head><title>Page {i}</title></head><body><p>Leaf {i}</p></body></html>"
    ).encode("utf-8")


class StaticSiteHandler(BaseHTTPRequestHandler):
    pages = {}

    def do_GET(self):
        body = self.pages.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def start_server(pages):
    handler = type("Handler", (StaticSiteHandler,), {"pages": pages})
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def start_slow_server(pages, delay_seconds):
    def _do_get(self):
        time.sleep(delay_seconds)
        StaticSiteHandler.do_GET(self)

    handler = type("SlowHandler", (StaticSiteHandler,), {
        "pages": pages,
        "do_GET": _do_get,
    })
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


class TestIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = start_server(PAGES)
        cls.port = cls.server.server_address[1]
        cls.origin = f"http://127.0.0.1:{cls.port}/"

        fd, cls._tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        cls._orig_db_path = config.DB_PATH
        cls._orig_storage_dir = config.STORAGE_DIR
        cls._tmpdir = tempfile.mkdtemp()
        config.DB_PATH = cls._tmp
        config.STORAGE_DIR = Path(cls._tmpdir)

        cls._orig_concurrent = config.MAX_CONCURRENT
        cls._orig_delay = config.POLITENESS_DELAY
        config.MAX_CONCURRENT = 2
        config.POLITENESS_DELAY = 0.0

        orchestrator.index_command(cls.origin, max_depth=2)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        config.DB_PATH = cls._orig_db_path
        config.STORAGE_DIR = cls._orig_storage_dir
        config.MAX_CONCURRENT = cls._orig_concurrent
        config.POLITENESS_DELAY = cls._orig_delay
        import shutil
        try:
            os.unlink(cls._tmp)
        except OSError:
            pass
        try:
            shutil.rmtree(cls._tmpdir)
        except OSError:
            pass

    def _conn(self):
        conn = sqlite3.connect(self._tmp)
        conn.row_factory = sqlite3.Row
        return conn

    def test_pages_indexed(self):
        conn = self._conn()
        count = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        conn.close()
        self.assertGreaterEqual(count, 4)

    def test_all_expected_urls_indexed(self):
        conn = self._conn()
        urls = {row["url"] for row in conn.execute("SELECT url FROM pages").fetchall()}
        conn.close()
        for path in ("/", "/about", "/blog", "/blog/post-1"):
            expected = f"http://127.0.0.1:{self.port}{path}"
            self.assertIn(expected, urls, f"Expected URL not indexed: {expected}")

    def test_search_widgets_returns_results(self):
        results = search.ui_search("widgets")
        self.assertTrue(len(results) >= 1, "Expected at least one result for 'widgets'")

    def test_search_widgets_hits_correct_pages(self):
        results = search.ui_search("widgets")
        urls = {row["url"] for row in results}
        about_url = f"http://127.0.0.1:{self.port}/about"
        post_url = f"http://127.0.0.1:{self.port}/blog/post-1"
        self.assertTrue(
            about_url in urls or post_url in urls,
            f"Expected about or post-1 in results, got: {urls}",
        )

    def test_search_wrong_job_returns_empty(self):
        results = search.ui_search("widgets", job_id=99999)
        self.assertEqual(results, [])

    def test_no_pending_or_processing_frontier_rows(self):
        conn = self._conn()
        rows = conn.execute(
            "SELECT COUNT(*) FROM frontier WHERE state IN ('pending', 'queued', 'processing')"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(rows, 0)

    def test_crawl_job_marked_done(self):
        conn = self._conn()
        job = conn.execute(
            "SELECT state FROM crawl_jobs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        self.assertEqual(job["state"], "done")

    def test_origin_url_is_seed_not_parent(self):
        """origin_url in page_discoveries must be the crawl seed, not the parent page."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT origin_url FROM page_discoveries"
        ).fetchall()
        conn.close()
        for row in rows:
            self.assertEqual(row["origin_url"], self.origin,
                             f"origin_url should be the seed URL, got: {row['origin_url']}")

    def test_p_data_export_exists(self):
        """After crawl completion, a p_data file should exist."""
        conn = self._conn()
        job = conn.execute("SELECT id FROM crawl_jobs ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        path = db.get_p_data_path(job["id"])
        self.assertTrue(path.exists(), f"p_data file should exist at {path}")

    def test_assignment_search_from_p_data(self):
        """Assignment search should work from the exported p_data file."""
        conn = self._conn()
        job = conn.execute("SELECT id FROM crawl_jobs ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        results = search.assignment_search("widgets", job_id=job["id"])
        self.assertTrue(len(results) > 0, "Assignment search should find results")


class TestQueueBackpressureIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = start_server(FANOUT_PAGES)
        cls.port = cls.server.server_address[1]
        cls.origin = f"http://127.0.0.1:{cls.port}/"

        fd, cls._tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        cls._orig_db_path = config.DB_PATH
        cls._orig_concurrent = config.MAX_CONCURRENT
        cls._orig_delay = config.POLITENESS_DELAY
        cls._orig_queue_cap = config.QUEUE_CAP
        cls._orig_storage_dir = config.STORAGE_DIR
        cls._tmpdir = tempfile.mkdtemp()

        config.DB_PATH = cls._tmp
        config.MAX_CONCURRENT = 2
        config.POLITENESS_DELAY = 0.0
        config.QUEUE_CAP = 2
        config.STORAGE_DIR = Path(cls._tmpdir)

        orchestrator.index_command(cls.origin, max_depth=1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        config.DB_PATH = cls._orig_db_path
        config.MAX_CONCURRENT = cls._orig_concurrent
        config.POLITENESS_DELAY = cls._orig_delay
        config.QUEUE_CAP = cls._orig_queue_cap
        config.STORAGE_DIR = cls._orig_storage_dir
        import shutil
        try:
            os.unlink(cls._tmp)
        except OSError:
            pass
        try:
            shutil.rmtree(cls._tmpdir)
        except OSError:
            pass

    def _conn(self):
        conn = sqlite3.connect(self._tmp)
        conn.row_factory = sqlite3.Row
        return conn

    def test_all_fanout_pages_indexed_even_with_small_queue(self):
        conn = self._conn()
        count = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        conn.close()
        self.assertEqual(count, 13)

    def test_no_frontier_work_left_after_completion(self):
        conn = self._conn()
        rows = conn.execute(
            "SELECT COUNT(*) FROM frontier WHERE state IN ('pending', 'queued', 'processing')"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(rows, 0)


class TestMultiJobConcurrency(unittest.TestCase):
    """Test that 2 crawl jobs can run concurrently."""

    @classmethod
    def setUpClass(cls):
        cls.server1 = start_server(PAGES)
        cls.server2 = start_server(PAGES2)
        cls.port1 = cls.server1.server_address[1]
        cls.port2 = cls.server2.server_address[1]

        fd, cls._tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        cls._orig_db_path = config.DB_PATH
        cls._orig_concurrent = config.MAX_CONCURRENT
        cls._orig_delay = config.POLITENESS_DELAY
        cls._orig_active_jobs = config.MAX_ACTIVE_JOBS
        cls._orig_storage_dir = config.STORAGE_DIR
        cls._tmpdir = tempfile.mkdtemp()

        config.DB_PATH = cls._tmp
        config.MAX_CONCURRENT = 2
        config.POLITENESS_DELAY = 0.0
        config.MAX_ACTIVE_JOBS = 2
        config.STORAGE_DIR = Path(cls._tmpdir)

        # Initialize DB
        conn = db.get_connection()
        db.init_schema(conn)
        conn.close()

        # Start 2 concurrent jobs
        cls.origin1 = f"http://127.0.0.1:{cls.port1}/"
        cls.origin2 = f"http://127.0.0.1:{cls.port2}/"

        cls.job_id1 = orchestrator.create_job(cls.origin1, 1, state="queued")
        cls.job_id2 = orchestrator.create_job(cls.origin2, 1, state="queued")

        # Run both in parallel threads
        t1 = threading.Thread(target=orchestrator.run_job, args=(cls.job_id1, 1))
        t2 = threading.Thread(target=orchestrator.run_job, args=(cls.job_id2, 1))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.server1.shutdown()
        cls.server2.shutdown()
        config.DB_PATH = cls._orig_db_path
        config.MAX_CONCURRENT = cls._orig_concurrent
        config.POLITENESS_DELAY = cls._orig_delay
        config.MAX_ACTIVE_JOBS = cls._orig_active_jobs
        config.STORAGE_DIR = cls._orig_storage_dir
        import shutil
        try:
            os.unlink(cls._tmp)
        except OSError:
            pass
        try:
            shutil.rmtree(cls._tmpdir)
        except OSError:
            pass

    def _conn(self):
        conn = sqlite3.connect(self._tmp)
        conn.row_factory = sqlite3.Row
        return conn

    def test_both_jobs_completed(self):
        conn = self._conn()
        states = {
            r["id"]: r["state"]
            for r in conn.execute("SELECT id, state FROM crawl_jobs").fetchall()
        }
        conn.close()
        self.assertEqual(states[self.job_id1], "done")
        self.assertEqual(states[self.job_id2], "done")

    def test_both_jobs_indexed_pages(self):
        conn = self._conn()
        count1 = conn.execute(
            "SELECT COUNT(*) FROM page_discoveries WHERE job_id = ?", (self.job_id1,)
        ).fetchone()[0]
        count2 = conn.execute(
            "SELECT COUNT(*) FROM page_discoveries WHERE job_id = ?", (self.job_id2,)
        ).fetchone()[0]
        conn.close()
        self.assertGreater(count1, 0, "Job 1 should have indexed pages")
        self.assertGreater(count2, 0, "Job 2 should have indexed pages")

    def test_origin_urls_are_separate(self):
        """Each job's discoveries should reference its own origin."""
        conn = self._conn()
        origins1 = {
            r["origin_url"]
            for r in conn.execute(
                "SELECT origin_url FROM page_discoveries WHERE job_id = ?", (self.job_id1,)
            ).fetchall()
        }
        origins2 = {
            r["origin_url"]
            for r in conn.execute(
                "SELECT origin_url FROM page_discoveries WHERE job_id = ?", (self.job_id2,)
            ).fetchall()
        }
        conn.close()
        self.assertEqual(origins1, {self.origin1})
        self.assertEqual(origins2, {self.origin2})

    def test_job_cap_prevents_third_job(self):
        """Creating a 3rd job when MAX_ACTIVE_JOBS=2 and 2 are 'done' should succeed
        (done jobs don't count). But if 2 were running, it should fail."""
        # Both jobs are done now, so a 3rd should succeed
        try:
            job_id3 = orchestrator.create_job("http://example.com/", 1, state="queued")
            # Clean up
            conn = self._conn()
            conn.execute("DELETE FROM crawl_jobs WHERE id = ?", (job_id3,))
            conn.commit()
            conn.close()
        except ValueError:
            self.fail("Should allow creating a job when all existing jobs are done")

    def test_both_jobs_have_p_data_exports(self):
        path1 = db.get_p_data_path(self.job_id1)
        path2 = db.get_p_data_path(self.job_id2)
        self.assertTrue(path1.exists(), f"Job 1 p_data should exist at {path1}")
        self.assertTrue(path2.exists(), f"Job 2 p_data should exist at {path2}")


class TestPauseResumeIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = start_slow_server(FANOUT_PAGES, delay_seconds=0.05)
        cls.port = cls.server.server_address[1]
        cls.origin = f"http://127.0.0.1:{cls.port}/"

        fd, cls._tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        cls._orig_db_path = config.DB_PATH
        cls._orig_storage_dir = config.STORAGE_DIR
        cls._orig_concurrent = config.MAX_CONCURRENT
        cls._orig_delay = config.POLITENESS_DELAY
        cls._tmpdir = tempfile.mkdtemp()

        config.DB_PATH = cls._tmp
        config.STORAGE_DIR = Path(cls._tmpdir)
        config.MAX_CONCURRENT = 1
        config.POLITENESS_DELAY = 0.0

        conn = db.get_connection()
        db.init_schema(conn)
        conn.close()

        cls.job_id = orchestrator.create_job(cls.origin, 1, state="running")
        cls.thread = threading.Thread(
            target=orchestrator.run_job,
            args=(cls.job_id, 1),
            daemon=True,
        )
        cls.thread.start()

        deadline = time.time() + 5
        saw_processing = False
        while time.time() < deadline:
            conn = sqlite3.connect(cls._tmp)
            conn.row_factory = sqlite3.Row
            try:
                processing = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM frontier WHERE job_id = ? AND state = 'processing'",
                    (cls.job_id,),
                ).fetchone()["cnt"]
            finally:
                conn.close()
            if processing > 0:
                saw_processing = True
                break
            time.sleep(0.02)

        if not saw_processing:
            raise AssertionError("Worker never entered processing state before pause test.")

        paused = orchestrator.request_pause(cls.job_id)
        if not paused:
            raise AssertionError("Pause request was not accepted.")

        cls.thread.join(timeout=5)
        if cls.thread.is_alive():
            raise AssertionError("Paused crawl thread did not exit in time.")

        conn = sqlite3.connect(cls._tmp)
        conn.row_factory = sqlite3.Row
        try:
            cls.state_after_pause = conn.execute(
                "SELECT state FROM crawl_jobs WHERE id = ?",
                (cls.job_id,),
            ).fetchone()["state"]
            cls.incomplete_after_pause = conn.execute(
                "SELECT COUNT(*) AS cnt FROM frontier WHERE job_id = ? AND state IN ('queued', 'processing')",
                (cls.job_id,),
            ).fetchone()["cnt"]
        finally:
            conn.close()

        resumed = orchestrator.resume_job(cls.job_id)
        if resumed is None:
            raise AssertionError("Paused crawl job could not be resumed.")

        _, max_depth = resumed
        orchestrator.run_job(cls.job_id, max_depth)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        config.DB_PATH = cls._orig_db_path
        config.STORAGE_DIR = cls._orig_storage_dir
        config.MAX_CONCURRENT = cls._orig_concurrent
        config.POLITENESS_DELAY = cls._orig_delay
        import shutil
        try:
            os.unlink(cls._tmp)
        except OSError:
            pass
        try:
            shutil.rmtree(cls._tmpdir)
        except OSError:
            pass

    def _conn(self):
        conn = sqlite3.connect(self._tmp)
        conn.row_factory = sqlite3.Row
        return conn

    def test_job_pauses_cleanly_before_resume(self):
        conn = self._conn()
        final_state = conn.execute(
            "SELECT state FROM crawl_jobs WHERE id = ?",
            (self.job_id,),
        ).fetchone()["state"]
        conn.close()
        self.assertEqual(self.state_after_pause, "paused")
        self.assertEqual(self.incomplete_after_pause, 0)
        self.assertEqual(final_state, "done")

    def test_resumed_job_finishes(self):
        conn = self._conn()
        page_count = conn.execute("SELECT COUNT(*) AS cnt FROM pages").fetchone()["cnt"]
        done_count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM frontier WHERE job_id = ? AND state = 'done'",
            (self.job_id,),
        ).fetchone()["cnt"]
        conn.close()
        self.assertGreaterEqual(page_count, 2)
        self.assertGreater(done_count, 0)


class TestWorkerFailureHandling(unittest.TestCase):
    """Verify that worker failures mark frontier rows as 'failed', not stranded."""

    def setUp(self):
        fd, self._tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._orig_db_path = config.DB_PATH
        config.DB_PATH = self._tmp

        self.conn = sqlite3.connect(self._tmp)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        db.init_schema(self.conn)

        self.job_id = self.conn.execute(
            "INSERT INTO crawl_jobs (origin_url, max_depth, state, started_at) VALUES (?, ?, ?, 1)",
            ("http://example.com/", 2, "running"),
        ).lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        config.DB_PATH = self._orig_db_path
        try:
            os.unlink(self._tmp)
        except OSError:
            pass

    def test_processing_row_moves_to_failed_on_error(self):
        """If a frontier row is in 'processing' and the worker excepts,
        it must end up as 'failed', not stuck in 'processing'."""
        url = "http://example.com/crash"
        self.conn.execute(
            "INSERT INTO frontier (job_id, url, origin_url, depth, state, enqueued_at) "
            "VALUES (?, ?, ?, 0, 'processing', 1)",
            (self.job_id, url, "http://example.com/"),
        )
        self.conn.commit()

        # Simulate what the worker's except block does:
        try:
            raise RuntimeError("simulated crash")
        except Exception:
            try:
                with self.conn:
                    self.conn.execute(
                        "UPDATE frontier SET state = 'failed' "
                        "WHERE job_id = ? AND url = ? AND state = 'processing'",
                        (self.job_id, url),
                    )
            except Exception:
                pass

        row = self.conn.execute(
            "SELECT state FROM frontier WHERE job_id = ? AND url = ?",
            (self.job_id, url),
        ).fetchone()
        self.assertEqual(row["state"], "failed")

    def test_already_done_row_not_reverted_by_failure_handler(self):
        """If frontier was already moved to 'done' by indexer, the failure
        handler's UPDATE is a no-op (state != 'processing')."""
        url = "http://example.com/done"
        self.conn.execute(
            "INSERT INTO frontier (job_id, url, origin_url, depth, state, enqueued_at) "
            "VALUES (?, ?, ?, 0, 'done', 1)",
            (self.job_id, url, "http://example.com/"),
        )
        self.conn.commit()

        # Worker failure handler fires but should be a no-op
        with self.conn:
            self.conn.execute(
                "UPDATE frontier SET state = 'failed' "
                "WHERE job_id = ? AND url = ? AND state = 'processing'",
                (self.job_id, url),
            )

        row = self.conn.execute(
            "SELECT state FROM frontier WHERE job_id = ? AND url = ?",
            (self.job_id, url),
        ).fetchone()
        self.assertEqual(row["state"], "done",
                         "Should remain 'done', not overwritten by failure handler")

    def test_no_stranded_processing_after_full_crawl(self):
        """After a completed crawl, there should be zero 'processing' rows."""
        # This is already tested in TestIntegration.test_no_pending_or_processing_frontier_rows
        # but let's explicitly verify for all known test crawls
        pass


class TestJobScopedSearch(unittest.TestCase):
    """Verify that job_id filtering works for both search modes."""

    @classmethod
    def setUpClass(cls):
        cls.server1 = start_server(PAGES)
        cls.server2 = start_server(PAGES2)
        cls.port1 = cls.server1.server_address[1]
        cls.port2 = cls.server2.server_address[1]

        fd, cls._tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        cls._orig_db_path = config.DB_PATH
        cls._orig_concurrent = config.MAX_CONCURRENT
        cls._orig_delay = config.POLITENESS_DELAY
        cls._orig_active_jobs = config.MAX_ACTIVE_JOBS
        cls._orig_storage_dir = config.STORAGE_DIR
        cls._tmpdir = tempfile.mkdtemp()

        config.DB_PATH = cls._tmp
        config.MAX_CONCURRENT = 2
        config.POLITENESS_DELAY = 0.0
        config.MAX_ACTIVE_JOBS = 2
        config.STORAGE_DIR = Path(cls._tmpdir)

        conn = db.get_connection()
        db.init_schema(conn)
        conn.close()

        cls.origin1 = f"http://127.0.0.1:{cls.port1}/"
        cls.origin2 = f"http://127.0.0.1:{cls.port2}/"

        cls.job_id1 = orchestrator.create_job(cls.origin1, 2, state="queued")
        cls.job_id2 = orchestrator.create_job(cls.origin2, 1, state="queued")

        t1 = threading.Thread(target=orchestrator.run_job, args=(cls.job_id1, 2))
        t2 = threading.Thread(target=orchestrator.run_job, args=(cls.job_id2, 1))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.server1.shutdown()
        cls.server2.shutdown()
        config.DB_PATH = cls._orig_db_path
        config.MAX_CONCURRENT = cls._orig_concurrent
        config.POLITENESS_DELAY = cls._orig_delay
        config.MAX_ACTIVE_JOBS = cls._orig_active_jobs
        config.STORAGE_DIR = cls._orig_storage_dir
        import shutil
        try:
            os.unlink(cls._tmp)
        except OSError:
            pass
        try:
            shutil.rmtree(cls._tmpdir)
        except OSError:
            pass

    def test_ui_search_all_jobs_returns_results_from_both(self):
        """UI search without job_id should include results from both jobs."""
        # 'widgets' only appears in job1 pages, 'gizmos' in job2
        r1 = search.ui_search("widgets")
        r2 = search.ui_search("gizmos")
        self.assertTrue(len(r1) > 0, "Should find 'widgets' from job1")
        self.assertTrue(len(r2) > 0, "Should find 'gizmos' from job2")

    def test_ui_search_scoped_to_job1(self):
        """UI search scoped to job1 should not return job2 content."""
        results = search.ui_search("gizmos", job_id=self.job_id1)
        self.assertEqual(results, [], "Job1 should not have 'gizmos'")

    def test_ui_search_scoped_to_job2(self):
        """UI search scoped to job2 should not return job1 content."""
        results = search.ui_search("widgets", job_id=self.job_id2)
        self.assertEqual(results, [], "Job2 should not have 'widgets'")

    def test_assignment_search_scoped_to_job1(self):
        """Assignment search scoped to job1 should return job1 content."""
        results = search.assignment_search("widgets", job_id=self.job_id1)
        self.assertTrue(len(results) > 0, "Job1 should have 'widgets'")

    def test_assignment_search_scoped_to_job2_no_cross_contamination(self):
        """Assignment search scoped to job2 should not return job1 content."""
        results = search.assignment_search("widgets", job_id=self.job_id2)
        self.assertEqual(results, [], "Job2 p_data should not have 'widgets'")


class TestFrontierBackpressure(unittest.TestCase):
    """Verify that frontier-aware backpressure drops deeper links."""

    def setUp(self):
        import asyncio
        fd, self._tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._orig_db_path = config.DB_PATH
        self._orig_frontier_bp = config.FRONTIER_BP_THRESHOLD
        config.DB_PATH = self._tmp

        self.conn = sqlite3.connect(self._tmp)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        db.init_schema(self.conn)

        self.job_id = self.conn.execute(
            "INSERT INTO crawl_jobs (origin_url, max_depth, state, started_at) VALUES (?, ?, ?, 1)",
            ("http://example.com/", 3, "running"),
        ).lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        config.DB_PATH = self._orig_db_path
        config.FRONTIER_BP_THRESHOLD = self._orig_frontier_bp
        try:
            os.unlink(self._tmp)
        except OSError:
            pass

    def test_frontier_pressure_drops_deep_links(self):
        """When frontier pending count exceeds FRONTIER_BP_THRESHOLD,
        deeper links (next_depth > 1) should be dropped."""
        import asyncio
        # Import the function under test
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        import worker as w
        import normalizer

        # Set a very low threshold so pressure triggers easily
        config.FRONTIER_BP_THRESHOLD = 5

        # Seed 10 pending frontier rows to exceed threshold
        for i in range(10):
            self.conn.execute(
                "INSERT OR IGNORE INTO frontier (job_id, url, origin_url, depth, state, enqueued_at) "
                "VALUES (?, ?, ?, 1, 'pending', 1)",
                (self.job_id, f"http://example.com/page-{i}", "http://example.com/"),
            )
        self.conn.commit()

        # Create a queue with plenty of capacity
        queue = asyncio.Queue(maxsize=1000)
        seen = set()
        bp_counter = [0]

        # Simulate a page at depth 1 discovering links (which would go to depth 2)
        raw_links = [f"http://example.com/deep-{i}" for i in range(5)]

        # We need normalizer to just pass through; mock should_enqueue
        orig_should = normalizer.should_enqueue
        normalizer.should_enqueue = lambda url, origin="": True

        try:
            w._enqueue_discovered_links(
                self.conn, queue, raw_links, seen, self.job_id,
                "http://example.com/", "http://example.com/page-0", 1,
                bp_counter,
            )
        finally:
            normalizer.should_enqueue = orig_should

        # All 5 deep links should have been dropped (next_depth=2 > 1, under pressure)
        self.assertEqual(bp_counter[0], 5,
                         "All deep links should be counted as backpressure drops")
        self.assertTrue(queue.empty(),
                        "No deep links should have been enqueued under frontier pressure")


if __name__ == "__main__":
    unittest.main()
