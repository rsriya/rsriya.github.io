"""Rebuild a single Buttondown draft from its existing articles plus news.json.

Safety: update drafts only; never send emails. Existing stories are recovered
from the Buttondown draft before rebuilding, so they do not disappear when
news.json rotates. No cap on the article count.
"""

import json
import os
import re
from datetime import datetime, timezone
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
HISTORY_FILE = ROOT / "data" / "newsletter_history.json"
API = "https://api.buttondown.com/v1/emails"


def canonical_url(url):
    p = urlsplit(str(url or "").strip())
    if p.scheme not in ("http", "https") or not p.hostname:
        return ""
    if p.hostname.lower() in ("pubmed.ncbi.nlm.nih.gov", "www.pubmed.ncbi.nlm.nih.gov"):
        m = re.match(r"^/(\d+)/?", p.path)
        if m:
            return f"https://pubmed.ncbi.nlm.nih.gov/{m.group(1)}/"
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, p.query, ""))


def event_key(item):
    """Identify identical titles and the known C-FLASH first-patient event."""
    title = item["title"].lower()
    condensed = re.sub(r"[^a-z0-9]+", "", title)
    if ("cflash01" in condensed or "conformalflash" in condensed) and (
        "firstpatient" in condensed or "patienttreated" in condensed or "treatsfirstpatient" in condensed
    ):
        return "event:cflash01-first-patient"
    return "title:" + condensed


def parse_existing_body(body):
    """Recover all Markdown article blocks from earlier append-style drafts."""
    if not isinstance(body, str):
        raise RuntimeError("Buttondown did not return a readable Markdown body.")

    current_type = None
    recovered = []
    lines = body.splitlines()
    headings_seen = 0
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line == "## News & Developments":
            current_type = "news"
            i += 1
            continue
        if line == "## Research & Publications":
            current_type = "paper"
            i += 1
            continue
        if not line.startswith("### "):
            i += 1
            continue

        headings_seen += 1
        title = line[4:].strip()
        i += 1
        content = []
        while i < len(lines) and not lines[i].strip().startswith(("### ", "## ")):
            content.append(lines[i].strip())
            i += 1

        chunk = "\n".join(content)
        links = re.findall(r"\[Read (?:the )?original(?: article)?\]\((https?://[^\s)]+)\)", chunk, re.I)
        if not links or current_type is None:
            raise RuntimeError(f"Could not safely recover article: {title!r}. Draft unchanged.")
        url = canonical_url(links[-1])
        if not url:
            raise RuntimeError(f"Invalid article URL in existing draft: {title!r}")
        summary = re.sub(
            r"\[Read (?:the )?original(?: article)?\]\(https?://[^\s)]+\)", "", chunk, flags=re.I
        ).strip()
        recovered.append({
            "title": title,
            "summary": summary,
            "url": url,
            "content_type": current_type,
            "published_date": "",
        })

    if body.strip() and headings_seen != len(recovered):
        raise RuntimeError("Draft parsing was incomplete. No changes made.")
    if body.strip() and not recovered:
        raise RuntimeError("Existing draft has content but no recoverable article blocks. No changes made.")
    return recovered


def distinct_articles(old, latest):
    by_url = {}
    ordered = []
    for item in old + latest:
        url = canonical_url(item.get("url"))
        if not url or not item.get("title") or not item.get("summary"):
            continue
        current = dict(item)
        current["url"] = url
        if current.get("content_type") not in ("paper", "news"):
            current["content_type"] = "paper" if "pubmed" in current.get("source", "").lower() else "news"
        if url not in by_url:
            by_url[url] = current
            ordered.append(url)
        else:
            # Keep the existing draft text, but recover publication date when available.
            if not by_url[url].get("published_date"):
                by_url[url]["published_date"] = current.get("published_date", "")

    result = []
    seen_events = set()
    for url in ordered:
        item = by_url[url]
        key = event_key(item)
        if key in seen_events:
            continue
        seen_events.add(key)
        result.append(item)
    return result


def render(articles):
    parts = [
        "# DMV Proton Therapy Collaborative",
        "",
        "Curated news and research in proton therapy, radiation oncology, and medical physics.",
        "",
    ]
    for heading, kind in (("News & Developments", "news"), ("Research & Publications", "paper")):
        items = [a for a in articles if a["content_type"] == kind]
        items.sort(key=lambda a: a.get("published_date") or "", reverse=True)
        if not items:
            continue
        parts.extend([f"## {heading}", ""])
        for a in items:
            parts.extend([
                "### " + a["title"].replace("\n", " ").strip(), "",
                a["summary"].strip(), "",
                f"[Read original article]({a['url']})", "",
            ])
    parts.extend(["---", "", "DMV Proton Therapy Collaborative", ""])
    return "\n".join(parts)


def main():
    token = os.environ.get("BUTTONDOWN_API_KEY")
    if not token:
        raise RuntimeError("BUTTONDOWN_API_KEY is missing")
    if not HISTORY_FILE.exists():
        raise RuntimeError("Newsletter history is missing. Refusing to create a new draft.")
    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    draft_id = history.get("active_draft_id") or next(
        (x.get("buttondown_email_id") for x in reversed(history.get("drafts", [])) if x.get("buttondown_email_id")),
        None,
    )
    if not draft_id:
        raise RuntimeError("No existing Buttondown draft ID in history; no changes made.")

    session = requests.Session()
    session.headers.update({"Authorization": f"Token {token}", "Content-Type": "application/json"})
    response = session.get(f"{API}/{draft_id}", timeout=30)
    response.raise_for_status()
    remote = response.json()
    if remote.get("status") != "draft":
        raise RuntimeError(f"Email {draft_id} status is {remote.get('status')!r}, not draft. Nothing modified.")

    old = parse_existing_body(remote.get("body"))
    feed = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    articles = distinct_articles(old, feed.get("articles", []))
    new_body = render(articles)
    print(f"Recovered {len(old)} existing article blocks; rebuilt {len(articles)} distinct articles.")
    print(f"News: {sum(a['content_type']=='news' for a in articles)}; Research: {sum(a['content_type']=='paper' for a in articles)}")

    if new_body != remote["body"]:
        patched = session.patch(f"{API}/{draft_id}", json={"body": new_body}, timeout=30)
        patched.raise_for_status()
        print("Updated existing draft:", draft_id)
    else:
        print("Draft already up to date:", draft_id)

    history["active_draft_id"] = draft_id
    history["active_article_urls"] = sorted({a["url"] for a in articles})
    history["last_rebuilt_at"] = datetime.now(timezone.utc).isoformat()
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("No email was sent.")


if __name__ == "__main__":
    main()
