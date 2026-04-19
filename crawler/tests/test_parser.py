import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import parser


class TestParse(unittest.TestCase):

    def test_extracts_links(self):
        html = '<html><body><a href="/about">About</a><a href="http://example.com/">Home</a></body></html>'
        links, _, _, _ = parser.parse(html, base_url="http://example.com/")
        self.assertIn("/about", links)
        self.assertIn("http://example.com/", links)

    def test_extracts_title(self):
        html = "<html><head><title>My Page</title></head><body>hi</body></html>"
        _, _, title, _ = parser.parse(html)
        self.assertEqual(title, "My Page")

    def test_extracts_headings(self):
        html = "<html><body><h1>Main Title</h1><h2>Section</h2><h3>Sub</h3></body></html>"
        _, _, _, headings = parser.parse(html)
        self.assertEqual(len(headings), 3)
        self.assertEqual(headings[0]["level"], 1)
        self.assertEqual(headings[0]["text"], "Main Title")
        self.assertEqual(headings[1]["level"], 2)
        self.assertEqual(headings[1]["text"], "Section")
        self.assertEqual(headings[2]["level"], 3)
        self.assertEqual(headings[2]["text"], "Sub")

    def test_ignores_script_content(self):
        html = "<html><body><script>var x = 'secret';</script><p>visible</p></body></html>"
        _, body_text, _, _ = parser.parse(html)
        self.assertNotIn("secret", body_text)
        self.assertIn("visible", body_text)

    def test_ignores_style_content(self):
        html = "<html><head><style>body { color: red; }</style></head><body>text</body></html>"
        _, body_text, _, _ = parser.parse(html)
        self.assertNotIn("color", body_text)
        self.assertIn("text", body_text)

    def test_skips_mailto_and_fragment_links(self):
        html = '<a href="mailto:a@b.com">mail</a><a href="#section">anchor</a><a href="/ok">ok</a>'
        links, _, _, _ = parser.parse(html)
        self.assertNotIn("mailto:a@b.com", links)
        self.assertNotIn("#section", links)
        self.assertIn("/ok", links)

    def test_malformed_html_does_not_crash(self):
        bad = "<<<<<not html at all>>>>> <a href='/x'"
        try:
            links, body_text, title, headings = parser.parse(bad)
        except Exception as e:
            self.fail(f"parse() raised an exception on malformed HTML: {e}")

    def test_empty_string_does_not_crash(self):
        links, body_text, title, headings = parser.parse("")
        self.assertEqual(links, [])
        self.assertEqual(body_text, "")
        self.assertEqual(title, "")
        self.assertEqual(headings, [])

    def test_returns_four_tuple(self):
        result = parser.parse("<html></html>")
        self.assertEqual(len(result), 4)

    def test_heading_not_in_body_text(self):
        """Heading text should be in headings list, not duplicated in body_text."""
        html = "<html><body><h1>Heading Only</h1><p>Body text here</p></body></html>"
        _, body_text, _, headings = parser.parse(html)
        self.assertEqual(len(headings), 1)
        self.assertIn("Body text here", body_text)


if __name__ == "__main__":
    unittest.main()