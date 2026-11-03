
"""Send the latest published newsletter to new subscribers.

Buttondown handles both subscriptions and email delivery.

Modes:
    check - Show eligible subscriber count without sending.
    send  - Send latest published newsletter individually.

The script:
- Only processes confirmed subscribers.
- Never sends draft emails.
- Never broadcasts to the full subscriber list.
- Records delivery state in Buttondown subscriber metadata.
- Does not repeat an attempted welcome automatically.

Required environment:
    BUTTONDOWN_API_KEY

Optional environment:
    WELCOME_MODE=check
    WELCOME_MAX_SENDS=20
    WELCOME_EMAIL_ID=
"""

import os
from datetime import datetime, timezone
from urllib.parse import urlparse

if os.name == "nt":
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass

import requests


API = "https://api.buttondown.com/v1"
STATE_KEY = "dmv_welcome_delivery_v1"

MODE = os.getenv("WELCOME_MODE", "check").lower()
MAX_SENDS = int(os.getenv("WELCOME_MAX_SENDS", "20"))
EMAIL_OVERRIDE = os.getenv("WELCOME_EMAIL_ID", "").strip()

ACTIVE_TYPES = {
    "regular",
    "premium",
    "gifted",
    "trialed",
    "churning",
}

# Recognize regular newsletter subjects, not welcome emails.
NEWSLETTER_SUBJECT_TERMS = (
    "proton therapy",
    "research digest",
)


# --------------------------------------------------
# API HELPERS
# --------------------------------------------------

def request(session, method, url, **kwargs):
    response = session.request(
        method,
        url,
        timeout=30,
        **kwargs,
    )
    response.raise_for_status()
    return response


def list_all(session, endpoint, params=None):
    """Retrieve every page from a Buttondown endpoint."""

    url = f"{API}/{endpoint}"
    results = []
    visited = set()

    while url:
        if url in visited:
            raise RuntimeError("Pagination loop detected.")

        visited.add(url)

        response = request(
            session,
            "GET",
            url,
            params=params,
        )

        data = response.json()
        results.extend(data.get("results", []))

        next_url = data.get("next")

        if next_url:
            parsed = urlparse(next_url)

            if (
                parsed.scheme != "https"
                or parsed.hostname != "api.buttondown.com"
                or not parsed.path.startswith("/v1/")
            ):
                raise RuntimeError(
                    "Unsafe pagination URL returned."
                )

        url = next_url
        params = None

    return results


# --------------------------------------------------
# FIND LATEST PUBLISHED NEWSLETTER
# --------------------------------------------------

def newsletter_matches(email):
    """Exclude welcome emails and unrelated publications."""

    subject = str(email.get("subject") or "").lower()

    if "welcome" in subject:
        return False

    return any(
        term in subject
        for term in NEWSLETTER_SUBJECT_TERMS
    )


def latest_newsletter(session):
    """Find most recently published regular newsletter."""

    if EMAIL_OVERRIDE:
        response = request(
            session,
            "GET",
            f"{API}/emails/{EMAIL_OVERRIDE}",
        )

        email = response.json()

        if email.get("status") != "sent":
            raise RuntimeError(
                "Configured email is not sent."
            )

        if not newsletter_matches(email):
            raise RuntimeError(
                "Configured email does not match "
                "the regular newsletter subject."
            )

        return email

    emails = list_all(
        session,
        "emails",
        params={"status": "sent"},
    )

    candidates = [
        email
        for email in emails
        if (
            email.get("status") == "sent"
            and newsletter_matches(email)
        )
    ]

    if not candidates:
        raise RuntimeError(
            "No published regular newsletter found."
        )

    candidates.sort(
        key=lambda email: (
            email.get("publish_date") or "",
            email.get("creation_date") or "",
        ),
        reverse=True,
    )

    return candidates[0]


# --------------------------------------------------
# SUBSCRIBERS
# --------------------------------------------------

def confirmed(subscriber):
    """Check whether the subscription is active."""

    return subscriber.get("type") in ACTIVE_TYPES


def delivery_state(subscriber):
    metadata = subscriber.get("metadata") or {}
    return metadata.get(STATE_KEY)


