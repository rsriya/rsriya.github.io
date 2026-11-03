"""Create and continuously update one Buttondown newsletter draft."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

# Fix Windows/Miniconda SSL certificate issues.
if os.name == "nt":
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass

import requests

ROOT = Path(__file__).resolve().parents[1]
NEWS_FILE = ROOT / "data" / "news.json"
HISTORY_FILE = ROOT / "data" / "newsletter_history.json"

API_URL = "https://api.buttondown.com/v1/emails"


def canonical_url(url):
    """Normalize URLs to prevent duplicate articles."""
    parsed = urlsplit(str(url or "").strip())

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""

    if parsed.hostname.lower() in {
        "pubmed.ncbi.nlm.nih.gov",
        "www.pubmed.ncbi.nlm.nih.gov",
    }:
        match = re.match(r"^/(\d+)/?", parsed.path)
        if match:
            return f"https://pubmed.ncbi.nlm.nih.gov/{match.group(1)}/"

    return urlunsplit((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path,
        parsed.query,
        "",
    ))


def collect_articles(history, feed):
    """Preserve existing articles and add new distinct articles."""
    articles = {}

    for item in history.get("articles", []) + feed.get("articles", []):
        if not isinstance(item, dict):
            continue

        url = canonical_url(item.get("url"))

        if not url or not item.get("title") or not item.get("summary"):
            continue

        if url not in articles:
            article = dict(item)
            article["url"] = url

            is_paper = (
                article.get("content_type") == "paper"
                or (
                    not article.get("content_type")
                    and "pubmed" in article.get("source", "").lower()
                )
            )

            article["content_type"] = "paper" if is_paper else "news"
            articles[url] = article

    return list(articles.values())


def make_body(articles):
    """Build a clean, organized newsletter."""

    lines = [
        "Your curated digest of proton therapy, radiation "
        "oncology, medical physics, and related research.",
        "",
        "---",
        "",
    ]

    for kind, heading in (
        ("news", "News & Developments"),
        ("paper", "Research & Publications"),
    ):
        stories = sorted(
            (a for a in articles if a["content_type"] == kind),
            key=lambda a: a.get("published_date", ""),
            reverse=True,
        )

        if not stories:
            continue

        lines.extend([
            f"## {heading}",
            "",
        ])

        for story in stories:
            title = " ".join(str(story["title"]).split())
            date = story.get("published_date", "")
            source = story.get("source", "")

            lines.extend([
                f"### {title}",
                "",
                f"*{source} | {date}*",
                "",
                str(story["summary"]).strip(),
                "",
                f"[Read original article]({story['url']})",
                "",
                "---",
                "",
            ])

    lines.extend([
        "Explore the latest updates on our "
        "[news page](https://dmv-proton.org/news.html).",
        "",
        "DMV Proton Therapy Collaborative",
    ])

    return "\n".join(lines)


def main():
    key = os.environ.get("BUTTONDOWN_API_KEY")

    if not key:
        raise RuntimeError("BUTTONDOWN_API_KEY is missing")

    feed = json.loads(NEWS_FILE.read_text(encoding="utf-8"))

    history = (
        json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        if HISTORY_FILE.exists()
        else {"active_draft_id": None, "articles": []}
    )

    if "articles" not in history:
        raise RuntimeError(
            "Old history format detected. Back it up and reset before running."
        )

    articles = collect_articles(history, feed)

    if not articles:
        print("No articles available. Nothing created.")
        return

    draft_id = history.get("active_draft_id")

    session = requests.Session()
    session.headers.update({
        "Authorization": f"Token {key}"
    })

    body = (
        "<!-- buttondown-editor-mode: plaintext -->\n"
        + make_body(articles)
    )

    if draft_id:
        # Update the same draft.
        response = session.get(
            f"{API_URL}/{draft_id}",
            timeout=30,
        )
        response.raise_for_status()

        draft = response.json()

        if draft.get("status") != "draft":
            raise RuntimeError(
                f"Email {draft_id} is not a draft. No changes made."
            )

        if draft.get("body") == body:
            print("Active draft is already up to date.")
        else:
            response = session.patch(
                f"{API_URL}/{draft_id}",
                json={"body": body},
                timeout=30,
            )
            response.raise_for_status()

            print("Updated draft:", draft_id)

    else:
        # Create the first draft.
        response = session.post(
            API_URL,
            json={
                "subject": "DMV Proton Therapy News — Working Draft",
                "body": body,
                "status": "draft",
            },
            timeout=30,
        )
        response.raise_for_status()

        draft_id = response.json().get("id")

        if not draft_id:
            raise RuntimeError("Buttondown did not return a draft ID")

        print("Created draft:", draft_id)

    history = {
        "active_draft_id": draft_id,
        "articles": articles,
    }

    HISTORY_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    HISTORY_FILE.write_text(
        json.dumps(history, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(
        f"Stored {len(articles)} distinct articles. Nothing was sent."
    )


if __name__ == "__main__":
    main()
