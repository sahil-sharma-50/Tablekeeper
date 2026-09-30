# Independent native 200% browser zoom recheck

- Application commit: `64d0f501f733f773c3357092c6ea5676b90512d0`
- Parent: `d3ee94018d6dca65f23d0361139c741253d86b28`
- Backend ancestor: `afdb3dc0a0eeca44583fe456186618de78525aca`
- Docker image: `sha256:3454d6cb9cd4438a6b2fbbd6660e3738c3a7048868ccc789d6f22e628e134de7`
- Chromium: `151.0.7922.34`, headless with extension support
- Run time: 2026-09-30 18:10 UTC; 24 viewport/theme/page scenarios completed in about 6 seconds.

## Method

Launched a Playwright persistent Chromium context with a fresh QA-only profile and temporary Manifest V3 extension. The extension called `chrome.tabs.setZoom(tabId, 2)` and then `chrome.tabs.getZoom(tabId)`. Every one of the 24 scenarios returned `2`. This was native browser tab zoom; no CSS zoom, device scale factor override, or viewport-only proxy was used.

The application ran from the exact Stage 2 image above in a new disposable container with 2 CPU and 2 GiB limits. Only that QA container received the opt-in seven-day demo fixture and synthetic account. The other preview/test containers and the user's browser profile were untouched. The temporary extension and profile were isolated to the QA run and removed after capture.

Commands used:

```powershell
docker run --detach --name tk4-qa-s2-zoom --cpus=2 --memory=2g --publish 127.0.0.1:18086:8080 tablekeeper-s2-64d0f50:qa
$body = Get-Content -Raw stage-2\demo\multi-day-demo.json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:18086/_test/reset -ContentType 'application/json' -Body $body
node evidence\s2-64d0f50-01\.native-zoom-temp\probe-native-zoom.cjs
```

## Results

The check covered login failure (HTTP 401), duplicate signup (HTTP 409), signed-out reserve feedback, and signed-out lookup feedback at outer browser sizes 1280x720, 1366x768, and 1440x900, in light and dark themes. All 24 cases passed the required checks:

- `getZoom` returned `2` for every case. The CSS viewports were 640x360, 683x384, and 720x450 respectively; DPR was 2.
- All login and signup alerts were focused, visible in the viewport, and below the sticky header: 12/12.
- Signed-out reserve remained enabled. Its role=alert message was inside the reservation panel, immediately below Sign in, visible below the sticky header, and connected to Reserve with `aria-describedby`: 6/6. Focus stayed on the Reserve button while scrolling exposed the message; this satisfies the exact focus-or-scroll requirement.
- Lookup feedback and its action remained visible: 6/6.
- No case had page-wide horizontal overflow. The main route artwork loaded in all 24 cases.

Per-case outer and CSS viewport dimensions, DPR, page/alert/focus bounds, sticky-header offset, theme, artwork load state, overflow, and action relationships are in [native-zoom-recheck.json](native-zoom-recheck.json). The evidence omits account fields, passwords, tokens, and reservation exports.

The QA-only commit `b7714e721d3f7fac38425f073a885711c278b1d1` records the prior Stage 2 repair recheck. This new native-zoom evidence was collected afterward against the unchanged application commit and image; no official suite rerun was needed.
