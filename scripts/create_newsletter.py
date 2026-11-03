"""Maintain one review-only Buttondown newsletter draft.

The current news.json supplies the three newest news stories and three newest
research papers. Re-running updates the existing unsent draft, not a new one.
No API call in this script sends, publishes, or schedules email.
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

# Optional fix for Miniconda/Windows trust-store certificate errors.
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
SUBJECT = "DMV Proton Therapy News — Draft"
MAX_NEWS = 3
MAX_RESEARCH = 3


def canonical_url(url):
    parsed = urlsplit(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.hostname.lower() in {"pubmed.ncbi.nlm.nih.gov", "www.pubmed.ncbi.nlm.nih.gov"}:
        match = re.match(r"^/(\d+)/?", parsed.path)
        if match:
            return f"https://pubmed.ncbi.nlm.nih.gov/{match.group(1)}/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, ""))


def select_articles(articles):
    """Pick latest distinct stories; replace older stories as the feed changes."""
    news, research, seen = [], [], set()
    for article in sorted(articles, key=lambda a: a.get("published_date", ""), reverse=True):
        url = canonical_url(article.get("url"))
        if not url or url in seen or not article.get("title") or not article.get("summary"):
            continue
        is_paper = article.get("content_type") == "paper" or (
            not article.get("content_type") and "pubmed" in article.get("source", "").lower()
        )
        bucket, limit = (research, MAX_RESEARCH) if is_paper else (news, MAX_NEWS)
        if len(bucket) >= limit:
            continue
        bucket.append({**article, "url": url})
        seen.add(url)
    return news, research


def make_body(news, research):
    lines = [
        "# DMV Proton Therapy Collaborative",
        "",
        "Curated news and research in proton therapy, radiation oncology, and medical physics.",
        "",
    ]
    for heading, items in (("News & Developments", news), ("Research & Publications", research)):
        if not items:
            continue
        lines.extend([f"## {heading}", ""])
        for article in items:
            lines.extend([
                f"### {article['title'].replace(chr(10), ' ')}", "",
                article["summary"].strip(), "",
                f"[Read original article]({article['url']})", "",
            ])
    lines.extend(["---", "", "DMV Proton Therapy Collaborative"])
    return "\n".join(lines)


def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return {"drafted_article_urls": [], "drafts": []}


def main():
    feed = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    news, research = select_articles(feed.get("articles", []))
    selected_urls = sorted(a["url"] for a in news + research)
    if not selected_urls:
        print("News feed has no usable articles; existing draft left unchanged.")
        return
    body = make_body(news, research)
    print(f"Selected {len(news)} news stories and {len(research)} research papers.")

    api_key = os.getenv("BUTTONDOWN_API_KEY")
    if not api_key:
        raise RuntimeError("Set BUTTONDOWN_API_KEY before running")

    session = requests.Session()
    session.headers.update({
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    })
    history = load_history()

    # Migrate existing history: use the newest of the two previously created
    # drafts as the single active draft. Older drafts are left untouched.
    draft_id = history.get("active_draft_id")
    if not draft_id and history.get("drafts"):
        draft_id = history["drafts"][-1].get("buttondown_email_id")

    changed_remote = False
    if draft_id:
        response = session.get(f"{API_URL}/{draft_id}", timeout=30)
        response.raise_for_status()
        remote = response.json()
        status = remote.get("status")
        if status == "draft":
            if remote.get("body", "").strip() == body.strip() and remote.get("subject") == SUBJECT:
                print(f"Draft {draft_id} is already up to date. No changes made.")
            else:
                response = session.patch(
                    f"{API_URL}/{draft_id}",
                    json={"subject": SUBJECT, "body": body},
                    timeout=30,
                )
                response.raise_for_status()
                changed_remote = True
                print(f"Updated existing Buttondown draft: {draft_id}")
        elif status == "sent":
            # No automatic new issue on the same invocation. This prevents
            # accidentally drafting another issue using already sent stories.
            print(f"Previously active newsletter {draft_id} was sent.")
            print("No new draft created. Start the next issue explicitly after resetting active_draft_id.")
            return
        else:
            print(f"Active email {draft_id} has status {status!r}, not 'draft'.")
            print("For safety, no email was changed and no new draft was created.")
            return
    else:
        response = session.post(
            API_URL,
            json={"subject": SUBJECT, "body": body, "status": "draft"},
            timeout=30,
        )
        response.raise_for_status()
        draft_id = response.json().get("id")
        if not draft_id:
            raise RuntimeError("Buttondown did not return a new draft ID")
        changed_remote = True
        print(f"Created first Buttondown draft: {draft_id}")

    history_changed = (
        history.get("active_draft_id") != draft_id
        or history.get("active_article_urls") != selected_urls
    )
    if not history_changed and not changed_remote:
        print("Newsletter history is also up to date.")
        return
    history["active_draft_id"] = draft_id
    history["active_article_urls"] = selected_urls
    history["active_last_updated_at"] = datetime.now(timezone.utc).isoformat()
    # Preserve historical entries for auditing, without counting them as sent.
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("Saved current draft details. Nothing was sent.")


if __name__ == "__main__":
    main()
