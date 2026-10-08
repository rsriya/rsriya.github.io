"""
DMV Proton Therapy Collaborative
Automated News Agent

This script:
1. Reads the existing data/news.json.
2. Fetches recent articles from selected RSS feeds.
3. Filters obvious irrelevant/old articles.
4. Gives the candidate articles to Gemini.
5. Gemini selects only genuinely relevant stories.
6. Gemini writes neutral summaries and categories.
7. Deduplicates stories by URL.
8. Keeps the newest 18 stories.
9. Writes data/news.json.

The GEMINI_API_KEY must be provided as an environment variable.

Optional:
    GEMINI_NEWS_MODEL
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import feedparser
from google import genai
from google.genai import types


ROOT = Path(__file__).resolve().parents[1]
NEWS_FILE = ROOT / "data" / "news.json"

MODEL = os.getenv("GEMINI_NEWS_MODEL") or "gemini-3.1-flash-lite"

MAX_STORIES = 18
LOOKBACK_DAYS = 7
MAX_CANDIDATES = 40


CATEGORIES = [
    "Proton Therapy",
    "Radiation Oncology",
    "Medical Physics",
    "Research",
    "AI & Imaging",
    "Regional",
]


# ---------------------------------------------------------------------
# RSS SOURCES
# ---------------------------------------------------------------------
#
# Add or remove feeds here as needed.
#
# The exact RSS URL for a source can change, so check each source's
# current feed URL if a feed stops working.
#
RSS_FEEDS = [
    {
        "name": "NCI",
        "url": "https://www.cancer.gov/news-events/press-releases/2026",
    },
    {
        "name": "NIH Research Matters",
        "url": "https://www.nih.gov/nih-research-matters/feed.xml",
    },
    {
        "name": "ASTRO",
        "url": "https://www.astro.org/news-and-publications/news-and-media-center/news-releases",
    },
]


# ---------------------------------------------------------------------
# GEMINI STRUCTURED OUTPUT
# ---------------------------------------------------------------------

SCHEMA = {
    "type": "object",
    "properties": {
        "articles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                    },
                    "summary": {
                        "type": "string",
                    },
                    "category": {
                        "type": "string",
                        "enum": CATEGORIES,
                    },
                    "source": {
                        "type": "string",
                    },
                    "published_date": {
                        "type": "string",
                        "format": "date",
                    },
                    "url": {
                        "type": "string",
                    },
                },
                "required": [
                    "title",
                    "summary",
                    "category",
                    "source",
                    "published_date",
                    "url",
                ],
            },
        }
    },
    "required": ["articles"],
}


# ---------------------------------------------------------------------
# LOAD EXISTING NEWS
# ---------------------------------------------------------------------

def load_existing() -> dict:
    """Load the existing news feed."""

    if not NEWS_FILE.exists():
        return {
            "updated_at": None,
            "articles": [],
        }

    with NEWS_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------
# URL HELPERS
# ---------------------------------------------------------------------

def normalize_url(url: str) -> str:
    """Normalize a URL for validation and deduplication."""

    url = url.strip()

    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        return ""

    # Remove fragments because they do not identify a different article.
    return url.split("#", 1)[0]


def make_id(article: dict) -> str:
    """Create a stable ID from the article URL."""

    normalized = normalize_url(article["url"])

    return (
        normalized
        .rstrip("/")
        .replace("https://", "")
        .replace("http://", "")
    )[:180]


# ---------------------------------------------------------------------
# ARTICLE VALIDATION
# ---------------------------------------------------------------------

def valid_article(article: dict) -> bool:
    """Check whether an article has the required structure."""

    if not isinstance(article, dict):
        return False

    required = [
        "title",
        "summary",
        "category",
        "source",
        "published_date",
        "url",
    ]

    if not all(article.get(key) for key in required):
        return False

    if article["category"] not in CATEGORIES:
        return False

    url = normalize_url(article["url"])

    if not url:
        return False

    if len(article["title"]) < 15:
        return False

    if len(article["summary"]) < 60:
        return False

    try:
        datetime.strptime(
            article["published_date"],
            "%Y-%m-%d",
        )
    except ValueError:
        return False

    return True


# ---------------------------------------------------------------------
# RSS FETCHING
# ---------------------------------------------------------------------

def parse_entry_date(entry) -> datetime | None:
    """Get a publication date from an RSS entry."""

    if getattr(entry, "published_parsed", None):
        try:
            return datetime(
                *entry.published_parsed[:6],
                tzinfo=timezone.utc,
            )
        except (TypeError, ValueError):
            pass

    if getattr(entry, "updated_parsed", None):
        try:
            return datetime(
                *entry.updated_parsed[:6],
                tzinfo=timezone.utc,
            )
        except (TypeError, ValueError):
            pass

    return None


def fetch_rss_articles() -> list[dict]:
    """Fetch recent articles from all configured RSS feeds."""

    cutoff = datetime.now(timezone.utc) - timedelta(
        days=LOOKBACK_DAYS
    )

    candidates = []

    for feed_info in RSS_FEEDS:

        print(
            f"Reading RSS feed: "
            f"{feed_info['name']}"
        )

        try:
            feed = feedparser.parse(
                feed_info["url"]
            )
        except Exception as exc:
            print(
                f"WARNING: Could not read "
                f"{feed_info['name']}: {exc}",
                file=sys.stderr,
            )
            continue

        if getattr(feed, "bozo", False):
            print(
                f"WARNING: RSS feed may be malformed: "
                f"{feed_info['name']}",
                file=sys.stderr,
            )

        for entry in feed.entries:

            title = (
                getattr(entry, "title", "")
                or ""
            ).strip()

            url = normalize_url(
                getattr(entry, "link", "")
                or ""
            )

            published = parse_entry_date(entry)

            if not title or not url or not published:
                continue

            if published < cutoff:
                continue

            summary = (
                getattr(entry, "summary", "")
                or ""
            ).strip()

            candidates.append(
                {
                    "title": title,
                    "summary": summary,
                    "source": feed_info["name"],
                    "published_date": published.date().isoformat(),
                    "url": url,
                }
            )

    # Deduplicate RSS results by URL.
    by_url = {}

    for article in candidates:
        key = article["url"].lower()

        if key not in by_url:
            by_url[key] = article

    candidates = list(by_url.values())

    # Newest first.
    candidates.sort(
        key=lambda article: article["published_date"],
        reverse=True,
    )

    return candidates[:MAX_CANDIDATES]


# ---------------------------------------------------------------------
# GEMINI PROMPT
# ---------------------------------------------------------------------

def build_prompt(
    candidates: list[dict],
    existing_articles: list[dict],
) -> str:
    """Build the Gemini article-selection prompt."""

    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=LOOKBACK_DAYS)

    existing_urls = [
        normalize_url(article.get("url", ""))
        for article in existing_articles
        if article.get("url")
    ]

    existing_titles = [
        article.get("title", "")
        for article in existing_articles
        if article.get("title")
    ]

    candidate_text = json.dumps(
        candidates,
        indent=2,
        ensure_ascii=False,
    )

    return f"""
