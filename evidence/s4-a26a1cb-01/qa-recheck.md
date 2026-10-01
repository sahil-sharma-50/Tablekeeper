# Stage 4 exact-source QA recheck

Date checked: 2026-10-01

## Revision and image

- Application `HEAD`: `a26a1cbb555b14f76c21abf42383e42f65d12543` (parent `1518657999f7c2856c7e41506aed0d20ffc503e8`).
- The application commit changes only `stage-4/web/regressions/native-zoom-layout.cjs`, `stage-4/web/src/main.tsx`, and `stage-4/web/src/styles.css`. Stages 1–3 and Stage 4 server/API sources are unchanged from the previously accepted/rechecked backend source. The index was empty before testing; the current QA-only working diff is `checks/stage4_mobile_interaction_recheck.cjs`.
- Built from `stage-4` with `docker build --label qa.source_sha=a26a1cbb555b14f76c21abf42383e42f65d12543 -t tablekeeper-s4-a26a1cb-qa .`. Image ID: `sha256:3290b91b2283828c03266da019838dfd98ad469427d2d6a3a1da7867c98cef5b`; inspected image label matches the full commit SHA.
- Browser ran against dedicated container `83a3dded9e4fe6d288e8e5f16993f74d179634578e2bf9fb4035f87539f1adc8` using that image, limited to 2 CPUs and 2 GiB and published only at `127.0.0.1:18767`. Container/image IDs and the label were inspected independently.

## Official isolated suites

Command, launched from `C:\Users\sahil\Desktop\BAND - Dark Factory`:

```powershell
wsl -d Ubuntu-24.04 -u bandbuilder --cd '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory' --exec bash factory/harness.sh run --track tablekeeper --repo '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory/submission/tablekeeper-v4' --stage 4 --mode isolated --out '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory/submission/tablekeeper-v4/evidence/s4-a26a1cb-01'
```

Result: Stage 1 120/120, Stage 2 25/25, Stage 3 7/7, Stage 4 6/6; no failures, errors, or skips. Run ID `f2686c7c46f94aa88b01baf0796d9e17`; elapsed 53.17 seconds. Harness metadata reports `provenance=working-tree` and leaves `revision` blank; the checkout `HEAD` and labeled image were independently verified as the SHA above. The six Stage 4 shipped tests are smoke coverage, not a replacement for the independent optimizer/API checks.

## Native browser and interaction recheck

Command used the temporary MV3 extension probe and Playwright persistent Chromium profile; `chrome.tabs.getZoom()` returned exactly `2`:

```powershell
$env:PLAYWRIGHT_MODULE='C:\Users\sahil\AppData\Local\npm-cache\_npx\e41f203b7505f1fb\node_modules\playwright'
$env:CHROMIUM_EXECUTABLE='C:\Users\sahil\AppData\Local\ms-playwright\chromium-1234\chrome-win64\chrome.exe'
$env:NATIVE_ZOOM_SCENARIO=(Resolve-Path 'checks/stage4_mobile_interaction_recheck.cjs').Path
$env:QA_SOURCE_SHA='a26a1cbb555b14f76c21abf42383e42f65d12543'
node checks/native_zoom_probe.cjs http://127.0.0.1:18767 1280 720
```

The browser reported Chromium 151.0.7922.34, outer window 1280x720, CSS viewport 640x360, DPR 2, and no horizontal overflow. All 16 replan/series samples at 375x812, 768x1024, 1280x720 and 1440x900, in light and dark themes, had actual tab zoom 2 and no horizontal overflow.

- **Pointer fix passes:** at 375x812 and actual zoom 2, normal Playwright pointer click (no force option) selected available `slot-t_2-19:00`. Before scrolling its center was offscreen; after automatic header-aware scrolling it was at y=254 below the 125px header, hit-tested to the target button, and selected. `clickError` was null.
- **Keyboard path passes:** search returned 200; Tab reached the slot in four stops; Enter selected it with visible focus. Tab then reached the enabled Reserve action in 31 additional stops; it was visible below the header with visible keyboard focus.
- **Stale apply feedback passes:** stale plan apply returned 409; the role=alert was focused, in view and below the sticky header at native zoom.
- **Signed-out Reserve passes:** mobile 375x812 and desktop 1280x720, both themes. Search began at scrollY 0; a real available slot click selected the slot; Reserve stayed enabled and visible below the header. The login-required alert was focused, visible in the panel immediately below Sign in, and linked by `aria-describedby`.
- The exact Stage 4 full browser baseline also passed, including its optimizer/policy/replan/series scenarios and response-recovery assertions. Detailed measurements are in `browser-zoom-matrix.json`; complete raw output is `browser-exact-mobile-attempt-2.log`.

The previous exact labeled-source run at `ef76b375e4483da8c46f54220b2ef687c3a9b9e8` reproduced the real pointer obstruction: ordinary click scrolled the slot under the sticky navigation and timed out. That failure remains preserved in `evidence/s4-ef76b37-01/`. The first run against the new image had a stale SHA label in the QA scenario itself; I corrected the owned scenario to require `QA_SOURCE_SHA`, then reran and retained attempt 2 as the acceptance capture. Attempt 1 is not used as acceptance evidence.

## Reused exact-source evidence and disposition

No Stage 4 backend/API/import/optimizer/runtime implementation changed in the frontend-only commits. The independent bounded optimizer oracle, API concurrency/rollback groups, populated imports from Stages 1–3 with retained sessions/receipts, and offline/resource/runtime/assets measurements from `evidence/s4-756c068-01/` therefore remain applicable and are reused, as directed. They are not represented as rerun on this frontend repair. Stage 4 application acceptance is **PASS** at `a26a1cbb555b14f76c21abf42383e42f65d12543`; no application defects remain from this handoff. The separate final fresh-clone `--all` and participant submission gates remain pending.

QA did not modify application source and has not staged or committed any files. Pending a fresh exclusive QA token for the completed owned paths only.
