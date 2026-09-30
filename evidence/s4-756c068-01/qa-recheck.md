# Stage 4 independent recheck

## Revision and result

- Exact integrated application SHA: `756c068eb1fc59319385f98071112e768383aa8a`.
- Backend SHA: `561a9f5c62181e3a41076a399256e8bb676ea1fe`.
- HEAD and clean tracked application diffs/index were verified for the run; QA made no application changes. Since the run, the shared working tree shows an uncommitted change in `stage-4/web/src/styles.css` (27 insertions, 2 deletions). That working-tree change is not part of the image/report above and has not been independently checked; recheck only after a committed handoff.
- Stage 4 is **not accepted**. API, import, official smoke, offline runtime and assets passed. Actual Chromium tab zoom at 2.0 exposed horizontal document overflow on the required 375x812 outer viewport for both replan and series pages in both themes. This is a concrete browser usability failure, not a CSS viewport proxy result.

## Official isolated suites

Command, launched from the factory root:

```powershell
wsl -d Ubuntu-24.04 -u bandbuilder --exec bash factory/harness.sh run --track tablekeeper --repo '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory/submission/tablekeeper-v4' --stage 4 --mode isolated --out '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory/submission/tablekeeper-v4/evidence/s4-756c068-01'
```

Result: Stage 1 120/120, Stage 2 25/25, Stage 3 7/7, Stage 4 6/6; no failures, errors or skips. Harness run ID `a5c75192794947c7ab045fb94a43342f`. Its report says `working-tree` and has a blank revision, so the exact application SHA above is independently verified from HEAD and clean application diffs. The shipped Stage 4 suite is a six-test smoke sample covering a basic pair, clock amendment and empty replan preview; it is directional, not exhaustive optimizer acceptance.

## Independent API and optimizer checks

`checks/stage4_independent.py` passed all nine independent groups against the exact Stage 4 image and separate populated Stage 1, Stage 2 and Stage 3 containers. The groups cover replan guards, accepted-cutoff repair, bounded oracle comparison and apply, state-neutral/no-feasible and stale plans, concurrency, maximum supported input, series amendment and precedence, rollback/no-op/key reuse, and populated imports with retained sessions and original receipts. The reference optimizer in `checks/stage4_optimizer.py` compares the lexicographic objective: changed booking count, total unused accepted capacity, then the ordered assignment-rank vector. Replan output remained exactly `{reference,table_ids,changed}`; it did not invent an earlier assignment for moved reservations.

Runner command:

```powershell
docker run --rm --name tk4-s4-api-runner --network tk4-s4-756c068-qa-net --cpus 2 --memory 2g --tmpfs /tmp:rw,noexec,nosuid,size=128m -v 'C:\Users\sahil\Desktop\BAND - Dark Factory\submission\tablekeeper-v4\checks:/checks:ro' -v 'C:\Users\sahil\Desktop\BAND - Dark Factory\submission\tablekeeper-v4\evidence\s4-756c068-01:/out' -w / -e PYTHONDONTWRITEBYTECODE=1 df-harness-runner python /checks/stage4_independent.py --base-url http://tk4-s4-756c068-qa:8080 --stage1-url http://tk4-s4-stage1-79f39e1:8080 --stage2-url http://tk4-s4-stage2-afdb3dc:8080 --stage3-url http://tk4-s4-stage3-bc58262:8080 --result-json /out/independent-api.json
```

The run made 247 requests (maximum 31.6 ms) and 67 controls (maximum 69.1 ms). Machine-readable result and full compact pass log: `independent-api.json`, `independent-api-attempt-8.log`.

## Offline runtime and assets

The exact image `sha256:2ec35203394f989936836c59ca0092684dc86d283a79e4fd17121f0e0a0e5854` carries label `qa.source_sha=756c068eb1fc59319385f98071112e768383aa8a`. It built successfully and ran with 2 CPU, 2 GiB and `--network none`. Container launch through first healthy probe was 841.1 ms; the first internal health request was 12.2 ms. Local CSS, JS, Source Sans 3, and image assets loaded; no external asset references were found. Browser verification also confirmed Source Sans 3 loaded. Full measurements are in `offline-startup.log` and `offline-assets.log`.

## Browser check and concrete failure

The browser check used a separate disposable container running the exact image at `http://127.0.0.1:18764`. Playwright Chromium `151.0.7922.34` ran through a temporary isolated MV3 extension and persistent profile; `chrome.tabs.getZoom()` returned `2.0` before and after the scenario, with device pixel ratio 2. This verifies native tab zoom, not viewport emulation.

Reproducer command (set these environment values in PowerShell):

```powershell
$env:PLAYWRIGHT_MODULE='C:\Users\sahil\AppData\Local\npm-cache\_npx\e41f203b7505f1fb\node_modules\playwright'
$env:CHROMIUM_EXECUTABLE='C:\Users\sahil\AppData\Local\ms-playwright\chromium-1234\chrome-win64\chrome.exe'
$env:NATIVE_ZOOM_SCENARIO='C:\Users\sahil\Desktop\BAND - Dark Factory\submission\tablekeeper-v4\checks\stage4_browser_recheck.cjs'
node checks/native_zoom_probe.cjs http://127.0.0.1:18764 1280 720
```

Expected: at actual 200% zoom, the replan and series controls remain usable without document-wide horizontal overflow at the required 375x812 viewport in light and dark themes. Actual: `getZoom()==2`; the resulting CSS viewport is 187x406. In all four 375x812 flow/theme samples, document scroll width is 339 px in light mode or 345 px in dark mode, while client width is 187 px. The recurrence date text itself was not clipped. The other 12 samples (768x1024, 1280x720 and 1440x900, both flows and themes) had no horizontal overflow. Sanitized measurements and the actual failure are in `browser-zoom-matrix.json`; raw browser logs are retained locally but not included in the sanitized evidence set.

The browser functional assertions passed: anonymous 401 and diner 403 with manager controls hidden; no public role picker; private history/terms 404; stale-plan 409 alert focused and visible below the 65 px sticky header; exact assignment response shape; no fabricated prior assignment; committed preview/apply/amend retries preserve original body and key; lookup shows the applied table and accepted terms; recurrence dates/current tables/status/exception are visible; one-click occurrence cancellation removes its action; Source Sans 3 and no external browser origins. The scenario reports false only because the required mobile 200% overflow check failed.

`COVERAGE.md` now records the complete Stage 4 matrix and this blocker. Evidence is sanitized; no private account credentials, bearer values, exports or fixtures are included in the report or browser matrix. No files have been staged or committed; an explicit QA commit token is still required.
