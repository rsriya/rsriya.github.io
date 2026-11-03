"""Maintain one unsent Buttondown welcome draft from the current news.json.

This draft is independent of the regular newsletter and is NEVER sent by this script.
All valid articles currently in news.json are included, without a history-based cap.
"""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

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


def canonical_url(value):
    parsed = urlsplit(str(value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.hostname.lower() in {
        "pubmed.ncbi.nlm.nih.gov", "www.pubmed.ncbi.nlm.nih.gov"
    }:
        match = re.match(r"^/(\d+)/?", parsed.path)
        if match:
            return f"https://pubmed.ncbi.nlm.nih.gov/{match.group(1)}/"
    return urlunsplit((
        parsed.scheme.lower(), parsed.netloc.lower(), parsed.path,
        parsed.query, ""
    ))


def current_articles(feed):
    """Use only today's feed, not regular-newsletter history."""
    found = {}
    for item in feed.get("articles", []):
        if not isinstance(item, dict):
            continue
        url = canonical_url(item.get("url"))
        if not url or not item.get("title") or not item.get("summary"):
            continue
        if url in found:
            continue
        article = dict(item)
        article["url"] = url
        article["content_type"] = (
            "paper" if article.get("content_type") == "paper"
            or (not article.get("content_type") and
                "pubmed" in str(article.get("source", "")).lower())
            else "news"
        )
        found[url] = article
    return list(found.values())


def make_body(articles):
    lines = [
        "Welcome to the **DMV Proton Therapy Collaborative**!",
        "",
        "We're glad you're here. Below is our current selection of news and "
        "research in proton therapy, radiation oncology, medical physics, "
        "and related fields.",
        "",
        "This welcome digest reflects the articles featured on our news page "
        "at the time it was last updated.",
        "",
        "---", "",
    ]
    for kind, heading in (("news", "News & Developments"),
                          ("paper", "Research & Publications")):
        group = sorted(
            (item for item in articles if item["content_type"] == kind),
            key=lambda item: str(item.get("published_date") or ""),
            reverse=True,
        )
        if not group:
            continue
        lines.extend([f"## {heading}", ""])
        for item in group:
            title = " ".join(str(item["title"]).split())
            metadata = " | ".join(str(x).strip() for x in (
                item.get("source"), item.get("published_date")
            ) if x)
            lines.extend([f"### {title}", ""])
            if metadata:
                lines.extend([f"*{metadata}*", ""])
            lines.extend([
                str(item["summary"]).strip(), "",
                f"[Read original article]({item['url']})", "",
                "---", "",
            ])
    lines.extend([
        "For the latest updates, visit our "
        "[news page](https://dmv-proton.org/news.html).", "",
        "DMV Proton Therapy Collaborative", "",
    ])
    return "<!-- buttondown-editor-mode: plaintext -->\n" + "\n".join(lines)


def main():
    api_key = os.environ.get("BUTTONDOWN_API_KEY")
    if not api_key:
        raise RuntimeError("BUTTONDOWN_API_KEY is missing")

    feed = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    articles = current_articles(feed)
    if not articles:
        print("No valid articles in news.json; welcome draft left unchanged.")
        return

    state = (json.loads(STATE_FILE.read_text(encoding="utf-8"))
             if STATE_FILE.exists() else {})
    draft_id = state.get("draft_id")
    body = make_body(articles)

    session = requests.Session()
    session.headers.update({"Authorization": f"Token {api_key}"})

    if draft_id:
        response = session.get(f"{API_URL}/{draft_id}", timeout=30)
        response.raise_for_status()
        existing = response.json()
        if existing.get("status") != "draft":
            raise RuntimeError(
                f"Welcome email {draft_id} has status "
                f"{existing.get('status')!r}; refusing to change a non-draft. "
                "This draft must remain unsent."
            )
        if existing.get("body") == body:
            print("Welcome draft already matches news.json.")
        else:
            response = session.patch(
                f"{API_URL}/{draft_id}", json={"body": body}, timeout=30
            )
            response.raise_for_status()
            print("Updated welcome draft:", draft_id)
    else:
        response = session.post(API_URL, json={
            "subject": SUBJECT, "body": body, "status": "draft"
        }, timeout=30)
        response.raise_for_status()
        draft_id = response.json().get("id")
        if not draft_id:
            raise RuntimeError("Buttondown did not return a draft ID")
        print("Created welcome draft:", draft_id)

    state = {"draft_id": draft_id}
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Welcome draft contains {len(articles)} current articles. Nothing sent.")


if __name__ == "__main__":
    main()
