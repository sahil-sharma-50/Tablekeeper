# Stage 3 independent acceptance recheck

## Verdict and provenance

Stage 3 independently passes at exact integrated source `bc5826217c1c8aa234e9270baf3b93c3cea9a398` (parent `0efa1e96f706703cb2139bf2a4a8db78275f73c8`). `git rev-parse HEAD` matched before and after; there were no tracked Stage 1–3 source diffs or staged application paths. Requirements are the unchanged complete `requirements.md` and inherited contracts/usability brief under LF-normalized task digest `370f2b750a2e221f064f9452d0de6b716a50fc00f2bfea98f290e6abefd8489b`.

## Official isolated run

Command from the challenge root:

```powershell
wsl -d Ubuntu-24.04 -u bandbuilder --cd '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory' --exec bash factory/harness.sh run --track tablekeeper --repo '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory/submission/tablekeeper-v4' --stage 3 --mode isolated --out '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory/submission/tablekeeper-v4/evidence/s3-bc58262-01'
```

Result: Stage 1 **120/120**, Stage 2 **25/25**, Stage 3 **7/7**; highest contiguous stage 3. Runtime was 85.666 seconds from `report.json` timestamps. The harness marks provenance `working-tree` and leaves its revision field blank; the exact committed SHA and clean application source tree were checked independently. The overshoot Stage 4 sentinel is retained: its unsupported series amendment endpoint returned 404 (`test_series_clock_time_can_be_changed`, 1 failed / 4 passed). This is outside Stage 3 acceptance.

## Independent API and pair-order regression

Command:

```powershell
python checks/stage3_independent.py --base-url http://127.0.0.1:18104 --stage1-url http://127.0.0.1:18101 --stage2-url http://127.0.0.1:18102 --result-json evidence/s3-bc58262-01/independent-api.json
```

All ten named PASS groups in `independent-api.log` pass: eight functional result groups and two populated-import groups. The JSON summary separately records seven core check functions and both import results. Coverage includes strict explanations and dated policy selection; policy authorization, validation and replay; accepted terms/history/revisions; cutoff and stale-revision precedence; concurrent revision writes; atomic series adoption, calendar rules, DST, exceptions and cancellation; pair history; collective swaps and rollback; and populated Stage 1/2 imports with retained sessions and exact create/move receipts. The updated pair-history group also sends a reversed-order pair through `POST /reservation-moves` and checks the response, reservation history, restaurant revision, complete series revision and exception state remain unchanged. The focused check is `python checks/stage3_pair_noop_repro.py http://127.0.0.1:18104`; both pair PATCH and collective-move no-ops pass. The original pre-fix failure on `0efa1e96f706703cb2139bf2a4a8db78275f73c8` remains in `evidence/s3-0efa1e9-01/pair-order-noop-repro.stderr.log` and `independent-api-blocked-pair-noop.log`.

The independent API run recorded 240 requests (maximum 61.4 ms) and 38 control calls (maximum 306.8 ms), under the 5-second and 10-second limits.

## Offline runtime, resources and assets

Built from `stage-3/` using `docker build -t tablekeeper-s3-qa-bc58262 stage-3`; image ID is `sha256:c441bf50b951d42000b1e266ef464d59436e1b8dfb928ccf0ee2b16251973ea6`. On that exact image, `python checks/stage1_runtime_probe.py --image tablekeeper-s3-qa-bc58262` passed with Docker `network=none`, `NanoCPUs=2000000000`, memory `2147483648`, and `PORT=8080`. Cold launch-to-first-healthy was **1,976.7 ms**. Inherited offline checks passed 50 overlapping writes, two 50-way idempotency races, strict types/precedence, swap/rollback, receipt replay and Berlin/New York DST; 385 requests peaked at 54.2 ms and 43 control calls at 1,729.2 ms. Both timezone databases were available.

`checks/stage3_offline_assets.py` passed inside the same network-disabled image: `/`, the JavaScript/CSS bundles and `/assets/source-sans-3.woff2` returned 200 from the app origin; no external stylesheet resources were present. The browser separately confirmed the computed `Source Sans 3` face reached `loaded` state and recorded no cross-origin runtime resources.

## Browser, accessibility and real native zoom

Command:

```powershell
$env:PLAYWRIGHT_MODULE = 'C:\Users\sahil\AppData\Local\npm-cache\_npx\e41f203b7505f1fb\node_modules\playwright'
$env:CHROMIUM_EXECUTABLE = 'C:\Users\sahil\AppData\Local\ms-playwright\chromium-1234\chrome-win64\chrome.exe'
$env:NATIVE_ZOOM_SCENARIO = 'C:\Users\sahil\Desktop\BAND - Dark Factory\submission\tablekeeper-v4\checks\stage3_browser_recheck.cjs'
node checks/native_zoom_probe.cjs http://127.0.0.1:18104 1280 720
```

The probe created and removed a temporary extension/profile. Chromium `151.0.7922.34` returned `chrome.tabs.getZoom() = 2.0`; at outer 1280×720 the CSS viewport was 640×360 at DPR 2. The scenario checked policy/history/series controls at native 200% on 1280×720 and 1440×900 in both themes (8 samples, no horizontal overflow). It also checked 12 normal-zoom mobile/tablet/desktop layouts, 8 focused login/signup failures with retained form values, 4 signed-out Reserve errors visible after submit without additional scrolling, and the error's ARIA description while keeping Reserve enabled.

The browser used a real service response for each policy/adoption error: request-body fault injection reached the server, which returned 422; the UI exposed `role=alert` feedback linked with `aria-describedby`. Successful publication showed its status, and the created agreement/occurrences were visible. Policy and adoption uncertainty retries retained the original parsed body and idempotency key. Keyboard checks opened policy, history and accepted-terms disclosures, verified visible focus on the first policy input, selected the recurrence count, and submitted adoption. Owner-only history/terms were checked; another diner received a visible 404. Each recurrence date label had positive text bounds, was below the sticky header and had no clipping ancestor. Occurrence cancellation removed its button and showed cancelled status; cancelling the anchor with one click kept both later occurrences, and a fresh lookup showed the cancelled history event.

`browser-zoom-matrix.json` contains sanitized dimensions, theme, focus, status, date and zoom measurements. The independent API, pair and offline logs contain no test credential values. The out-of-scope Stage 4 sentinel log remains available with fixture email/password fields redacted; its counts are retained.

## Remaining scope and elapsed time

No Stage 3 requirement gap remains identified. Stage 4 acceptance, final fresh-clone `--all`, and the already documented unchanged-input `Harness:`/`Model:` submission gate remain outstanding. Official Stage 3 harness elapsed time was 85.666 s; cold offline startup was 1.977 s. Across both measured control-call contexts, the overall maximum was 1,729.2 ms from the inherited offline suite; the independent Stage 3 API subset peaked at 306.8 ms. Provider token usage was not measured, and harness runtime is not billing data.
