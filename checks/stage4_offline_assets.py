#!/usr/bin/env python3
"""Check a running Stage 4 image and its bundled page assets using stdlib only."""
from __future__ import annotations

import json
import re
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


BASE = "http://127.0.0.1:8080"


def fetch(path: str) -> tuple[bytes, float, str]:
    started = time.perf_counter()
    with urlopen(BASE + path, timeout=2) as response:
        body = response.read()
        return body, time.perf_counter() - started, response.headers.get_content_type()


def main() -> None:
    deadline = time.monotonic() + 60
    health_ms = None
    while time.monotonic() < deadline:
        try:
            body, elapsed, content_type = fetch("/health")
            if json.loads(body) == {"status": "ok"}:
                health_ms = round(elapsed * 1000, 1)
                break
        except (OSError, URLError, ValueError):
            time.sleep(0.1)
    assert health_ms is not None, "health did not become ready within 60 seconds"
    if sys.argv[1:] == ["--health-only"]:
        print(json.dumps({"health_first_probe_ms": health_ms}))
        return

    html, _, _ = fetch("/")
    text = html.decode("utf-8")
    refs = re.findall(r"(?:src|href)=\"([^\"]+)\"", text)
    local = {ref.split("?", 1)[0] for ref in refs
             if ref.startswith("/assets/")}
    external = [ref for ref in refs
                if re.match(r"https?://", ref, flags=re.IGNORECASE)]
    assert local, "root document did not link any bundled assets"

    checked: dict[str, dict[str, object]] = {}
    for path in sorted(local):
        asset, elapsed, content_type = fetch(path)
        checked[path] = {"bytes": len(asset), "content_type": content_type,
                         "elapsed_ms": round(elapsed * 1000, 1)}
        if path.endswith(".css"):
            css = asset.decode("utf-8")
            urls = re.findall(r"url\((?:\"|')?([^\"')]+)", css)
            for ref in urls:
                if ref.startswith("data:"):
                    continue
                if re.match(r"https?://", ref, flags=re.IGNORECASE):
                    external.append(ref)
                    continue
                asset_path = ref if ref.startswith("/") else "/assets/" + ref
                if asset_path not in checked:
                    font, font_elapsed, font_type = fetch(asset_path)
                    checked[asset_path] = {"bytes": len(font),
                                           "content_type": font_type,
                                           "elapsed_ms": round(font_elapsed * 1000, 1)}
    assert not external, f"external runtime assets: {external}"
    assert any(".woff" in path for path in checked), "bundled font was not referenced"
    assert all(item["bytes"] > 0 for item in checked.values())

    result = {"health_first_probe_ms": health_ms,
              "local_assets": checked,
              "external_asset_refs": external,
              "network_mode_required": "none"}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
