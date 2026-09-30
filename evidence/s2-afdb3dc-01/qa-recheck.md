# Stage 2 independent QA recheck

## Revision and scope

- Exact application commit checked: `afdb3dc0a0eeca44583fe456186618de78525aca` (parent `3f2941f11e0db3760f8b11ef00459410d82fdf94`).
- Requirements: immutable `requirements.md` at `a9c7024bfdaf39cdb8ae25018862d25c6719550b`; LF digest `370f2b750a2e221f064f9452d0de6b716a50fc00f2bfea98f290e6abefd8489b`.
- The official report's `revision` field is blank and `provenance` is `working-tree`; immediately before that run, workspace HEAD was the exact SHA above. The isolated harness passed inherited Stage 1 120/120 and Stage 2 25/25, with no failed/error/skipped/deselected tests. Its Stage 3 sentinel receives the expected policies-route 404 and is outside this acceptance scope.
- Between the original Stage 2 integrated revision `eff54a8c40492a33698ee70b31fb3502534b0b76` and `afdb3dc`, no `stage-2/web` path changed. The `afdb3dc` UI observations reuse exact frontend evidence from the earlier handoff where noted. Current uncommitted `stage-2/web` edits (`src/main.tsx`, `src/styles.css`, `src/booking-attempt.ts`, and `regressions/`) appeared after these observations and are not covered by this evidence.

## Commands and runtime

Official isolated run, launched from `C:\Users\sahil\Desktop\BAND - Dark Factory` into a new output directory:

```powershell
wsl.exe -d Ubuntu-24.04 -u bandbuilder --exec bash -lc "cd '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory' && bash factory/harness.sh run --track tablekeeper --repo '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory/submission/tablekeeper-v4' --stage 2 --mode isolated --out '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory/submission/tablekeeper-v4/evidence/s2-afdb3dc-01'"
```

Independent checks against the freshly built `tablekeeper-s2-afdb3dc` image in a disposable container at port 18084, with the Stage 1 source container at port 18081:

```powershell
python checks/stage1_independent.py --base-url http://localhost:18084 --source-url http://localhost:18081
python checks/stage2_independent.py --base-url http://localhost:18084 --stage1-url http://localhost:18081
```

Both commands passed. Stage 1's inherited API matrix covers 50 overlapping writes, identical-key races, key and type boundaries, replay precedence, PATCH and move atomicity/rollback, DST/absolute durations, and populated import receipts. Stage 2's independent groups cover canonical/non-transitive pairs, capacity/occupancy, adjacency, cancel release, pair PATCH/moves, failed-move atomicity, 50 contending pair bookings, and populated Stage 1 import with retained token, reservation and original receipt. Full outputs: `stage1-independent.log`, `stage2-independent.log`.

The fresh-container measurement is `evidence/s2-afdb3dc-01/runtime-startup.log`: 2 CPU / 2 GiB, launch to first healthy HTTP 200 in 1062.3 ms. Full official logs and count files are `stage-1.log`, `stage-1.counts.json`, `stage-2.log`, `stage-2.counts.json`; report metadata is `report.json`.

An additional fresh-container follow-up replays one original Stage 1 create and two original move receipts after later moves, cancellation, pair-upgrade import, and a subsequent Stage 2 write. All three JSON responses remained exactly equal to their Stage 1 originals. See `evidence/s2-afdb3dc-followup-01/qa-receipt-recheck.md` and `receipt-pair-upgrade.json`; new image/container startup and full check output are in that directory.

## Browser flows verified

- Logged-out reserve error is immediately under Sign in inside the reservation panel at 375×812 and 1280×720; selection automatically reveals the action, no manual scroll is used, submit remains enabled, and error focus/description/alert are present. See `../s2-eff54a8-01/ui-mobile-auth-error.yml`, `ui-desktop-auth-error.yml` and screenshots.
- A delayed earlier search does not overwrite a later search. Closed Monday and fully booked open-day states render distinctly. See `ui-stale-search-network.txt`, `ui-stale-search-result.*`, `ui-closed-day.*`, `ui-fully-booked.*`.
- Single and pair committed-response drops show uncertainty without confirmation/error and retry the same original body/key to recover the original reference. A changed single field creates a new request identity. See `ui-single-lost-retry.json` and `ui-pair-lost-retry.json`.
- Browser migration: user `QA 97` stayed signed in while a populated Stage 1 export was imported into Stage 2 without reload. A lost-response request remained pending; retry after import returned the original reference and same body/key, and lookup returned confirmed with a cancel action. The export/token was never recorded. See `ui-browser-upgrade.json` and `ui-upgrade-lookup.*`.
- A single reservation's one-click cancel removes its action and shows cancelled status; theme persistence, initial OS-dark preference, visible keyboard focus, viewport overflow, demo weekdays, and optional phone omission are recorded in `../s2-eff54a8-01/`.

## Reproducible UI failures on the checked frontend

1. **Stale booking error remains after a new available selection.** In the browser at `http://localhost:18084`, select `t_d` at 19:00 on 2026-10-14 for party size 4, submit, and take the table from another client before/while that request arrives. The app returns `409 table_unavailable`, shows the required error and refreshes availability. Then select available `t_d` at 21:00. Expected: selecting a new slot clears the old booking alert. Actual: summary and selected slot change, but `booking-error` still says “That table is already reserved.” Evidence: `ui-table-taken-error.*`, `ui-stale-booking-error.*`. Reported to frontend and lead in Jam message `a996e7af-a703-409e-9f37-c7546d4ccc4a`.
2. **Wrong heading font and cropped auth artwork.** Open `/login` at 1280×720. Expected: Source Sans 3 for every text element and full undistorted supplied artwork. Actual: body uses Source Sans 3, headings compute to Georgia; the 1254×1254 image is placed in a 618.2×465 box with `object-fit: cover`. Signup art uses the same crop behavior. Evidence: `../s2-eff54a8-01/ui-fonts-artwork-1280x720.json`, `ui-login-artwork.json`, `ui-login-1280x720.png`. Frontend/lead report: `1821fc3d-bf87-408f-ba43-b44e7df81c2d`.
3. **Signup exceeds required desktop viewports and clips failure feedback on mobile.** Open `/signup`: at 1280×720 and 1366×768, `scrollHeight=780`; at 1440×900 it fits. Submit a duplicate email at 375×812. Expected: normal desktop account routes fit without unnecessary scrolling and the error remains visible. Actual: desktop signup requires vertical scrolling; the alert bounds extend from y=786 to y=826 at mobile scrollY 0, clipping 14 px. Evidence: `../s2-eff54a8-01/ui-signup-1280x720.json`, `ui-signup-1366x768.json`, `ui-signup-1440x900.json`, `ui-failed-signup.json`. Frontend/lead report: `c1774a6d-115d-433f-a8a3-7e9a00cd079a`.

All are functional usability/design requirements, not aesthetic exceptions. Their browser captures were made before the current uncommitted UI edits; those edits require a fresh committed revision and retest. Native browser 200% zoom could not be applied by the available automation; 640×360 effective viewport was only a proxy, so that item remains unproven.

## Result

The Stage 2 API, imported browser session and retry, pair concurrency, official tests, startup/runtime limits and the specified logged-out reserve path pass on the checked revision. Stage 2 is **not independently accepted** because the stale alert, signup viewport/error clipping, heading font and cropped artwork are real failures; native 200% zoom and the complete pair confirmation-to-cancel label chain remain unproven. No application source was changed by QA.
