import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import normalizer


class TestCanonicalize(unittest.TestCase):

    def test_resolves_relative_url(self):
        result = normalizer.canonicalize("/about", "https://example.com/page")
        self.assertEqual(result, "https://example.com/about")

    def test_resolves_relative_path(self):
        result = normalizer.canonicalize("../page", "https://example.com/a/b")
        self.assertEqual(result, "https://example.com/page")

    def test_removes_fragment(self):
        result = normalizer.canonicalize("https://example.com/a#section")
        self.assertEqual(result, "https://example.com/a")

    def test_preserves_query_parameters(self):
        result = normalizer.canonicalize("https://example.com/search?q=hello&page=2")
        self.assertIn("q=hello", result)
        self.assertIn("page=2", result)

    def test_lowercases_scheme(self):
        result = normalizer.canonicalize("HTTPS://Example.COM/path")
        self.assertTrue(result.startswith("https://"))

    def test_lowercases_host(self):
        result = normalizer.canonicalize("https://EXAMPLE.COM/path")
        self.assertIn("example.com", result)

    def test_rejects_ftp_scheme(self):
        result = normalizer.canonicalize("ftp://example.com/file")
        self.assertIsNone(result)

    def test_rejects_javascript_scheme(self):
        result = normalizer.canonicalize("javascript:void(0)")
        self.assertIsNone(result)

    def test_rejects_empty_string(self):
        result = normalizer.canonicalize("")
        self.assertIsNone(result)

    def test_absolute_http_passes_through(self):
        result = normalizer.canonicalize("http://example.com/page")
        self.assertEqual(result, "http://example.com/page")


class TestShouldEnqueue(unittest.TestCase):

    def test_accepts_normal_url(self):
        self.assertTrue(normalizer.should_enqueue("https://example.com/page"))

    def test_rejects_special_namespace(self):
        self.assertFalse(normalizer.should_enqueue("https://en.wikipedia.org/wiki/Special:Search"))

    def test_rejects_talk_namespace(self):
        self.assertFalse(normalizer.should_enqueue("https://en.wikipedia.org/wiki/Talk:Python"))

    def test_rejects_user_namespace(self):
        self.assertFalse(normalizer.should_enqueue("https://en.wikipedia.org/wiki/User:JohnDoe"))

    def test_rejects_file_namespace(self):
        self.assertFalse(normalizer.should_enqueue("https://en.wikipedia.org/wiki/File:Image.png"))

    def test_rejects_template_namespace(self):
        self.assertFalse(normalizer.should_enqueue("https://en.wikipedia.org/wiki/Template:Infobox"))

    def test_rejects_action_edit(self):
        self.assertFalse(normalizer.should_enqueue("https://en.wikipedia.org/w/index.php?action=edit"))

    def test_rejects_oldid(self):
        self.assertFalse(normalizer.should_enqueue("https://en.wikipedia.org/w/index.php?oldid=12345"))

    def test_rejects_diff(self):
        self.assertFalse(normalizer.should_enqueue("https://en.wikipedia.org/w/index.php?diff=99"))

    def test_allows_normal_query(self):
        self.assertTrue(normalizer.should_enqueue("https://example.com/search?q=hello"))

    def test_same_host_restriction_off_by_default(self):
        self.assertTrue(normalizer.should_enqueue(
            "https://external.com/page",
            origin="https://example.com",
            restrict_to_origin=False,
        ))

    def test_same_host_restriction_on(self):
        self.assertFalse(normalizer.should_enqueue(
            "https://external.com/page",
            origin="https://example.com",
            restrict_to_origin=True,
        ))

    def test_same_host_restriction_allows_same(self):
        self.assertTrue(normalizer.should_enqueue(
            "https://example.com/page",
            origin="https://example.com",
            restrict_to_origin=True,
        ))


class TestFilterNew(unittest.TestCase):

    def test_returns_new_urls(self):
        seen = set()
        result = normalizer.filter_new(["http://example.com/a"], seen)
        self.assertEqual(result, ["http://example.com/a"])

    def test_excludes_already_seen(self):
        seen = {"http://example.com/a"}
        result = normalizer.filter_new(["http://example.com/a"], seen)
        self.assertEqual(result, [])

    def test_adds_to_seen(self):
        seen = set()
        normalizer.filter_new(["http://example.com/a"], seen)
        self.assertIn("http://example.com/a", seen)

    def test_deduplicates_within_list(self):
        seen = set()
        result = normalizer.filter_new(
            ["http://example.com/a", "http://example.com/a"], seen
        )
        self.assertEqual(len(result), 1)

    def test_resolves_relative_links_with_base(self):
        seen = set()
        result = normalizer.filter_new(["/about"], seen, base="http://example.com/")
        self.assertEqual(result, ["http://example.com/about"])

    def test_filters_out_invalid(self):
        seen = set()
        result = normalizer.filter_new(["ftp://example.com", "mailto:x@y.com"], seen)
        self.assertEqual(result, [])

    def test_filters_wiki_namespace(self):
        seen = set()
        result = normalizer.filter_new(
            ["https://en.wikipedia.org/wiki/Special:Search"],
            seen,
        )
        self.assertEqual(result, [])

    def test_filters_action_edit(self):
        seen = set()
        result = normalizer.filter_new(
            ["https://example.com/page?action=edit"],
            seen,
        )
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()