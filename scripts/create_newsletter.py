"""Accumulate distinct stories in one Buttondown draft; never send emails."""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

# Windows/Miniconda certificate support.
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


def links_in_body(body):
    # Read existing Markdown or HTML article links.
    links = re.findall(r"\]\((https?://[^\s)]+)\)", body)
    links += re.findall(
        r"""href=["'](https?://[^"']+)["']""",
        body,
    )

    return {
        canonical_url(url)
        for url in links
        if canonical_url(url)
    }


def choose_articles(articles, excluded):
    seen = set(excluded)
    news = []
    research = []

    articles = sorted(
        articles,
        key=lambda a: a.get("published_date", ""),
        reverse=True,
    )

    for item in articles:
        url = canonical_url(item.get("url"))

        if not url or url in seen:
            continue

        if not item.get("title") or not item.get("summary"):
            continue

        article = {**item, "url": url}

        is_paper = (
            article.get("content_type") == "paper"
            or (
                not article.get("content_type")
                and "pubmed" in article.get("source", "").lower()
            )
        )

        if is_paper:
            research.append(article)
        else:
            news.append(article)

        seen.add(url)

    return news, research


def format_additions(news, research):
    sections = []

    for heading, articles in (
        ("News & Developments", news),
        ("Research & Publications", research),
    ):
        if not articles:
            continue

        block = [f"## {heading}", ""]

        for item in articles:
            title = item["title"].replace("\n", " ").strip()

            block.extend([
                f"### {title}",
                "",
                item["summary"].strip(),
                "",
                f"[Read original article]({item['url']})",
                "",
            ])

        sections.append("\n".join(block).rstrip())

    return "\n\n".join(sections)


def save_history(history):
    HISTORY_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    HISTORY_FILE.write_text(
        json.dumps(history, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main():
    key = os.getenv("BUTTONDOWN_API_KEY")

    if not key:
        raise RuntimeError("BUTTONDOWN_API_KEY is missing")

    feed = json.loads(
        NEWS_FILE.read_text(encoding="utf-8")
    )

    history = (
        json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        if HISTORY_FILE.exists()
        else {"drafted_article_urls": [], "drafts": []}
    )

    session = requests.Session()
    session.headers.update({
        "Authorization": f"Token {key}",
        "Content-Type": "application/json",
    })

    # Reuse the latest previously recorded draft.
    draft_id = history.get("active_draft_id")

    if not draft_id and history.get("drafts"):
        draft_id = history["drafts"][-1].get(
            "buttondown_email_id"
        )

    existing_body = ""
    included = set()

    if draft_id:
        response = session.get(
            f"{API_URL}/{draft_id}",
            timeout=30,
        )
        response.raise_for_status()

        remote = response.json()
        status = remote.get("status")

        if status == "draft":
            existing_body = remote.get("body")

            if not isinstance(existing_body, str):
                raise RuntimeError(
                    "Draft body not readable; refusing to overwrite"
                )

            included = links_in_body(existing_body)

            if history.get("active_draft_id") == draft_id:
                included.update(
                    canonical_url(u)
                    for u in history.get(
                        "active_article_urls", []
                    )
                )
            else:
                for old in reversed(history.get("drafts", [])):
                    if old.get("buttondown_email_id") == draft_id:
                        included.update(
                            canonical_url(u)
                            for u in old.get("article_urls", [])
                        )
                        break

        elif status == "sent":
            # Start a new issue after manual sending.
            previously_sent = set(
                history.get("sent_article_urls", [])
            )

            previously_sent.update(
                canonical_url(u)
                for u in history.get("active_article_urls", [])
            )

            previously_sent.update(
                links_in_body(remote.get("body") or "")
            )

            history["sent_article_urls"] = sorted(
                previously_sent
            )
            history["active_draft_id"] = None
            history["active_article_urls"] = []
            draft_id = None

        else:
            raise RuntimeError(
                f"Draft {draft_id} is {status!r}; "
                "nothing was modified"
            )

    excluded = (
        included
        if draft_id
        else set(history.get("sent_article_urls", []))
    )

    news, research = choose_articles(
        feed.get("articles", []),
        excluded,
    )

    new_articles = news + research

    if not new_articles:
        print("No new distinct articles. Existing draft unchanged.")
        save_history(history)
        return

    additions = format_additions(news, research)

    print(
        f"Adding {len(news)} news articles and "
        f"{len(research)} research papers"
    )

    if draft_id:
        # Append, preserving everything already in the draft.
        new_body = (
            existing_body.rstrip()
            + "\n\n"
            + additions
            + "\n"
        )

        response = session.patch(
            f"{API_URL}/{draft_id}",
            json={"body": new_body},
            timeout=30,
        )
        response.raise_for_status()

        print("Updated existing Buttondown draft:", draft_id)

    else:
        body = (
            "# DMV Proton Therapy Collaborative\n\n"
            "Curated news and research in proton therapy, "
            "radiation oncology, and medical physics.\n\n"
            + additions
            + "\n"
        )

        response = session.post(
            API_URL,
            json={
                "subject": (
                    "DMV Proton Therapy News — Working Draft"
                ),
                "body": body,
                "status": "draft",
            },
            timeout=30,
        )
        response.raise_for_status()

        draft_id = response.json().get("id")

        if not draft_id:
            raise RuntimeError(
                "Buttondown did not return an email ID"
            )

        history.setdefault("drafts", []).append({
            "buttondown_email_id": draft_id,
            "created_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "article_urls": [
                a["url"] for a in new_articles
            ],
        })

        print("Created new working draft:", draft_id)

    history["active_draft_id"] = draft_id
    history["active_article_urls"] = sorted(
        included | {a["url"] for a in new_articles}
    )

    save_history(history)

    print("Draft history saved. Nothing was sent.")


if __name__ == "__main__":
    main()
