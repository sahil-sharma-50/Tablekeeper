#!/usr/bin/env python3
"""Check the Stage 3 UI bundles and fonts from the app origin using stdlib HTTP."""
from __future__ import annotations

import re
import sys
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen


base = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8080"
origin = urlparse(base).netloc
external: set[str] = set()
fonts: set[str] = set()
css_urls: set[str] = set()


def get(path: str) -> tuple[bytes, str]:
    url = urljoin(base + "/", path)
    parsed = urlparse(url)
    assert parsed.netloc == origin, f"cross-origin asset: {url}"
    with urlopen(url, timeout=3) as response:
        body = response.read()
        print(f"HTTP {response.status} {response.headers.get('Content-Type')} {parsed.path} {len(body)}")
        assert response.status == 200
        return body, response.headers.get("Content-Type", "")


html, _ = get("/")
refs = re.findall(r'(?:src|href)="([^"]+)"', html.decode())
assert refs, "index has no JS/CSS bundle references"
for ref in refs:
    if ref.startswith("/assets/"):
        body, content_type = get(ref)
        if ref.endswith(".css") or "text/css" in content_type:
            css_urls.add(ref)
            for raw in re.findall(r"url\(([^)]+)\)", body.decode(errors="replace")):
                asset = raw.strip(" \"'")
                url = urljoin(base + "/", asset)
                if urlparse(url).netloc != origin:
                    external.add(url)
                elif urlparse(url).path.startswith("/assets/"):
                    get(urlparse(url).path)
                    if urlparse(url).path.lower().endswith((".woff", ".woff2", ".ttf", ".otf")):
                        fonts.add(urlparse(url).path)

assert css_urls, "index did not load a stylesheet"
assert fonts, "no bundled font was referenced by the stylesheet"
assert not external, f"stylesheet has external resources: {sorted(external)}"
print(f"PASS same-origin UI bundles and bundled fonts; css={len(css_urls)} fonts={sorted(fonts)} external={sorted(external)}")
