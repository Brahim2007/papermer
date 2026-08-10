"""Small diagnostic client for the X/Twitter API.

Credentials must be provided through environment variables.  This script is
not imported by Django and is retained only as an optional diagnostic tool.
"""

from __future__ import annotations

import os
import sys

import requests


def main() -> int:
    bearer = os.getenv("TWITTER_BEARER")
    if not bearer:
        print("TWITTER_BEARER is not configured.", file=sys.stderr)
        return 2

    query = os.getenv("TWITTER_QUERY", '"Proximal Algorithms"')
    response = requests.get(
        "https://api.twitter.com/2/tweets/search/recent",
        headers={"Authorization": f"Bearer {bearer}"},
        params={"query": query, "max_results": 10},
        timeout=20,
    )
    response.raise_for_status()
    for tweet in response.json().get("data", []):
        print(tweet["id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
