"""
RSS 2.0 / Atom feed parsing: bytes in, a bounded list of normalized entries out.

Pure parsing, no network access and no persistence -- kept separate from fetching and
from document persistence so each can be tested and reasoned about independently.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional
from xml.etree.ElementTree import ParseError

import structlog
# defusedxml guards against XML entity-expansion ("billion laughs") and external-entity
# attacks from a feed response; a RegulatorySource.url is operator-configured but its
# response body is still untrusted third-party content, and the stdlib's own
# xml.etree.ElementTree.fromstring does not defend against those by default.
import defusedxml.ElementTree as ElementTree
from defusedxml.common import DefusedXmlException

logger = structlog.get_logger()

DEFAULT_MAX_ENTRIES = 50

ATOM_NS = "{http://www.w3.org/2005/Atom}"


class FeedParseError(ValueError):
    """Raised when the feed is not parseable XML at all."""


@dataclass
class FeedEntry:
    """
    One normalized item from a feed.

    guid is the best available stable identifier PARIVART can use for dedup/provenance:
    an explicit <guid>/<id>, falling back to the entry's link, falling back to None if
    the feed gives neither (content-hash-based dedup, applied downstream, still catches
    true duplicates in that case).
    """

    guid: Optional[str]
    title: str
    link: Optional[str]
    description: str
    published_at: Optional[datetime]


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    """Best-effort date parsing. A malformed or missing date is not a parse failure
    for the entry as a whole -- published_at is simply None."""
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)  # RFC 822, RSS's dialect
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))  # Atom's dialect
        except ValueError:
            logger.warning("rss_entry_date_unparseable", value=value)
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _text(element, *tag_candidates: str) -> Optional[str]:
    for tag in tag_candidates:
        found = element.find(tag)
        if found is not None and found.text:
            return found.text.strip()
    return None


def _parse_rss2_item(item) -> FeedEntry:
    title = _text(item, "title") or "Untitled RSS Entry"
    link = _text(item, "link")
    guid = _text(item, "guid") or link
    description = _text(item, "description") or title
    published_at = _parse_date(_text(item, "pubDate"))
    return FeedEntry(guid=guid, title=title, link=link, description=description, published_at=published_at)


def _parse_atom_entry(entry) -> FeedEntry:
    title = _text(entry, f"{ATOM_NS}title", "title") or "Untitled RSS Entry"
    link_el = entry.find(f"{ATOM_NS}link") if entry.find(f"{ATOM_NS}link") is not None else entry.find("link")
    link = link_el.get("href") if link_el is not None else None
    guid = _text(entry, f"{ATOM_NS}id", "id") or link
    description = _text(entry, f"{ATOM_NS}summary", "summary", f"{ATOM_NS}content", "content") or title
    published_at = _parse_date(_text(entry, f"{ATOM_NS}updated", "updated", f"{ATOM_NS}published", "published"))
    return FeedEntry(guid=guid, title=title, link=link, description=description, published_at=published_at)


def parse_feed(raw: bytes, max_entries: int = DEFAULT_MAX_ENTRIES) -> list[FeedEntry]:
    """
    Parse RSS 2.0 or Atom feed bytes into at most `max_entries` normalized entries.

    Raises FeedParseError for content that is not well-formed XML at all. A feed that
    parses but has zero items is a valid, empty result -- not an error: a source with
    nothing new to report is a successful run with zero discoveries, not a failure.
    """
    try:
        root = ElementTree.fromstring(raw)
    except ParseError as exc:
        raise FeedParseError(f"feed is not well-formed XML: {exc}") from exc
    except DefusedXmlException as exc:
        # An entity-expansion bomb or external-entity reference, not merely malformed
        # XML -- still surfaced as a parse failure to the caller, not re-raised as a
        # security exception type the ingestion-run error path wouldn't expect.
        raise FeedParseError(f"feed rejected as unsafe XML: {exc}") from exc

    items = root.findall("./channel/item")
    if items:
        entries = [_parse_rss2_item(item) for item in items[:max_entries]]
        return entries

    atom_entries = root.findall(f"{ATOM_NS}entry") or root.findall("entry")
    entries = [_parse_atom_entry(entry) for entry in atom_entries[:max_entries]]
    return entries
