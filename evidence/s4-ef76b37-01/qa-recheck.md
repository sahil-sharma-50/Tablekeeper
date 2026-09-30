# Stage 4 repair recheck

## Revision and runtime

- Application SHA at checkout and before testing: `ef76b375e4483da8c46f54220b2ef687c3a9b9e8`.
- Exact image: `sha256:2ee6b7ccaaf9e0a45345f6b1c102482086922e919bacfdb14ecf3fc26b524830`, labeled with `qa.source_sha=ef76b375e4483da8c46f54220b2ef687c3a9b9e8`.
- Image ran in an isolated container with 2 CPU and 2 GiB memory. Checkout HEAD and application paths were verified; no application source changes were made during QA.
- Binding requirements: complete immutable `requirements.md`, Stage 4 lines 1022 onward, inherited contracts and usability brief; task LF digest `370f2b750a2e221f064f9452d0de6b716a50fc00f2bfea98f290e6abefd8489b`.

## Official isolated suite

Command, invoked from the challenge root with a new output directory:

```powershell
wsl -d Ubuntu-24.04 -u bandbuilder --exec bash factory/harness.sh run --track tablekeeper --repo '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory/submission/tablekeeper-v4' --stage 4 --mode isolated --out '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory/submission/tablekeeper-v4/evidence/s4-ef76b37-01'
```

Result: Stage 1 120/120, Stage 2 25/25, Stage 3 7/7 and Stage 4 6/6; zero official failures. Run ID `bd0719a7957e4a55af500b342a173dd7`. The official report says `provenance=working-tree` and has an empty revision field; the exact checkout SHA was independently recorded before and after the harness. The Stage 4 shipped suite is a six-test smoke suite. Logs, counts and report are retained in this directory.

## Exact-image browser checks

The native zoom run used Chromium `151.0.7922.34`, a temporary MV3 extension and an isolated profile. `chrome.tabs.getZoom()` returned exactly `2.0`; this was browser tab zoom, not CSS zoom, device scale emulation or viewport-only emulation. The exact labeled image was published only on a dedicated bridge container at `127.0.0.1:18766`, with 2 CPU/2 GiB limits.

Command:

```powershell
$env:PLAYWRIGHT_MODULE='C:\Users\sahil\AppData\Local\npm-cache\_npx\e41f203b7505f1fb\node_modules\playwright'
$env:CHROMIUM_EXECUTABLE='C:\Users\sahil\AppData\Local\ms-playwright\chromium-1234\chrome-win64\chrome.exe'
$env:NATIVE_ZOOM_SCENARIO=(Resolve-Path checks/stage4_mobile_interaction_recheck.cjs).Path
node checks/native_zoom_probe.cjs http://127.0.0.1:18766 1280 720
```

The full exact-source Stage 4 browser scenario passed: manager authorization/privacy, preview immutability, apply, uncertain preview/apply/amend original-body/key recovery, history/series/cancellation state, and source-runtime checks. The actual-zoom replan/series matrix covered 375x812, 768x1024, 1280x720 and 1440x900 in both themes (16 samples); all 16 had no document-wide horizontal overflow. The focused 409 plan alert was visible and focused at CSS y=170 below the 125 px mobile sticky header.

Keyboard access passed at outer 375x812/200%: after keyboard search, Tab reached the available 19:00 button, Enter selected it with visible focus, and Tab reached the enabled Reserve button at CSS y=181..225, below the 125 px header. The pointer path remains blocked: a normal Playwright pointer click on the same available button auto-scrolls it to CSS y=67..102 under the sticky header, whose center intercepts the click. The action times out after 5 seconds and the slot remains unselected. The exact measured hit target is the header `nav`. No force-click was used. This is the remaining Stage 4 acceptance blocker.

At normal browser zoom, the inherited logged-out Reserve flow passed at 375x812 and 1280x720 in both themes. Selection from scroll position zero brought the panel into view without manual scrolling; Reserve remained enabled and visible below the header. The alert appeared immediately below Sign in inside the panel, visible below the sticky header and focused when first shown. After the user clicked Reserve, focus stayed on that button and `aria-describedby` still referenced the alert. Mobile bounds: panel y=78, Reserve y=502, alert y=407, header bottom=65. Desktop bounds: panel y=177, Reserve y=605, alert y=510, header bottom=76.

`browser-exact-mobile-attempt-2.log` preserves the complete sanitized exact-source run; `browser-zoom-matrix.json` contains the compact viewport, bounds, focus and state summary. Earlier `browser-attempt-*`/`browser-mobile-attempt-*` runs used port 18765, which mapped to a different unlabeled image on an internal Docker network; they are explicitly excluded as evidence. The valid exact-image run used port 18766 and the image ID above.

## Acceptance

Stage 4 is not accepted on `ef76b375e4483da8c46f54220b2ef687c3a9b9e8` because pointer slot selection at actual 200% zoom/375x812 is intercepted by the sticky header after automatic scrolling. The keyboard route and other checks above pass. QA routed the exact reproducer and hit-test to the frontend owner and lead. No copy-forward or QA commit was made.