def update_state(session, subscriber, status, email_id):
    """Save delivery state privately in Buttondown."""

    subscriber_id = subscriber["id"]

    # Merge with existing subscriber metadata.
    metadata = dict(subscriber.get("metadata") or {})

    metadata[STATE_KEY] = {
        "status": status,
        "email_id": email_id,
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    response = request(
        session,
        "PATCH",
        f"{API}/subscribers/{subscriber_id}",
        json={"metadata": metadata},
    )

    updated = response.json()
    saved_metadata = updated.get("metadata") or {}
    saved_state = saved_metadata.get(STATE_KEY)

    if not isinstance(saved_state, dict):
        raise RuntimeError(
            "Buttondown did not save delivery state."
        )

    if saved_state.get("status") != status:
        raise RuntimeError(
            "Delivery state verification failed."
        )

    subscriber["metadata"] = saved_metadata


# --------------------------------------------------
# SEND INDIVIDUALLY
# --------------------------------------------------


def send_to_subscriber(session, subscriber_id, email_id):
    """Send one published newsletter to one subscriber."""

    url = (
        f"{API}/subscribers/{subscriber_id}"
        f"/emails/{email_id}"
    )

    response = session.post(
        url,
        timeout=30,
    )

    if not response.ok:
        print("Buttondown HTTP status:", response.status_code)

        try:
            error = response.json()
            print("Buttondown error code:", error.get("code"))
            print("Buttondown error detail:", error.get("detail"))
        except ValueError:
            print("Buttondown returned a non-JSON error.")

        response.raise_for_status()

    return response.status_code


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    if MODE not in {"check", "send"}:
        raise ValueError(
            "WELCOME_MODE must be check or send."
        )

    if MAX_SENDS < 1:
        raise ValueError(
            "WELCOME_MAX_SENDS must be positive."
        )

    api_key = os.environ.get("BUTTONDOWN_API_KEY")

    if not api_key:
        raise RuntimeError(
            "BUTTONDOWN_API_KEY is missing."
        )

    session = requests.Session()

    session.headers.update({
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    })

    print("Welcome mode:", MODE)

    # 1. Retrieve subscribers.
    subscribers = list_all(
        session,
        "subscribers",
    )

    print("Total subscribers:", len(subscribers))

    # 2. Find confirmed subscribers not yet welcomed.
    eligible = [
        subscriber
        for subscriber in subscribers
        if (
            confirmed(subscriber)
            and delivery_state(subscriber) is None
        )
    ]

    print("Eligible new subscribers:", len(eligible))

    # 3. Nothing to do if everyone has been processed.
    if not eligible:
        print("No welcome emails needed.")
        return

    # 4. Find latest published newsletter.
    email = latest_newsletter(session)

    email_id = email["id"]

    print("Latest published newsletter:")
    print("  ID:", email_id)
    print("  Subject:", email.get("subject"))
    print("  Published:", email.get("publish_date"))

    # 5. Check-only mode.
    if MODE == "check":
        print("CHECK MODE: Nothing was sent.")
        return

    # 6. Send individually, with a per-run limit.
    accepted = 0

    for subscriber in eligible[:MAX_SENDS]:
        subscriber_id = subscriber["id"]

        print("Processing subscriber:", subscriber_id)

        # Mark intent before sending.
        #
        # If the network fails after Buttondown accepts
        # a send request, the next run will NOT resend.
        # An attempted state requires manual review.
        update_state(
            session,
            subscriber,
            status="attempted",
            email_id=email_id,
        )

        try:
            status_code = send_to_subscriber(
                session,
                subscriber_id,
                email_id,
            )

        except requests.RequestException:
            print(
                "Send failed or its outcome is uncertain. "
                "Subscriber remains marked as attempted."
            )
            raise

        print("Send request HTTP status:", status_code)

        # Record that Buttondown accepted the send.
        update_state(
            session,
            subscriber,
            status="sent",
            email_id=email_id,
        )

        accepted += 1

    print("Welcome sends accepted:", accepted)
    print("No broadcast was initiated.")

    remaining = max(
        0,
        len(eligible) - accepted,
    )

    print("Subscribers remaining:", remaining)


if __name__ == "__main__":
    main()
