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

import requests
import feedparser
from google import genai
from google.genai import types
from news_pages import fetch_news_pages

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
        "name": "NCI Cancer Currents",
        "url": "https://www.cancer.gov/publishedcontent/rss/news-events/cancer-currents-blog.rss",
    },
    {
        "name": "PubMed Proton Therapy",
        "url": "https://pubmed.ncbi.nlm.nih.gov/rss/search/1TyHVUJDxNJSqZjLRrxIc-xM-9cL987x7-RhQrikMJRwTmGQVM/?limit=100&utm_campaign=pubmed-2&fc=20261026170100"
    },
    {
        "name": "PubMed Medical Physics",
        "url": "https://pubmed.ncbi.nlm.nih.gov/rss/search/1P9hIDIGI6NPG2TSIA1BW_OWoyQvN5KTS9D0K8drayqnxH2Yen/?limit=100&utm_campaign=pubmed-2&fc=20261026171808"
    },
    {
        "name": "PubMed AI",
        "url": "https://pubmed.ncbi.nlm.nih.gov/rss/search/1FiYL_imNw8xy2fFLHvyWg5mfmFq-bGG9MIjBWDDgg_f-megfv/?limit=100&utm_campaign=pubmed-2&fc=20261026171942"
    },
    {
        "name": "NAPT News",
        "url": "https://proton-therapy.org/category/napt-news/feed/",
    },
    {
        "name": "AAPM News",
        "url": "https://www.aapm.org/rss/feed.asp",
    },
    {
        "name": "ASTRO News",
        "url": (
            "https://news.google.com/rss/search?"
            "q=site%3Aastro.org%20%22radiation%20therapy%22"
            "&hl=en-US&gl=US&ceid=US:en"
        ),
    },
]


NEWS_PAGES = [
    {
        "name": "Penn Radiation Medicine",
        "url": "https://rmi.pennmedicine.org/news/",
    },
    {
        "name": "UF Health Proton Therapy",
        "url": "https://www.floridaproton.org/news",
    },
    {
        "name": "Connecticut Proton Center",
        "url": "https://ctproton.org/news-press/",
    },
]

NEWS_SOURCES = {
    "NAPT News",
    "NCI Cancer Currents",
    "AAPM News",
    "ASTRO News",
    *(page["name"] for page in NEWS_PAGES),
}

