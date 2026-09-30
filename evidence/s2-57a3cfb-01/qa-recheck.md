# Independent Stage 2 frontend recheck

- Application SHA: 57a3cfb99aaf53dcf63628640c4b17d26fccf0fb
- Parent: a20396f7655b290803cd5f9628509e313a9b9b9a
- Backend acceptance source ancestor: afdb3dc0a0eeca44583fe456186618de78525aca
- Requirements digest: 370f2b750a2e221f064f9452d0de6b716a50fc00f2bfea98f290e6abefd8489b
- Workspace: C:/Users/sahil/Desktop/BAND - Dark Factory/submission/tablekeeper-v4
- Exact image: tablekeeper-s2-57a3cfb:qa, sha256:9f0a30517e36333a7dd28ae163984f76e0758cf5887d7308833529417d57336d

## Source and official run

The frontend commit contains exactly seven stage-2/web files: regressions/account-layout.mjs, regressions/booking-attempt.test.ts, regressions/booking-recovery.mjs, regressions/zoom-equivalent-layout.mjs, src/booking-attempt.ts, src/main.tsx and src/styles.css. Before and after testing, git rev-parse HEAD was the application SHA; tracked and staged diffs under stage-2 were empty. The accepted backend commit is an ancestor, and git diff afdb3dc..57a3cfb was empty for stage-1, stage-2/server and stage-2/checks/backend.

Official isolated command from C:/Users/sahil/Desktop/BAND - Dark Factory:

    wsl -d Ubuntu-24.04 -u bandbuilder --cd '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory' --exec bash factory/harness.sh run --track tablekeeper --repo '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory/submission/tablekeeper-v4' --stage 2 --mode isolated --out '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory/submission/tablekeeper-v4/evidence/s2-57a3cfb-01'

Result: Stage 1 120/120; Stage 2 25/25; no failures, errors, skips or deselections. Stage 3 sentinel 404 is out of Stage 2 scope. Report run id 865f22f24e4a4cd0a51d6ca6c5110482, elapsed 48.6 seconds, 2026-09-30 16:03:21.694 to 16:04:10.323 UTC. report.json has blank revision and working-tree provenance; the independently recorded pre/post git SHA and clean tracked source diff identify the tested commit.

## Independent browser outcomes

- Typography/artwork: body and h1/h2 compute to loaded Source Sans 3. The 1254x1254 supplied art uses object-fit contain. Desktop signup has no page overflow at 1280x720, 1366x768 or 1440x900. Tablet 768x1024 and mobile have no page-wide horizontal overflow.
- Themes/keyboard: light/dark toggle persists across reload. Five successive Tab captures on the home page show visible focus on navigation/actions.
- Search race: held the 2026-10-01 availability response for 800 ms, submitted 2026-10-02 while the first response remained pending, then allowed the older response to finish. The final field remained 2026-10-02 and C+A at 18:00 remained available. Evidence: ui-search-race-oct1-oct2.json.
- Long signed-out reservation: at 375x812 and 1280x720, after returning the page to the top and selecting available C+A at 16:00, the app itself scrolled the review panel into view. The alert was immediately after Sign in, focused, visible below the sticky header, and Reserve remained enabled. No manual scroll was used after selecting. Evidence: ui-reserve-auth-375x812-selected.json and ui-reserve-auth-1280x720-selected.json.
- Mobile 409: a second synthetic QA user successfully booked C+A at 18:00 after the main page had selected it. The main page showed 'That table is already reserved.' The alert was visible at y=597..638 below the 65 px header; the cell became disabled/unavailable and date/party remained; active focus was BODY. Evidence: ui-mobile-409-competitor-18.json and ui-mobile-409-alert.json. A subsequent selection clears a definite stale refusal.
- Login/signup failure: at 375x812 the focused login alert was y=836..876 and the duplicate-signup alert y=836..877, both below the viewport. Desktop login feedback was visible. Evidence: ui-login-failure-375x812.json and ui-signup-failure-375x812.json.
- Pair recovery and cancel: on the exact image, a committed C+A POST response was deliberately dropped. Retry used the original body and key and restored the original confirmation. Lookup showed Thursday 1 October at 19:00, guests 5, table C + A. The outlined Cancel reservation button needed one click, disappeared after success, showed cancelled, and freed both C and A. The original reference, account values and bearer token are not in the evidence.
- Native zoom: Ctrl+Shift+Equal and Ctrl+Equal left the 1280 CSS viewport and DPR 1.0000000149 unchanged. CUA returned apps=[] and browsers=[]; createBrowserTab for iab and chrome returned 'Browser is not available'. Native 200% remains unverified; no reduced-viewport proxy is claimed.

## Decision

Stage 2 is not accepted on this revision. Concrete remaining issue: mobile login/signup feedback is below the viewport; the 375x812 409 error also does not receive focus. Actual native 200% browser zoom could not be exercised in the available UI surface. The required long-schedule signed-out reserve error is visible and focused at both required viewports. No stage copy-forward or QA commit was made.