You are the news editor for the DMV Proton Therapy Collaborative.

Today's date is {today.isoformat()}.

The organization connects proton therapy, radiation oncology,
medical physics, research, and related professionals in
Washington, DC, Maryland, and Virginia.

You have been given recent articles collected directly from
RSS feeds.

Your task is to select ONLY genuinely useful articles for the
organization's professional audience.

The articles were collected from:
{cutoff.isoformat()} onward.

Return 0 to 6 selected articles.

PRIORITY TOPICS

1. Proton therapy
2. Radiation oncology
3. Medical physics
4. Radiation treatment technology
5. Cancer treatment research directly relevant to radiation oncology
6. AI, medical imaging, adaptive radiotherapy, treatment planning,
   automation, or machine learning when clearly relevant to
   radiation oncology
7. Major professional, clinical, regulatory, technology, or research
   developments involving proton therapy
8. Important developments in Washington DC, Maryland, or Virginia

DO NOT SELECT

- Generic cancer stories without meaningful radiation relevance
- Generic healthcare stories
- Promotional material
- Patient testimonials
- Fundraising announcements
- Old stories
- Duplicate stories
- Stories that are only loosely related to radiation oncology
- Articles that do not contain meaningful professional or research news

RELEVANCE STANDARD

When in doubt, DO NOT include the article.

