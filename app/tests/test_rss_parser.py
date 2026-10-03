"""
app/ingestion/rss_parser.py: pure parsing, no network. Fixture XML only.
"""

from datetime import timezone

import pytest

from app.ingestion.rss_parser import FeedParseError, parse_feed

VALID_RSS2 = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>First Notice</title>
      <link>https://example.com/notice-1</link>
      <guid>urn:example:notice-1</guid>
      <description>Details of the first notice.</description>
      <pubDate>Mon, 01 Sep 2026 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Second Notice</title>
      <link>https://example.com/notice-2</link>
      <guid>urn:example:notice-2</guid>
      <description>Details of the second notice.</description>
      <pubDate>Tue, 02 Sep 2026 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

VALID_ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test Atom Feed</title>
  <entry>
    <title>Atom Entry One</title>
    <id>urn:example:atom-1</id>
    <link href="https://example.com/atom-1"/>
    <summary>Atom entry summary.</summary>
    <updated>2026-09-01T12:00:00Z</updated>
  </entry>
</feed>
"""

EMPTY_RSS2 = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Empty Feed</title></channel></rss>
"""

MISSING_GUID_AND_TITLE = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <link>https://example.com/no-title</link>
      <description>No title or guid given.</description>
    </item>
  </channel>
</rss>
"""

MALFORMED_XML = b"<rss version=\"2.0\"><channel><item><title>Unclosed"

BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ELEMENT lolz (#PCDATA)>
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<rss version="2.0"><channel><item><title>&lol3;</title></channel></rss>
"""


def test_parses_valid_rss2_entries_in_order():
    entries = parse_feed(VALID_RSS2)
    assert len(entries) == 2
    assert entries[0].title == "First Notice"
    assert entries[0].guid == "urn:example:notice-1"
    assert entries[0].link == "https://example.com/notice-1"
    assert entries[0].description == "Details of the first notice."
    assert entries[0].published_at.tzinfo is not None
    assert entries[1].title == "Second Notice"


def test_parses_valid_atom_entries():
    entries = parse_feed(VALID_ATOM)
    assert len(entries) == 1
    assert entries[0].title == "Atom Entry One"
    assert entries[0].guid == "urn:example:atom-1"
    assert entries[0].link == "https://example.com/atom-1"
    assert entries[0].description == "Atom entry summary."


def test_empty_feed_returns_empty_list_not_an_error():
    assert parse_feed(EMPTY_RSS2) == []


def test_missing_title_and_guid_fall_back_safely():
    entries = parse_feed(MISSING_GUID_AND_TITLE)
    assert len(entries) == 1
    assert entries[0].title == "Untitled RSS Entry"
    # guid falls back to link when the feed gives no explicit guid.
    assert entries[0].guid == "https://example.com/no-title"


def test_malformed_xml_raises_feed_parse_error():
    with pytest.raises(FeedParseError):
        parse_feed(MALFORMED_XML)


def test_entity_expansion_bomb_is_rejected_not_expanded():
    """A billion-laughs-style payload must be refused as unsafe, never expanded."""
    with pytest.raises(FeedParseError):
        parse_feed(BILLION_LAUGHS)


def test_max_entries_bounds_how_many_items_are_parsed():
    many_items = b"".join(
        f"<item><title>Item {i}</title><guid>g{i}</guid></item>".encode()
        for i in range(10)
    )
    feed = b"<rss version=\"2.0\"><channel>" + many_items + b"</channel></rss>"

    entries = parse_feed(feed, max_entries=3)

    assert len(entries) == 3
    assert entries[0].title == "Item 0"
