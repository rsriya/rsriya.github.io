"""Create and continuously update a Buttondown welcome draft.

The welcome draft always contains the current articles in
data/news.json, rather than accumulating historical articles.

If the previously tracked welcome email has been sent,
a fresh draft is created for future use.

This script NEVER sends emails.
"""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

# Fix SSL certificate issues on Windows/Miniconda.
if os.name == "nt":
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass

import requests


ROOT = Path(__file__).resolve().parents[1]

NEWS_FILE = ROOT / "data" / "news.json"
STATE_FILE = ROOT / "data" / "welcome_draft.json"

API_URL = "https://api.buttondown.com/v1/emails"

SUBJECT = "Welcome to DMV Proton Therapy Collaborative"


# -----------------------------------------------------
# URL NORMALIZATION
# -----------------------------------------------------

def canonical_url(url):
    """Normalize article URLs for deduplication."""

    parsed = urlsplit(str(url or "").strip())

    if parsed.scheme not in {"http", "https"}:
        return ""

    if not parsed.hostname:
        return ""

    hostname = parsed.hostname.lower()

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
# STATE MANAGEMENT
# -----------------------------------------------------

def load_state():
    """Read the ID of the currently tracked welcome draft."""

    if not STATE_FILE.exists():
        return {"draft_id": None}

    state = json.loads(
        STATE_FILE.read_text(encoding="utf-8")
    )

    state.setdefault("draft_id", None)

    return state


def save_state(draft_id):
    """Save the current welcome draft ID."""

    STATE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    STATE_FILE.write_text(
        json.dumps(
            {"draft_id": draft_id},
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


# -----------------------------------------------------
# ARTICLE COLLECTION
# -----------------------------------------------------

def collect_articles(feed):
    """Collect all valid, distinct articles in news.json."""

    articles = {}

    for item in feed.get("articles", []):

        if not isinstance(item, dict):
            continue

        url = canonical_url(item.get("url"))

        if not url:
            continue

        if not item.get("title"):
            continue

        if not item.get("summary"):
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
# WELCOME EMAIL FORMATTING
# -----------------------------------------------------

def make_body(articles):
    """Generate the complete welcome email in Markdown."""

    lines = [
        "Welcome to the DMV Proton Therapy Collaborative!",
        "",
        "Thank you for subscribing.",
        "",
        "Our newsletter brings together developments in "
        "proton therapy, radiation oncology, medical physics, "
        "and related research.",
        "",
        "Below is our current collection of news and "
        "recently published research.",
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
                article
                for article in articles
                if article["content_type"] == kind
            ),
            key=lambda article: article.get(
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

            source = str(
                story.get("source") or ""
            ).strip()

            date = str(
                story.get("published_date") or ""
            ).strip()

            metadata = " | ".join(
                value
                for value in (source, date)
                if value
            )

            lines.extend([
                f"### {title}",
                "",
            ])

            if metadata:
                lines.extend([
                    f"*{metadata}*",
                    "",
                ])

            lines.extend([
                str(story["summary"]).strip(),
                "",
                f"[Read original article]({story['url']})",
                "",
                "---",
                "",
            ])

    lines.extend([
        "For the latest updates, visit our "
        "[news page](https://dmv-proton.org/news.html).",
        "",
        "Thank you for being part of our community.",
        "",
        "DMV Proton Therapy Collaborative",
    ])

    return (
        "<!-- buttondown-editor-mode: plaintext -->\n"
        + "\n".join(lines)
    )


# -----------------------------------------------------
# BUTTONDOWN API
# -----------------------------------------------------

def get_email(session, email_id):
    """Retrieve an existing Buttondown email."""

    response = session.get(
        f"{API_URL}/{email_id}",
        timeout=30,
    )

    response.raise_for_status()

    return response.json()


def create_draft(session, body):
    """Create a new welcome draft without sending it."""

    response = session.post(
        API_URL,
        json={
            "subject": SUBJECT,
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

    print("Created welcome draft:", draft_id)

    return draft_id


def update_draft(session, draft_id, body):
    """Replace the body of an existing welcome draft."""

    response = session.patch(
        f"{API_URL}/{draft_id}",
        json={
            "body": body,
        },
        timeout=30,
    )

    response.raise_for_status()

    print("Updated welcome draft:", draft_id)


# -----------------------------------------------------
# MAIN
# -----------------------------------------------------

def main():

    api_key = os.environ.get("BUTTONDOWN_API_KEY")

    if not api_key:
        raise RuntimeError(
            "BUTTONDOWN_API_KEY is missing."
        )

    if not NEWS_FILE.exists():
        raise FileNotFoundError(
            f"News feed not found: {NEWS_FILE}"
        )

    feed = json.loads(
        NEWS_FILE.read_text(encoding="utf-8")
    )

    articles = collect_articles(feed)

    print(
        f"Found {len(articles)} distinct articles "
        "in news.json."
    )

    # Do not replace an existing welcome email
    # with empty content.
    if not articles:
        print(
            "No valid articles found. "
            "Leaving the welcome draft unchanged."
        )
        return

    body = make_body(articles)

    state = load_state()
    draft_id = state.get("draft_id")

    session = requests.Session()

    session.headers.update({
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    })

    # -------------------------------------------------
    # CHECK EXISTING WELCOME EMAIL
    # -------------------------------------------------

    if draft_id:

        existing = get_email(
            session,
            draft_id,
        )

        status = existing.get("status")

        print("Tracked welcome email:", draft_id)
        print("Buttondown status:", status)

        if status == "draft":

            if existing.get("body") == body:
                print(
                    "Welcome draft is already up to date."
                )

            else:
                update_draft(
                    session,
                    draft_id,
                    body,
                )

            # Keep tracking the same draft.
            save_state(draft_id)

        elif status == "sent":

            print(
                "Previous welcome email was sent. "
                "Creating a new draft."
            )

            new_draft_id = create_draft(
                session,
                body,
            )

            save_state(new_draft_id)

        else:

            raise RuntimeError(
                f"Welcome email {draft_id} has "
                f"status {status!r}. "
                "No changes made."
            )

    else:

        # No previously tracked welcome draft.
        draft_id = create_draft(
            session,
            body,
        )

        save_state(draft_id)

    print(
        "Welcome draft contains "
        f"{len(articles)} articles."
    )

    print("No emails were sent automatically.")


if __name__ == "__main__":
    main()
