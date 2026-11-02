"""Make a review-only Buttondown draft from distinct, previously undrafted news."""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

# Work around Windows/Miniconda CA-store issues without disabling TLS verification.
if os.name == "nt":
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass

import requests

ROOT = Path(__file__).resolve().parents[1]
NEWS_FILE = ROOT / "data/news.json"
HISTORY_FILE = ROOT / "data/newsletter_history.json"
API_URL = "https://api.buttondown.com/v1/emails"
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


def select_articles(articles, excluded):
    selected_news, selected_research = [], []
    seen = set(excluded)
    for article in sorted(articles, key=lambda a: a.get("published_date", ""), reverse=True):
        url = canonical_url(article.get("url"))
        if not url or url in seen or not article.get("title") or not article.get("summary"):
            continue
        is_research = article.get("content_type") == "paper" or (
            not article.get("content_type") and "pubmed" in article.get("source", "").lower()
        )
        output, cap = (selected_research, MAX_RESEARCH) if is_research else (selected_news, MAX_NEWS)
        if len(output) >= cap:
            continue
        output.append({**article, "url": url})
        seen.add(url)
    return selected_news, selected_research


def make_body(news, research):
    parts = ["# DMV Proton Therapy Collaborative", "", "Curated news and research in proton therapy, radiation oncology, and medical physics.", ""]
    for heading, entries in [("News & Developments", news), ("Research & Publications", research)]:
        if not entries:
            continue
        parts.extend([f"## {heading}", ""])
        for article in entries:
            parts.extend([
                f"### {article['title'].replace(chr(10), ' ')}", "",
                article["summary"], "",
                f"[Read original article]({article['url']})", "",
            ])
    parts.extend(["---", "", "DMV Proton Therapy Collaborative"])
    return "\n".join(parts)


def matching_draft(session, subject):
    # Consult Buttondown in case a draft was created but history wasn't saved.
    page = 1
    while True:
        response = session.get(API_URL, params={"status": "draft", "subject": subject, "page": page}, timeout=30)
        response.raise_for_status()
        result = response.json()
        for email in result.get("results", []):
            if email.get("subject") == subject:
                return email.get("id")
        if not result.get("next") or not result.get("results"):
            return None
        page += 1


def main():
    content = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else {"drafted_article_urls": [], "drafts": []}
    excluded = {canonical_url(u) for u in history.get("drafted_article_urls", [])}
    news, research = select_articles(content.get("articles", []), excluded)
    chosen = news + research
    if not chosen:
        print("No unseen articles. No draft created.")
        return

    keys = sorted(a["url"] for a in chosen)
    digest_id = hashlib.sha256("\n".join(keys).encode()).hexdigest()[:12]
    subject = f"DMV Proton Therapy News [digest:{digest_id}]"
    print(f"Selected {len(news)} news stories and {len(research)} research papers")
    print("Draft subject:", subject)

    api_key = os.getenv("BUTTONDOWN_API_KEY")
    if not api_key:
        raise RuntimeError("Set BUTTONDOWN_API_KEY before running")
    session = requests.Session()
    session.headers.update({"Authorization": f"Token {api_key}", "Content-Type": "application/json"})

    draft_id = matching_draft(session, subject)
    if draft_id:
        print("Matching Buttondown draft already exists:", draft_id)
    else:
        response = session.post(API_URL, json={"subject": subject, "body": make_body(news, research), "status": "draft"}, timeout=30)
        response.raise_for_status()
        draft_id = response.json().get("id")
        if not draft_id:
            raise RuntimeError("Buttondown did not provide a draft ID")
        print("Created Buttondown draft:", draft_id)

    history["drafted_article_urls"] = sorted(excluded | set(keys))
    drafts = history.setdefault("drafts", [])
    if not any(d.get("digest_id") == digest_id for d in drafts):
        drafts.append({"digest_id": digest_id, "buttondown_email_id": draft_id,
                       "created_at": datetime.now(timezone.utc).isoformat(),
                       "article_urls": keys})
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Recorded draft history (not sent).")


if __name__ == "__main__":
    main()
