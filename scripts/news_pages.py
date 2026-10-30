"""Conservative monitor for public news listing pages (not RSS).

Collects candidate announcements for an existing Gemini editorial pipeline.
Only accepts articles with a verifiable publication date. Pages that block
requests or have unsupported markup are skipped with a warning.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}
DATE_PATTERN = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2},?\s+20\d{2}\b"
    r"|\b20\d{2}-\d{2}-\d{2}\b",
    re.I,
)
TRACKING = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def clean_url(url: str) -> str:
    p = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                       if not k.lower().startswith("utm_") and k.lower() not in TRACKING])
    return urlunsplit((p.scheme, p.netloc, p.path, query, ""))


def parse_date(raw: str) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        pass
    match = DATE_PATTERN.search(raw)
    if not match:
        return None
    value = match.group(0).replace("Sept", "Sep").replace(".", "")
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def published_date(soup: BeautifulSoup) -> datetime | None:
    # Prefer machine-readable dates on an article page.
    for meta in soup.select('meta[property="article:published_time"], meta[name="date"], '
                            'meta[name="pubdate"], meta[name="datePublished"], '
                            'meta[itemprop="datePublished"], meta[property="og:published_time"]'):
        date = parse_date(meta.get("content", ""))
        if date:
            return date
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        def walk(node):
            if isinstance(node, dict):
                if node.get("datePublished"):
                    yield node["datePublished"]
                for val in node.values():
                    yield from walk(val)
            elif isinstance(node, list):
                for val in node:
                    yield from walk(val)
        for value in walk(data):
            date = parse_date(str(value))
            if date:
                return date
    for time in soup.select("time[datetime], time"):
        date = parse_date(time.get("datetime", "") or time.get_text(" ", strip=True))
        if date:
            return date
    # Visible date near the article heading is better than footer/copyright dates.
    main = soup.select_one("article, main, [role=main]") or soup
    heading = main.find(["h1", "h2"])
    if heading:
        node = heading
        for _ in range(4):
            if node is None:
                break
            date = parse_date(node.get_text(" ", strip=True)[:900])
            if date:
                return date
            node = node.parent
    return None


def summary_text(soup: BeautifulSoup) -> str:
    meta = soup.select_one('meta[name="description"], meta[property="og:description"]')
    if meta:
        value = meta.get("content", "").strip()
        if len(value) >= 60:
            return value[:650]
    for p in soup.select("article p, main p, [role=main] p"):
        value = p.get_text(" ", strip=True)
        if 60 <= len(value) <= 2000:
            return value[:650]
    return ""


def candidate_links(soup: BeautifulSoup, base_url: str, limit: int):
    seen = set()
    for heading in soup.select("main h2, main h3, article h2, article h3, h2, h3"):
        title = heading.get_text(" ", strip=True)
        if not 25 <= len(title) <= 230:
            continue
        anchor = heading.find("a", href=True) or heading.find_parent("a", href=True)
        if anchor is None:
            # Some pages put the 'Read more' link adjacent to the title.
            parent = heading.parent
            for _ in range(3):
                if parent is None:
                    break
                anchor = parent.find("a", href=True)
                if anchor:
                    break
                parent = parent.parent
        if anchor is None:
            continue
        href = clean_url(urljoin(base_url, anchor["href"]))
        p = urlsplit(href)
        if p.scheme not in ("http", "https") or not p.path.strip("/"):
            continue
        if href.rstrip("/") == base_url.rstrip("/") or href in seen:
            continue
        seen.add(href)
        yield title, href
        if len(seen) >= limit:
            break


def fetch_news_pages(pages: list[dict], lookback_days: int = 90,
                     max_per_source: int = 5) -> list[dict]:
    """Fetch dated article candidates from news listings, without inventing dates."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    results = []
    session = requests.Session()
    session.headers.update(HEADERS)
    for page in pages:
        name, listing_url = page["name"], page["url"]
        print(f"Reading news webpage: {name}")
        try:
            response = session.get(listing_url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
        except requests.RequestException as exc:
            print(f"  WARNING: Could not fetch listing ({exc})")
            continue

        count = 0
        # Limit detail requests to avoid burdening the publisher.
        for title, url in candidate_links(soup, listing_url, limit=12):
            try:
                detail = session.get(url, timeout=15)
                detail.raise_for_status()
                article_soup = BeautifulSoup(detail.text, "html.parser")
            except requests.RequestException as exc:
                print(f"  Skipped article: {title[:65]} ({exc})")
                continue
            published = published_date(article_soup)
            if published is None or not cutoff <= published <= datetime.now(timezone.utc) + timedelta(days=1):
                continue
            description = summary_text(article_soup)
            if len(description) < 60:
                continue
            results.append({
                "title": title,
                "summary": description,
                "source": name,
                "published_date": published.date().isoformat(),
                "url": url,
            })
            count += 1
            if count >= max_per_source:
                break
        print(f"  Dated candidates within {lookback_days} days: {count}")
    return results
