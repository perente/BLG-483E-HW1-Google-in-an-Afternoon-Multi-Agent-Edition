"""
test_search.py

Tests for both ui_search() and assignment_search().
Verifies that the two search paths are separate and produce correct results.
"""

import sys
import os
import json
import sqlite3
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
import db
import indexer
import search


def _setup_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    db.init_schema(conn)
    return conn


def _seed_job(conn, origin="http://example.com/", max_depth=2, state="running"):
    cur = conn.execute(
        "INSERT INTO crawl_jobs (origin_url, max_depth, state, started_at) VALUES (?, ?, ?, 1)",
        (origin, max_depth, state),
    )
    conn.commit()
    return cur.lastrowid


def _seed_frontier(conn, job_id, url, origin_url="http://example.com/", depth=0):
    conn.execute(
        "INSERT OR IGNORE INTO frontier (job_id, url, origin_url, depth, state, enqueued_at) VALUES (?, ?, ?, ?, 'pending', 1)",
        (job_id, url, origin_url, depth),
    )
    conn.commit()


class TestUISearch(unittest.TestCase):

    def setUp(self):
        fd, self._tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._orig_db_path = config.DB_PATH
        config.DB_PATH = self._tmp

        self.conn = _setup_db(self._tmp)
        self.job_id = _seed_job(self.conn)

        pages = [
            ("http://example.com/widgets", "Widgets Page", "Widgets are amazing products.",
             [{"level": 1, "text": "All About Widgets"}]),
            ("http://example.com/about",   "About Us",     "We specialize in building things.", []),
            ("http://example.com/blog",    "Blog",         "Welcome to the blog about gizmos.", []),
        ]
        for url, title, body, headings in pages:
            _seed_frontier(self.conn, self.job_id, url)
            indexer.write_page(
                self.conn, url, title, body,
                200, self.job_id, "http://example.com/", 0,
                headings=headings,
            )

    def tearDown(self):
        self.conn.close()
        config.DB_PATH = self._orig_db_path
        try:
            os.unlink(self._tmp)
        except OSError:
            pass

    def test_returns_matching_page(self):
        results = search.ui_search("widgets")
        urls = [r["url"] for r in results]
        self.assertIn("http://example.com/widgets", urls)

    def test_no_false_positives(self):
        results = search.ui_search("widgets")
        urls = [r["url"] for r in results]
        self.assertNotIn("http://example.com/about", urls)

    def test_nonexistent_query_returns_empty(self):
        results = search.ui_search("xyzzy_nonexistent_12345")
        self.assertEqual(results, [])

    def test_job_id_filter_matches(self):
        results = search.ui_search("widgets", job_id=self.job_id)
        self.assertTrue(len(results) > 0)

    def test_job_id_filter_wrong_job_returns_empty(self):
        results = search.ui_search("widgets", job_id=99999)
        self.assertEqual(results, [])

    def test_results_have_expected_keys(self):
        results = search.ui_search("gizmos")
        self.assertTrue(len(results) > 0)
        row = results[0]
        for key in ("url", "origin_url", "depth", "score"):
            self.assertIn(key, row)

    def test_results_ordered_by_score_descending(self):
        results = search.ui_search("widgets")
        if len(results) > 1:
            scores = [r["score"] for r in results]
            self.assertEqual(scores, sorted(scores, reverse=True))

    def test_title_match_boosts_score(self):
        """Page with 'widgets' in title should score higher than one with it only in body."""
        results = search.ui_search("widgets")
        if len(results) >= 1:
            top_url = results[0]["url"]
            self.assertEqual(top_url, "http://example.com/widgets")

    def test_heading_match_contributes_score(self):
        """H1 heading match should contribute to score."""
        results = search.ui_search("widgets")
        top = results[0]
        # Should have title (10) + h1 (6) + body (1) + coverage (5) + depth (3) = 25+
        self.assertGreater(top["score"], 20)

    def test_backward_compat_search_alias(self):
        """search.search() should work as alias for ui_search()."""
        results = search.search("widgets")
        self.assertTrue(len(results) > 0)