LOOKBACK_DAYS = 30
NEWS_LOOKBACK_DAYS = 90
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

    candidates = []

    for feed_info in RSS_FEEDS:

        print(
            f"Reading RSS feed: "
            f"{feed_info['name']}"
        )
        source_count = 0
        try:
            if feed_info["name"] == "NAPT News":
                feed = feedparser.parse(feed_info["url"])
        
                if feed.get("status") != 200:
                    print(
                        f"WARNING: NAPT returned HTTP "
                        f"{feed.get('status')}"
                    )
                    continue

            else:
                response = requests.get(feed_info['url'], timeout=20)
                response.raise_for_status()
    
                feed = feedparser.parse(response.content)
        
                if not feed.entries:
                    print(
                        f"WARNING: No entries found in "
                        f"{feed_info['name']}"
                    )
                    continue
    
        except requests.RequestException as e:
            print(
                f"WARNING: Could not access "
                f"{feed_info['name']} ({feed_info['url']}): {e}"
            )
            continue
        if getattr(feed, "bozo", False):
            print(
                f"WARNING: RSS feed may be malformed: "
                f"{feed_info['name']}",
                file=sys.stderr,
            )
        is_news_source = feed_info["name"] in NEWS_SOURCES
        
        lookback = (
            NEWS_LOOKBACK_DAYS
            if is_news_source
            else LOOKBACK_DAYS
        )
        
        cutoff = datetime.now(timezone.utc) - timedelta(
            days=lookback
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
            source_count += 1
        print(
            f"  Total RSS entries: {len(feed.entries)}"
            f" | Within {lookback} days: {source_count}"
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
    
    # Prioritize all recent NAPT and NCI articles.
    priority_articles = [
        article for article in candidates
        if article["source"] in NEWS_SOURCES
    ]
    
    pubmed_articles = [
        article for article in candidates
        if article["source"] not in NEWS_SOURCES
    ]
    
    # Reserve slots for NAPT and NCI.
    remaining_slots = max(
        0,
        MAX_CANDIDATES - len(priority_articles)
    )
    
    selected_pubmed = pubmed_articles[:remaining_slots]
    
    final_candidates = priority_articles + selected_pubmed
    
    print("\nArticles sent to Gemini:")
    
    from collections import Counter
    
    counts = Counter(
        article["source"]
        for article in final_candidates
    )
    
    for feed_info in RSS_FEEDS:
        name = feed_info["name"]
        print(f"  {name}: {counts[name]}")
    
    print(f"  TOTAL: {len(final_candidates)}")
    
    return final_candidates


# ---------------------------------------------------------------------
# GEMINI PROMPT
# ---------------------------------------------------------------------

def build_prompt(
    candidates: list[dict],
    existing_articles: list[dict],
    editorial_type: str = "research",
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
    if editorial_type == "news":
        editorial_instructions = """
    You are selecting INDUSTRY NEWS, not scientific papers.
    
    Prioritize:
    - New proton therapy centers beginning patient treatments.
    - Proton center openings, expansions, and closures.
    - Medicare reimbursement and insurance coverage changes.
    - Healthcare policy affecting proton therapy access.
    - Important professional and technology announcements.
    - Regional proton therapy developments.
    
    IMPORTANT:
    A significant Medicare reimbursement proposal affecting proton
    therapy centers is relevant professional news.
    
    Do not reject an article merely because it comes from an
    advocacy organization. Evaluate the factual development and
    distinguish reported facts from opinions.
    
    Avoid redundant coverage of the same development.
    Return 0 to 4 relevant news articles.
    """
    else:
        editorial_instructions = """
    You are selecting SCIENTIFIC RESEARCH PUBLICATIONS.
    
    Prioritize important advances in proton therapy,
    radiation oncology, medical physics, treatment planning,
    dosimetry, and relevant AI applications.
    
    Return 0 to 6 relevant research articles.
    """
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

RECENCY REQUIREMENTS

Research publications have a 30-day lookback.
Industry news has a 90-day lookback.
Candidates have already passed the appropriate date filters. 

{editorial_instructions}

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
9. Proton therapy reimbursement, Medicare and Medicaid policy,
   insurance coverage, healthcare regulations, and patient access.
10. Proton center openings, first-patient treatments,
    expansions, closures, and financial sustainability.

PRIORITY NEWS

1. New proton therapy centers opening or beginning patient treatments.
2. Existing centers expanding, upgrading, or introducing new technologies.
3. Important radiation oncology clinical guidelines from ASTRO
   and other professional societies.
4. Medicare reimbursement, insurance coverage, and patient access.
5. Major medical physics guidance, standards, and safety developments.
6. First-in-human proton therapy trials and major clinical milestones.
7. Important proton therapy equipment and technology developments.

Do not include routine staffing announcements, patient testimonials,
marketing claims, or minor corporate updates.

For manufacturer press releases, distinguish contracts and planned
installations from completed installations and clinical operations.

Deduplicate events across sources, even when their headlines and
URLs differ.

EDITORIAL GUIDANCE

- Include important proton therapy policy and reimbursement
  developments even when published by advocacy organizations.
- Distinguish factual policy developments from advocacy opinions.
- Summarize proposed regulations as proposals, not final decisions.
- Do not exclude a significant policy story merely because the
  source is an advocacy organization.
- Avoid publishing multiple articles covering substantially
  the same policy development.
  
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
    editorial_type: str = "research",
) -> list[dict]:
    """Ask Gemini to select and summarize relevant RSS articles."""

    if not candidates:
        return []

    response = client.models.generate_content(
        model=MODEL,
        contents=build_prompt(
            candidates,
            existing_articles,
            editorial_type,
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
    """Validate, deduplicate, and balance research and news."""

    by_url: dict[str, dict] = {}

    for article in existing + new_articles:

        if not valid_article(article):
            continue

        article = dict(article)
        article["url"] = normalize_url(article["url"])
        article["id"] = article.get("id") or make_id(article)

        # Preserve explicit type, otherwise infer from source.
        if article.get("content_type") not in {"paper", "news"}:
            article["content_type"] = (
                "paper"
                if "pubmed" in article["source"].lower()
                else "news"
            )

        key = article["url"].lower()

        # Prefer the newly generated version if a URL repeats.
        by_url[key] = article

    articles = list(by_url.values())

    papers = sorted(
        [a for a in articles if a["content_type"] == "paper"],
        key=lambda a: a["published_date"],
        reverse=True,
    )

    news = sorted(
        [a for a in articles if a["content_type"] == "news"],
        key=lambda a: a["published_date"],
        reverse=True,
    )

    # Reserve slots for both sections.
    selected_papers = papers[:12]
    selected_news = news[:6]

    # Fill unused slots with the newest remaining articles.
    remaining = (
        papers[len(selected_papers):]
        + news[len(selected_news):]
    )

    remaining.sort(
        key=lambda a: a["published_date"],
        reverse=True,
    )

    available_slots = MAX_STORIES - (
        len(selected_papers) + len(selected_news)
    )

    merged = (
        selected_papers
        + selected_news
        + remaining[:max(0, available_slots)]
    )

    merged.sort(
        key=lambda a: a["published_date"],
        reverse=True,
    )

    print("\nFinal published articles:")
    print(
        f"  Research: "
        f"{sum(a['content_type'] == 'paper' for a in merged)}"
    )
    print(
        f"  News: "
        f"{sum(a['content_type'] == 'news' for a in merged)}"
    )

    return merged



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

    rss_candidates = fetch_rss_articles()
    
    web_candidates = fetch_news_pages(
        NEWS_PAGES,
        lookback_days=NEWS_LOOKBACK_DAYS,
        max_per_source=5,
    )
    
    # Combine RSS and webpage candidates.
    by_url = {}
    
    for article in rss_candidates + web_candidates:
        key = normalize_url(article["url"]).lower()
        by_url[key] = article
    
    candidates = list(by_url.values())
    
    print(f"\nRSS candidates: {len(rss_candidates)}")
    print(f"Webpage candidates: {len(web_candidates)}")
    print(f"Combined unique candidates: {len(candidates)}")

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
    
    news_candidates = [
        article for article in candidates
        if article["source"] in NEWS_SOURCES
    ]
    
    research_candidates = [
        article for article in candidates
        if article["source"] not in NEWS_SOURCES
    ]
    
    print(f"\nEvaluating {len(news_candidates)} news articles...")
    
    selected_news = select_articles_with_gemini(
        client,
        news_candidates,
        existing_articles,
        editorial_type="news",
    )
    
    print(f"Gemini selected {len(selected_news)} news articles.")
    
    for article in selected_news:
        print(f"  [NEWS] {article['title']}")
    
    
    print(f"\nEvaluating {len(research_candidates)} research papers...")
    
    selected_research = select_articles_with_gemini(
        client,
        research_candidates,
        existing_articles,
        editorial_type="research",
    )

    print(f"Gemini selected {len(selected_research)} research papers.")
    
    for article in selected_research:
        print(f"  [RESEARCH] {article['title']}")
    
    
    new_articles = selected_news + selected_research

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
