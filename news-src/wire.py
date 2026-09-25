"""Shared plumbing for the Stage Wire ingest: fetching, date parsing and
feed reading.

Stdlib only, deliberately - the GitHub Action then needs no pip install and
cannot break on a dependency update while nobody is looking.

Feeds in the wild are inconsistent in ways that matter here. Playbill dates
its items with `dc:date` and no timezone at all; BroadwayWorld writes
`Fri, 25 Sep 2026 12:54:54 EST`, and Python will not parse a named zone
like EST through %Z. Both were silently dateless until this module handled
them. Anything that cannot be dated is treated as undated rather than as
"now", so a broken feed can never fake a fresh story.
"""

import datetime as dt
import html as html_module
import re
import time
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

# Identifiable on purpose: several of these outlets refuse blank or obviously
# scripted agents, and a contact URL is the price of being let in.
UA = "stage-wire/0.1 (+https://rizzo.cc/news/ ; feed reader for rizzo.cc)"

ACCEPT = "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"

DC = "{http://purl.org/dc/elements/1.1/}"
ATOM = "{http://www.w3.org/2005/Atom}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"

# Named zones that turn up in RSS. %Z will not reliably parse these, so they
# are mapped by hand. Standard/daylight pairs both listed; being an hour out
# on a headline timestamp changes nothing downstream.
TZ_NAMES = {
    "UT": 0, "UTC": 0, "GMT": 0, "Z": 0,
    "EST": -5, "EDT": -4,
    "CST": -6, "CDT": -5,
    "MST": -7, "MDT": -6,
    "PST": -8, "PDT": -7,
}

DATE_FORMATS = (
    "%a, %d %b %Y %H:%M:%S %z",
    "%a, %d %b %Y %H:%M:%S",
    "%a, %d %b %Y %H:%M %z",
    "%a, %d %b %Y %H:%M",
    "%d %b %Y %H:%M:%S %z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


def fetch(url, timeout=30, retries=2):
    """GET with our UA. One retry with a short backoff clears most transient
    refusals; a source that fails twice is a real problem worth reporting."""
    last = None
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": ACCEPT})
            with urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # urllib raises a zoo of exception types
            last = e
            if attempt < retries:
                time.sleep(2 + attempt * 3)
    raise last


def parse_date(s):
    """Return a timezone-aware UTC datetime, or None if the string cannot be
    trusted. None means undated, never 'now'."""
    if not s:
        return None
    s = str(s).strip()
    if not s:
        return None

    offset_hours = None

    # Trailing Z, as in 2026-09-25T13:16:00Z
    if len(s) > 1 and s[-1] == "Z" and not s.endswith(" Z"):
        s, offset_hours = s[:-1], 0

    # Trailing named zone, as in "... 12:54:54 EST"
    m = re.search(r"\s([A-Za-z]{2,4})$", s)
    if m:
        name = m.group(1).upper()
        if name in TZ_NAMES:
            offset_hours = TZ_NAMES[name]
            s = s[: m.start()].strip()

    for fmt in DATE_FORMATS:
        try:
            d = dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
        if d.tzinfo is None:
            tz = dt.timezone(dt.timedelta(hours=offset_hours or 0))
            d = d.replace(tzinfo=tz)
        return d.astimezone(dt.timezone.utc)
    return None


def _text(node):
    if node is None or node.text is None:
        return ""
    return html_module.unescape(node.text).strip()


def strip_tags(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", s or "")).strip()


class Item:
    """One story as a feed described it, before any of our own judgement."""

    # feed_id / feed_name are filled in by the collector, which knows which
    # source the item came from; the parser does not.
    __slots__ = ("title", "link", "summary", "published", "source", "categories",
                 "feed_id", "feed_name")

    def __init__(self, title, link, summary, published, source, categories):
        self.title = title
        self.link = link
        self.summary = summary
        self.published = published
        self.source = source
        self.categories = categories
        self.feed_id = ""
        self.feed_name = ""

    def __repr__(self):
        when = self.published.date().isoformat() if self.published else "undated"
        return f"<Item {when} {self.source or '?'}: {self.title[:60]!r}>"


def _rss_items(root):
    for e in root.findall(".//item"):
        title = _text(e.find("title"))
        link = _text(e.find("link"))
        summary = _text(e.find("description")) or _text(e.find(CONTENT + "encoded"))
        published = parse_date(_text(e.find("pubDate")) or _text(e.find(DC + "date")))

        # Google News puts the originating outlet in <source>; everyone else
        # leaves it out and the caller names the feed itself.
        src_node = e.find("source")
        source = _text(src_node) if src_node is not None else ""

        categories = [_text(c) for c in e.findall("category")]
        categories += [_text(c) for c in e.findall(DC + "subject")]

        yield Item(title, link, strip_tags(summary), published, source,
                   [c for c in categories if c])


def _atom_items(root):
    for e in root.findall(".//" + ATOM + "entry"):
        title = _text(e.find(ATOM + "title"))
        link = ""
        for l in e.findall(ATOM + "link"):
            rel = l.get("rel") or "alternate"
            if rel == "alternate" and l.get("href"):
                link = l.get("href")
                break
        summary = _text(e.find(ATOM + "summary")) or _text(e.find(ATOM + "content"))
        published = parse_date(
            _text(e.find(ATOM + "published")) or _text(e.find(ATOM + "updated"))
        )
        categories = [c.get("term") for c in e.findall(ATOM + "category") if c.get("term")]
        yield Item(title, link, strip_tags(summary), published, "", categories)


def parse_feed(body):
    """Read an RSS or Atom document into Items. Raises on malformed XML, which
    the caller reports as a failed source rather than an empty one."""
    root = ET.fromstring(body)
    items = list(_rss_items(root))
    if not items:
        items = list(_atom_items(root))
    return items


def age_hours(when, now=None):
    if when is None:
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    return (now - when).total_seconds() / 3600


def clamp_future(when, now=None):
    """A timestamp cannot be in the future, whatever the feed says.

    BroadwayWorld labels every timestamp EST even in daylight saving, so
    half the year its stories arrive stamped an hour ahead. Left alone, a
    future date would pin a story to the top of the list until the clock
    caught up.
    """
    if when is None:
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    return min(when, now)