The DMV Proton Therapy Collaborative is a professional resource,
not a general cancer-news website.

SUMMARY REQUIREMENTS

For each selected article:

- Use the original headline or a faithful shortened version.
- Write a neutral 2-3 sentence summary.
- Do not exaggerate findings.
- Do not provide medical advice.
- Do not introduce facts that are not supported by the article.
- Classify the article into exactly one category:

  {", ".join(CATEGORIES)}

- Use the article's publication date.
- Use the supplied URL.
- Use the supplied source name.

IMPORTANT

Do not invent URLs.

Do not modify URLs unless removing an obvious URL fragment.

ALREADY PUBLISHED URLS

{json.dumps(existing_urls, indent=2)}

ALREADY PUBLISHED TITLES

{json.dumps(existing_titles, indent=2)}

CANDIDATE ARTICLES

{candidate_text}

Return ONLY the requested structured data.
"""


# ---------------------------------------------------------------------
# GEMINI
# ---------------------------------------------------------------------

def select_articles_with_gemini(
    client: genai.Client,
    candidates: list[dict],
    existing_articles: list[dict],
) -> list[dict]:
    """Ask Gemini to select and summarize relevant RSS articles."""

    if not candidates:
        return []

    response = client.models.generate_content(
        model=MODEL,
        contents=build_prompt(
            candidates,
            existing_articles,
        ),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=SCHEMA,
        ),
    )

    if not response.text:
        raise RuntimeError(
            "Gemini returned an empty response."
        )

    try:
        payload = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Gemini did not return valid structured JSON."
        ) from exc

    return payload.get("articles", [])


# ---------------------------------------------------------------------
# MERGE
# ---------------------------------------------------------------------

def merge_articles(
    existing: list[dict],
    new_articles: list[dict],
) -> list[dict]:
    """Validate, deduplicate, sort, and limit the news feed."""

    by_url: dict[str, dict] = {}

    for article in existing + new_articles:

        if not valid_article(article):
            continue

        article = dict(article)

        article["url"] = normalize_url(
            article["url"]
        )

        article["id"] = (
            article.get("id")
            or make_id(article)
        )

        key = article["url"].lower()

        if key not in by_url:
            by_url[key] = article

    articles = list(by_url.values())

    articles.sort(
        key=lambda article: article["published_date"],
        reverse=True,
    )

    return articles[:MAX_STORIES]


# ---------------------------------------------------------------------
# WRITE NEWS
# ---------------------------------------------------------------------

def write_news(articles: list[dict]) -> None:
    """Write the final news feed to data/news.json."""

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "articles": articles,
    }

    NEWS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with NEWS_FILE.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            output,
            f,
            indent=2,
            ensure_ascii=False,
        )

        f.write("\n")


# ---------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------

def main() -> int:

    if not os.getenv("GEMINI_API_KEY"):
        print(
            "ERROR: GEMINI_API_KEY is not set.",
            file=sys.stderr,
        )
        return 1

    existing = load_existing()

    existing_articles = existing.get(
        "articles",
        [],
    )

    print(
        f"Fetching RSS articles from "
        f"{len(RSS_FEEDS)} sources..."
    )

    candidates = fetch_rss_articles()

    print(
        f"Found {len(candidates)} recent RSS "
        f"candidate articles."
    )

    if not candidates:
        print(
            "No recent RSS articles found."
        )

        # Still update updated_at so the workflow
        # records that it ran successfully.
        write_news(existing_articles)

        return 0

    client = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"]
    )

    print(
        f"Sending candidates to Gemini "
        f"using model: {MODEL}"
    )

    new_articles = select_articles_with_gemini(
        client,
        candidates,
        existing_articles,
    )

    print(
        f"Gemini selected "
        f"{len(new_articles)} articles."
    )

    merged = merge_articles(
        existing_articles,
        new_articles,
    )

    write_news(merged)

    print(
        f"Published feed now contains "
        f"{len(merged)} stories."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
