"""Push a notification via ntfy.sh (https://ntfy.sh) — no account or API key required.

Subscribe the ntfy phone app to your topic name, and this POSTs an alert to it with a
one-tap "Book now" action linking straight to the seat page.
"""

import requests


def notify(topic, title, message, click_url):
    # HTTP header values must be latin-1; strip anything that isn't (e.g. emoji).
    # Emoji still show via the ASCII `Tags` field. The message BODY is UTF-8, so
    # rich text/emoji belong there, not in headers.
    def h(v):
        return v.encode("latin-1", "ignore").decode("latin-1")

    requests.post(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers={
            "Title": h(title),
            "Priority": "high",
            "Tags": "clapper,fire",
            "Click": h(click_url),
            "Actions": h(f"view, Book now, {click_url}"),
        },
        timeout=15,
    )