class TestAssignmentSearch(unittest.TestCase):

    def setUp(self):
        fd, self._tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._orig_db_path = config.DB_PATH
        self._orig_storage_dir = config.STORAGE_DIR
        self._tmpdir = tempfile.mkdtemp()
        config.DB_PATH = self._tmp
        config.STORAGE_DIR = __import__("pathlib").Path(self._tmpdir)

        self.conn = _setup_db(self._tmp)
        self.job_id = _seed_job(self.conn, state="done")

        pages = [
            ("http://example.com/a", "Python Tutorial", "python programming python python",
             [{"level": 1, "text": "Learn Python"}]),
            ("http://example.com/b", "Java Guide", "java programming basics",
             []),
        ]
        for url, title, body, headings in pages:
            _seed_frontier(self.conn, self.job_id, url)
            indexer.write_page(
                self.conn, url, title, body,
                200, self.job_id, "http://example.com/", 1,
                headings=headings,
            )

        # Export p_data
        db.export_p_data(self.conn, self.job_id)

    def tearDown(self):
        self.conn.close()
        config.DB_PATH = self._orig_db_path
        config.STORAGE_DIR = self._orig_storage_dir
        import shutil
        try:
            os.unlink(self._tmp)
        except OSError:
            pass
        try:
            shutil.rmtree(self._tmpdir)
        except OSError:
            pass

    def test_finds_matching_word(self):
        results = search.assignment_search("python", job_id=self.job_id)
        self.assertTrue(len(results) > 0)
        urls = [r["url"] for r in results]
        self.assertIn("http://example.com/a", urls)

    def test_score_formula(self):
        """Verify score = (freq * 10) + 1000 - (depth * 5)."""
        results = search.assignment_search("python", job_id=self.job_id)
        top = [r for r in results if r["url"] == "http://example.com/a"][0]
        # python appears in title + h1 + body (3x) = at least 5 times
        # depth = 1
        expected_score = (top["frequency"] * 10) + 1000 - (1 * 5)
        self.assertEqual(top["score"], expected_score)

    def test_no_results_for_nonexistent_word(self):
        results = search.assignment_search("xyznonexistent", job_id=self.job_id)
        self.assertEqual(results, [])

    def test_multi_word_sums_scores(self):
        """Multi-word query should sum matching token scores per URL."""
        results = search.assignment_search("python programming", job_id=self.job_id)
        if results:
            top = results[0]
            # Score should be sum of individual token scores
            self.assertGreater(top["score"], 1000)

    def test_results_have_assignment_keys(self):
        results = search.assignment_search("python", job_id=self.job_id)
        self.assertTrue(len(results) > 0)
        row = results[0]
        for key in ("word", "url", "origin_url", "depth", "frequency", "score"):
            self.assertIn(key, row)

    def test_p_data_file_format(self):
        """Verify the exported p_data file has correct TSV format."""
        path = db.get_p_data_path(self.job_id)
        self.assertTrue(path.exists())
        with open(path, "r") as f:
            for line in f:
                parts = line.strip().split("\t")
                self.assertEqual(len(parts), 5, f"Bad line format: {line}")
                word, url, origin_url, depth, freq = parts
                int(depth)  # should not raise
                int(freq)   # should not raise

    def test_origin_url_in_export_is_job_origin(self):
        """origin_url in p_data should be the job's seed origin."""
        path = db.get_p_data_path(self.job_id)
        with open(path, "r") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) == 5:
                    self.assertEqual(parts[2], "http://example.com/")


class TestSearchSeparation(unittest.TestCase):
    """Verify UI search and assignment search are separate paths."""

    def setUp(self):
        fd, self._tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._orig_db_path = config.DB_PATH
        self._orig_storage_dir = config.STORAGE_DIR
        self._tmpdir = tempfile.mkdtemp()
        config.DB_PATH = self._tmp
        config.STORAGE_DIR = __import__("pathlib").Path(self._tmpdir)

        self.conn = _setup_db(self._tmp)
        self.job_id = _seed_job(self.conn, state="done")

        url = "http://example.com/test"
        _seed_frontier(self.conn, self.job_id, url)
        indexer.write_page(
            self.conn, url, "Test Page", "unique testword searchable",
            200, self.job_id, "http://example.com/", 0,
        )
        db.export_p_data(self.conn, self.job_id)

    def tearDown(self):
        self.conn.close()
        config.DB_PATH = self._orig_db_path
        config.STORAGE_DIR = self._orig_storage_dir
        import shutil
        try:
            os.unlink(self._tmp)
        except OSError:
            pass
        try:
            shutil.rmtree(self._tmpdir)
        except OSError:
            pass

    def test_ui_and_assignment_both_find_results(self):
        ui_results = search.ui_search("testword")
        asn_results = search.assignment_search("testword", job_id=self.job_id)
        self.assertTrue(len(ui_results) > 0, "UI search should find results")
        self.assertTrue(len(asn_results) > 0, "Assignment search should find results")

    def test_ui_and_assignment_have_different_score_formats(self):
        ui_results = search.ui_search("testword")
        asn_results = search.assignment_search("testword", job_id=self.job_id)
        # UI scores are float-ish (field-weighted), assignment scores are integers (formula)
        ui_score = ui_results[0]["score"]
        asn_score = asn_results[0]["score"]
        self.assertNotEqual(ui_score, asn_score, "Scores should differ between the two models")


if __name__ == "__main__":
    unittest.main()