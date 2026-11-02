
import json
import os
from pathlib import Path
from datetime import datetime, timezone

import requests

ROOT = Path(__file__).resolve().parents[1]
NEWS_FILE = ROOT / "data" / "news.json"

API_KEY = os.environ["BUTTONDOWN_API_KEY"]

with NEWS_FILE.open(encoding="utf-8") as f:
    news = json.load(f)

articles = news.get("articles", [])

# Use up to 6 articles for the first test.
articles = articles[:6]

today = datetime.now(timezone.utc).date()

body = [
    "# DMV Proton Therapy Collaborative",
    "",
    "A curated selection of news and research "
    "in proton therapy, radiation oncology, "
    "and medical physics.",
    "",
]

for article in articles:
    body.extend([
        f"## {article['title']}",
        "",
        article["summary"],
        "",
        f"[Read original article]({article['url']})",
        "",
    ])

body.extend([
    "---",
    "",
    "This newsletter is provided by the "
    "DMV Proton Therapy Collaborative.",
])

payload = {
    "subject": f"DMV Proton Therapy News — {today}",
    "body": "\n".join(body),
    "status": "draft",
}

response = requests.post(
    "https://api.buttondown.com/v1/emails",
    headers={
        "Authorization": f"Token {API_KEY}",
        "Content-Type": "application/json",
    },
    json=payload,
    timeout=30,
)

response.raise_for_status()

print("Draft created successfully!")
print("Email ID:", response.json().get("id"))
