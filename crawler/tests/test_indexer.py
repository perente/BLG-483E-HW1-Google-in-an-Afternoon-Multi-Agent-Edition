import sys
import os
import sqlite3
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import indexer


def make_conn():
    """Return an in-memory SQLite connection with schema initialized."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    db.init_schema(conn)
    return conn


def seed_job(conn, origin="http://example.com/", max_depth=2):
    cursor = conn.execute(
        "INSERT INTO crawl_jobs (origin_url, max_depth, state, started_at) VALUES (?, ?, 'running', 1)",
        (origin, max_depth),
    )
    conn.commit()
    return cursor.lastrowid


def seed_frontier(conn, job_id, url, origin_url, depth=0):
    conn.execute(
        "INSERT OR IGNORE INTO frontier (job_id, url, origin_url, depth, state, enqueued_at) VALUES (?, ?, ?, ?, 'pending', 1)",
        (job_id, url, origin_url, depth),
    )
    conn.commit()


class TestWritePage(unittest.TestCase):

    def setUp(self):
        self.conn = make_conn()
        self.job_id = seed_job(self.conn)
        seed_frontier(self.conn, self.job_id, "http://example.com/a", "http://example.com/")

    def tearDown(self):
        self.conn.close()

    def test_inserts_page_row(self):
        indexer.write_page(
            self.conn, "http://example.com/a", "Title A", "hello world",
            200, self.job_id, "http://example.com/", 0,
        )
        row = self.conn.execute("SELECT * FROM pages WHERE url = ?", ("http://example.com/a",)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["title"], "Title A")
        self.assertEqual(row["status"], 200)

    def test_inserts_page_discoveries_row(self):
        indexer.write_page(
            self.conn, "http://example.com/a", "T", "body",
            200, self.job_id, "http://example.com/", 0,
        )
        row = self.conn.execute("SELECT * FROM page_discoveries").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["job_id"], self.job_id)
        self.assertEqual(row["origin_url"], "http://example.com/")
        self.assertEqual(row["depth"], 0)

    def test_fts_is_searchable(self):
        indexer.write_page(
            self.conn, "http://example.com/a", "T", "uniqueword123",
            200, self.job_id, "http://example.com/", 0,
        )
        rows = self.conn.execute(
            "SELECT rowid FROM pages_fts WHERE pages_fts MATCH 'uniqueword123'"
        ).fetchall()
        self.assertEqual(len(rows), 1)

    def test_duplicate_write_does_not_raise(self):
        seed_frontier(self.conn, self.job_id, "http://example.com/a", "http://example.com/", 0)
        indexer.write_page(
            self.conn, "http://example.com/a", "T1", "first body",
            200, self.job_id, "http://example.com/", 0,
        )
        try:
            indexer.write_page(
                self.conn, "http://example.com/a", "T2", "second body",
                200, self.job_id, "http://example.com/", 0,
            )
        except Exception as e:
            self.fail(f"Second write_page raised: {e}")

    def test_duplicate_write_keeps_one_page_row(self):
        seed_frontier(self.conn, self.job_id, "http://example.com/a", "http://example.com/", 0)
        indexer.write_page(
            self.conn, "http://example.com/a", "T1", "body",
            200, self.job_id, "http://example.com/", 0,
        )
        indexer.write_page(
            self.conn, "http://example.com/a", "T2", "body updated",
            200, self.job_id, "http://example.com/", 0,
        )
        count = self.conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        self.assertEqual(count, 1)

    def test_marks_frontier_done(self):
        indexer.write_page(
            self.conn, "http://example.com/a", "T", "body",
            200, self.job_id, "http://example.com/", 0,
        )
        row = self.conn.execute(
            "SELECT state FROM frontier WHERE job_id = ? AND url = ?",
            (self.job_id, "http://example.com/a"),
        ).fetchone()
        self.assertEqual(row["state"], "done")

    def test_stores_headings(self):
        headings = [{"level": 1, "text": "Main"}, {"level": 2, "text": "Sub"}]
        indexer.write_page(
            self.conn, "http://example.com/a", "T", "body",
            200, self.job_id, "http://example.com/", 0,
            headings=headings,
        )
        import json
        row = self.conn.execute("SELECT headings FROM pages WHERE url = ?", ("http://example.com/a",)).fetchone()
        stored = json.loads(row["headings"])
        self.assertEqual(len(stored), 2)
        self.assertEqual(stored[0]["level"], 1)
        self.assertEqual(stored[0]["text"], "Main")

    def test_origin_url_is_job_origin_not_parent(self):
        """Verify that origin_url in page_discoveries is the job origin, not the parent page."""
        job_origin = "http://example.com/"
        parent_url = "http://example.com/parent"

        seed_frontier(self.conn, self.job_id, parent_url, job_origin, 0)
        indexer.write_page(
            self.conn, parent_url, "Parent", "parent body",
            200, self.job_id, job_origin, 0,
        )

        row = self.conn.execute(
            "SELECT origin_url FROM page_discoveries WHERE job_id = ?",
            (self.job_id,),
        ).fetchone()
        self.assertEqual(row["origin_url"], job_origin)


if __name__ == "__main__":
    unittest.main()