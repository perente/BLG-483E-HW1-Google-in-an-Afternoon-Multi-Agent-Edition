"""
parser.py

HTML parsing using stdlib html.parser.

Extracts:
  - page title
  - headings (h1, h2, h3) as [{level, text}, ...]
  - body text (whitespace-normalized, script/style excluded)
  - hyperlinks

Large body text is capped to MAX_BODY_SIZE to avoid oversized DB storage.
"""

import html.parser

try:
    from . import config
except ImportError:
    import config


class CrawlParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []
        self.title: str = ""
        self.headings: list[dict] = []  # [{"level": 1, "text": "..."}, ...]
        self._body_parts: list[str] = []
        self._in_skip = 0      # nesting depth inside script/style/head/noscript
        self._in_title = False
        self._in_heading: int | None = None  # current heading level (1-3) or None
        self._heading_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._in_skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in ("h1", "h2", "h3"):
            self._in_heading = int(tag[1])
            self._heading_parts = []
        elif tag in ("a", "link"):
            attr_dict = dict(attrs)
            href = attr_dict.get("href", "").strip()
            if href and not href.startswith(("#", "mailto:", "javascript:", "tel:")):
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._in_skip = max(0, self._in_skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in ("h1", "h2", "h3"):
            if self._in_heading is not None:
                text = " ".join(self._heading_parts).strip()
                if text:
                    self.headings.append({
                        "level": self._in_heading,
                        "text": text,
                    })
                self._in_heading = None
                self._heading_parts = []

    def handle_data(self, data):
        if self._in_skip:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title += text + " "
        if self._in_heading is not None:
            self._heading_parts.append(text)
        else:
            self._body_parts.append(text)

    @property
    def body_text(self) -> str:
        raw = " ".join(self._body_parts)
        max_size = getattr(config, "MAX_BODY_SIZE", 500_000)
        if len(raw) > max_size:
            return raw[:max_size]
        return raw


def parse(html_text: str, base_url: str = "") -> tuple[list[str], str, str, list[dict]]:
    """
    Parse HTML text into (links, body_text, title, headings).

    headings is a list of {"level": int, "text": str} dicts.
    """
    p = CrawlParser()
    try:
        p.feed(html_text)
    except Exception:
        pass
    return p.links, p.body_text, p.title.strip(), p.headings
