"""
DMV Proton Therapy Collaborative
Automated News Agent

This script:
1. Reads the existing data/news.json.
2. Gives an OpenAI Responses API agent live web search.
3. Asks the agent to identify only recent, relevant, source-backed stories.
4. Returns structured JSON.
5. Deduplicates stories by URL.
6. Keeps the newest 18 stories.
7. Writes data/news.json.

The OPENAI_API_KEY must be provided as an environment variable.
Optional:
    OPENAI_NEWS_MODEL
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from openai import OpenAI


ROOT = Path(__file__).resolve().parents[1]
NEWS_FILE = ROOT / "data" / "news.json"

MODEL = os.getenv("OPENAI_NEWS_MODEL") or "gpt-6-astra"
MAX_STORIES = 18
LOOKBACK_DAYS = 7


CATEGORIES = [
    "Proton Therapy",
    "Radiation Oncology",
    "Medical Physics",
    "Research",
    "AI & Imaging",
    "Regional",
]


SCHEMA = {
    "type": "object",
    "properties": {
        "articles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": CATEGORIES,
                    },
                    "source": {"type": "string"},
                    "published_date": {
                        "type": "string",
                        "format": "date",
                    },
                    "url": {"type": "string"},
                },
                "required": [
                    "title",
                    "summary",
                    "category",
                    "source",
                    "published_date",
                    "url",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["articles"],
    "additionalProperties": False,
}


def load_existing() -> dict:
    if not NEWS_FILE.exists():
        return {"updated_at": None, "articles": []}

    with NEWS_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        return ""

    # Remove fragments because they do not identify a different article.
    return url.split("#", 1)[0]


def make_id(article: dict) -> str:
    normalized = normalize_url(article["url"])
    return normalized.rstrip("/").replace("https://", "").replace(
        "http://", ""
    )[:180]


def valid_article(article: dict) -> bool:
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
        datetime.strptime(article["published_date"], "%Y-%m-%d")
    except ValueError:
        return False

    return True


def build_prompt(existing_articles: list[dict]) -> str:
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

    return f"""
You are the news editor for the DMV Proton Therapy Collaborative,
a professional regional organization connecting proton therapy and
radiation oncology professionals in Washington, DC, Maryland, and Virginia.

Today's date is {today.isoformat()}.

Search the live web for important news published on or after
{cutoff.isoformat()}.

Find 0 to 6 NEW stories that are genuinely relevant to this audience.

Priority topics:
1. Proton therapy
2. Radiation oncology
3. Medical physics
4. Radiation treatment technology
5. Cancer treatment research directly relevant to radiation oncology
6. AI, imaging, adaptive radiotherapy, treatment planning, or automation
   when clearly relevant to radiation oncology
7. Major professional, clinical, regulatory, technology, or research
   developments involving proton therapy
8. Important developments in the Washington DC / Maryland / Virginia region

Prefer original or authoritative reporting:
- major cancer centers and universities
- ASTRO and other professional organizations
- NCI, NIH, FDA, and other authoritative agencies
- peer-reviewed or conference-related reporting
- established medical/scientific publications

Do NOT publish:
- generic cancer stories with no meaningful radiation/proton relevance
- promotional pages that are only advertisements
- patient testimonials unless there is a substantive professional development
- old stories merely resurfacing in search
- duplicate coverage of a story already present
- unsupported claims
- stories where you cannot identify a reliable original article URL

For each selected article:
- use the article's actual headline or a faithful shortened headline
- write a neutral 2-3 sentence summary
- do not exaggerate findings
- do not give medical advice
- classify it into exactly one of:
  {", ".join(CATEGORIES)}
- provide the actual publication date
- provide the canonical URL of the source article

The website displays the summary next to a "Read original" link.
The summary must therefore be faithful to the linked article.

Already published URLs:
{json.dumps(existing_urls, indent=2)}

Already published titles:
{json.dumps(existing_titles, indent=2)}

Return ONLY the requested structured data.
"""


def fetch_new_articles(client: OpenAI, existing_articles: list[dict]) -> list[dict]:
    response = client.responses.create(
        model=MODEL,
        tools=[
            {
                "type": "web_search",
                "search_context_size": "high",
            }
        ],
        input=[
            {
                "role": "system",
                "content": (
                    "You are a careful medical and scientific news editor. "
                    "You must use live web search and only return stories "
                    "that are supported by the source pages you find."
                ),
            },
            {
                "role": "user",
                "content": build_prompt(existing_articles),
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "dmv_proton_news",
                "strict": True,
                "schema": SCHEMA,
            }
        },
    )

    try:
        payload = json.loads(response.output_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "The model did not return valid structured JSON."
        ) from exc

    return payload.get("articles", [])


def merge_articles(existing: list[dict], new_articles: list[dict]) -> list[dict]:
    by_url: dict[str, dict] = {}

    for article in existing + new_articles:
        if not valid_article(article):
            continue

        article = dict(article)
        article["url"] = normalize_url(article["url"])
        article["id"] = article.get("id") or make_id(article)

        key = article["url"].lower()

        if key not in by_url:
            by_url[key] = article

    articles = list(by_url.values())

    articles.sort(
        key=lambda article: article["published_date"],
        reverse=True,
    )

    return articles[:MAX_STORIES]


def write_news(articles: list[dict]) -> None:
    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "articles": articles,
    }

    NEWS_FILE.parent.mkdir(parents=True, exist_ok=True)

    with NEWS_FILE.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main() -> int:
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1

    existing = load_existing()
    existing_articles = existing.get("articles", [])

    client = OpenAI()

    print(f"Searching for new stories using model: {MODEL}")

    new_articles = fetch_new_articles(
        client,
        existing_articles,
    )

    print(f"Agent returned {len(new_articles)} candidate stories.")

    merged = merge_articles(
        existing_articles,
        new_articles,
    )

    write_news(merged)

    print(f"Published feed now contains {len(merged)} stories.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
