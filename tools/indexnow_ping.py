#!/usr/bin/env python3
"""Submit every URL of the live sitemap to IndexNow (Bing, Yandex, Seznam, Naver, …).

Run after a deploy that added or changed content pages:

    python3 tools/indexnow_ping.py --key <INDEXNOW_KEY> --site https://www.fund-data-converter.eu

The key must already be served at <site>/<key>.txt (env INDEXNOW_KEY on the service).
Standard library only, so it runs anywhere deploy.sh runs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from urllib.parse import urlsplit

ENDPOINT = "https://api.indexnow.org/indexnow"
# api.indexnow.org answers 403 to the default Python-urllib user agent.
USER_AGENT = "fund-data-converter-indexnow/1.0 (+https://www.fund-data-converter.eu)"


def sitemap_urls(site: str) -> list[str]:
    request = urllib.request.Request(f"{site}/sitemap.xml", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return re.findall(r"<loc>(.*?)</loc>", response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--key", required=True)
    parser.add_argument("--site", required=True, help="canonical origin, e.g. https://www.fund-data-converter.eu")
    args = parser.parse_args()
    site = args.site.rstrip("/")
    urls = sitemap_urls(site)
    if not urls:
        print("no URLs in the sitemap", file=sys.stderr)
        return 1
    payload = {
        "host": urlsplit(site).hostname,
        "key": args.key,
        "keyLocation": f"{site}/{args.key}.txt",
        "urlList": urls,
    }
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        print(f"IndexNow: HTTP {response.status} for {len(urls)} URLs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
