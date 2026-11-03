"""Create and maintain Buttondown newsletter drafts.

- Update the current draft when new articles arrive.
- Archive article URLs when a newsletter has been sent.
- Start a new draft using only previously unsent articles.
- Never send emails automatically.
"""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

# Windows/Miniconda SSL certificate support.
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


# -----------------------------------------------------
# URL NORMALIZATION
# -----------------------------------------------------

def canonical_url(url):
    """Normalize URLs for deduplication."""

    parsed = urlsplit(str(url or "").strip())

    if parsed.scheme not in {"http", "https"}:
        return ""

    if not parsed.hostname:
        return ""

    hostname = parsed.hostname.lower()

    # Remove tracking parameters from PubMed URLs.
    if hostname in {
        "pubmed.ncbi.nlm.nih.gov",
        "www.pubmed.ncbi.nlm.nih.gov",
    }:
        match = re.match(r"^/(\d+)/?", parsed.path)

        if match:
            return (
                "https://pubmed.ncbi.nlm.nih.gov/"
                f"{match.group(1)}/"
            )

    return urlunsplit((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path,
        parsed.query,
        "",
    ))


# -----------------------------------------------------
# HISTORY
# -----------------------------------------------------

def load_history():
    """Load newsletter state."""

    if not HISTORY_FILE.exists():
        return {
            "active_draft_id": None,
            "articles": [],
            "sent_article_urls": [],
        }

    history = json.loads(
        HISTORY_FILE.read_text(encoding="utf-8")
    )

    history.setdefault("active_draft_id", None)
    history.setdefault("articles", [])
    history.setdefault("sent_article_urls", [])

    return history


def save_history(history):
    """Save newsletter state for subsequent runs."""

    HISTORY_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    HISTORY_FILE.write_text(
        json.dumps(
            history,
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )


# -----------------------------------------------------
# ARTICLE COLLECTION
# -----------------------------------------------------

def collect_articles(history, feed):
    """Collect distinct articles excluding previously sent ones."""

    sent_urls = {
        canonical_url(url)
        for url in history["sent_article_urls"]
    }

    articles = {}

    candidates = (
        history["articles"]
        + feed.get("articles", [])
    )

    for item in candidates:

        if not isinstance(item, dict):
            continue

        url = canonical_url(item.get("url"))

        if not url:
            continue

        if url in sent_urls:
            continue

        if not item.get("title") or not item.get("summary"):
            continue

        if url in articles:
            continue

        article = dict(item)
        article["url"] = url

        is_paper = (
            article.get("content_type") == "paper"
            or (
                not article.get("content_type")
                and "pubmed" in
                article.get("source", "").lower()
            )
        )

        article["content_type"] = (
            "paper" if is_paper else "news"
        )

        articles[url] = article

    return list(articles.values())


# -----------------------------------------------------
# NEWSLETTER FORMATTING
# -----------------------------------------------------

def make_body(articles):
    """Generate a clean, structured Markdown newsletter."""

    lines = [
        "Your curated digest of proton therapy, "
        "radiation oncology, medical physics, "
        "and related research.",
        "",
        "---",
        "",
    ]

    for kind, heading in (
        ("news", "News & Developments"),
        ("paper", "Research & Publications"),
    ):

        stories = sorted(
            (
                a for a in articles
                if a["content_type"] == kind
            ),
            key=lambda a: a.get(
                "published_date", ""
            ),
            reverse=True,
        )

        if not stories:
            continue

        lines.extend([
            f"## {heading}",
            "",
        ])

        for story in stories:

            title = " ".join(
                str(story["title"]).split()
            )

            source = story.get("source", "")
            date = story.get("published_date", "")

            lines.extend([
                f"### {title}",
                "",
                f"*{source} | {date}*",
                "",
                str(story["summary"]).strip(),
                "",
                (
                    "[Read original article]"
                    f"({story['url']})"
                ),
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

    return (
        "<!-- buttondown-editor-mode: plaintext -->\n"
        + "\n".join(lines)
    )


# -----------------------------------------------------
# BUTTONDOWN
# -----------------------------------------------------

def get_email(session, email_id):
    """Retrieve an existing Buttondown email."""

    response = session.get(
        f"{API_URL}/{email_id}",
        timeout=30,
    )

    response.raise_for_status()

    return response.json()


def update_draft(session, draft_id, body):
    """Update an existing draft."""

    response = session.patch(
        f"{API_URL}/{draft_id}",
        json={"body": body},
        timeout=30,
    )

    response.raise_for_status()

    print("Updated existing draft:", draft_id)


def create_draft(session, body):
    """Create a draft without sending it."""

    response = session.post(
        API_URL,
        json={
            "subject": (
                "Proton Therapy News & Research Digest"
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
            "Buttondown did not return a draft ID."
        )

    print("Created new draft:", draft_id)

    return draft_id


# -----------------------------------------------------
# MAIN
# -----------------------------------------------------

def main():

    api_key = os.environ.get("BUTTONDOWN_API_KEY")

    if not api_key:
        raise RuntimeError(
            "BUTTONDOWN_API_KEY is missing"
        )

    feed = json.loads(
        NEWS_FILE.read_text(encoding="utf-8")
    )

    history = load_history()

    session = requests.Session()

    session.headers.update({
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    })

    draft_id = history["active_draft_id"]

    # -------------------------------------------------
    # CHECK EXISTING EMAIL STATUS
    # -------------------------------------------------

    if draft_id:

        email = get_email(session, draft_id)

        status = email.get("status")

        print("Existing email:", draft_id)
        print("Buttondown status:", status)

        if status == "sent":

            print(
                "Previous newsletter has been sent. "
                "Archiving its articles."
            )

            sent_urls = set(
                history["sent_article_urls"]
            )

            for article in history["articles"]:

                url = canonical_url(
                    article.get("url")
                )

                if url:
                    sent_urls.add(url)

            history["sent_article_urls"] = sorted(
                sent_urls
            )

            history["articles"] = []
            history["active_draft_id"] = None

            # Save immediately to record the sent issue.
            save_history(history)

            draft_id = None

        elif status != "draft":

            raise RuntimeError(
                f"Email {draft_id} has status "
                f"{status!r}. No changes made."
            )

    # -------------------------------------------------
    # COLLECT UNSENT ARTICLES
    # -------------------------------------------------

    articles = collect_articles(
        history,
        feed,
    )

    if not articles:

        print(
            "No unsent articles available. "
            "No draft created."
        )

        save_history(history)

        return

    body = make_body(articles)

    # -------------------------------------------------
    # CREATE OR UPDATE DRAFT
    # -------------------------------------------------

    if draft_id:

        email = get_email(session, draft_id)

        if email.get("status") != "draft":
            raise RuntimeError(
                "Email status changed during update. "
                "No changes made."
            )

        if email.get("body") == body:

            print(
                "Draft is already up to date."
            )

        else:

            update_draft(
                session,
                draft_id,
                body,
            )

    else:

        draft_id = create_draft(
            session,
            body,
        )

    # -------------------------------------------------
    # SAVE CURRENT STATE
    # -------------------------------------------------

    history["active_draft_id"] = draft_id
    history["articles"] = articles

    save_history(history)

    print(
        f"Stored {len(articles)} unsent articles."
    )

    print(
        f"Previously sent articles: "
        f"{len(history['sent_article_urls'])}"
    )

    print("No emails were sent automatically.")


if __name__ == "__main__":
    main()
