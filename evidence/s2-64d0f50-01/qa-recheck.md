# Independent Stage 2 frontend repair recheck

- Application SHA: `64d0f501f733f773c3357092c6ea5676b90512d0`
- Parent: `d3ee94018d6dca65f23d0361139c741253d86b28`
- Accepted backend ancestor: `afdb3dc0a0eeca44583fe456186618de78525aca`
- Requirements digest: `370f2b750a2e221f064f9452d0de6b716a50fc00f2bfea98f290e6abefd8489b`
- Frontend commit paths: `stage-2/web/src/main.tsx`, `stage-2/web/src/styles.css`, `stage-2/web/regressions/account-layout.mjs`, `stage-2/web/regressions/booking-recovery.mjs`.

## Build and official isolated run

Built the exact child-repository source with `docker build --tag tablekeeper-s2-64d0f50:qa .` from `stage-2/`; the production TypeScript/Vite build passed. Image ID: `sha256:3454d6cb9cd4438a6b2fbbd6660e3738c3a7048868ccc789d6f22e628e134de7`.

Started a fresh container with 2 CPU and 2 GiB limits at `http://127.0.0.1:18085`. First `/health` response was HTTP 200, 826.4 ms after container launch. The test container and browser session were stopped after the checks.

Official isolated command, run from `C:/Users/sahil/Desktop/BAND - Dark Factory`:

```sh
wsl -d Ubuntu-24.04 -u bandbuilder --cd '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory' --exec bash factory/harness.sh run --track tablekeeper --repo '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory/submission/tablekeeper-v4' --stage 2 --mode isolated --out '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory/submission/tablekeeper-v4/evidence/s2-64d0f50-01'
```

Harness run `39c9890db20346b0a5e546e860618201` completed in 46.460 seconds (17:26:26.462 to 17:27:12.923 UTC): Stage 1 120/120 and Stage 2 25/25, with no failures, errors, skips, or deselections. Its Stage 3 sentinel received the expected policies-route 404 and is outside Stage 2 scope. `report.json` reports working-tree provenance and an empty revision field; the child repository HEAD was `64d0f501f733f773c3357092c6ea5676b90512d0` before the run and remains that SHA. Stage 1 and Stage 2 source are unchanged and clean.

## Independent browser results

Used a fresh Playwright CLI browser session against the separately built image and a disposable synthetic fixture. No private reference or Bearer [redacted] was retained. Sanitized metrics are in `browser-recheck.json`.

- Wrong login and duplicate signup: 8/8 cases passed across light/dark, 375x812/1280x720. Responses were 401/409 respectively. Alerts had role `alert`, received focus, stayed below the sticky header and within the viewport, and the form values remained. Mobile bounds were y=755.33-795.92 for login and y=670.33-710.92 for signup.
- Signed-out long-schedule reserve: 4/4 cases passed across both themes and required viewports. After selecting C+A at 18:00 from the top of the page, the app automatically revealed a focused alert below Sign in without manual scrolling. Reserve stayed enabled; date, party, and pair remained selected; `aria-describedby` matched the alert. Bounds were y=501.73-560.92 at 375x812 and y=628.56-687.75 at 1280x720.
- Competing pair reservation: second-client C+A at 18:00 returned 201; the selected client's POST returned 409 and availability refresh returned 200. At 375x812, the alert was focused at y=596-636.59 below the 65 px header, the selected cell became unavailable, form values remained, and `aria-describedby` matched. Selecting 21:00 cleared the definite refusal.
- Committed uncertain pair POST: `route.fetch` committed the first C+A POST (201), then its response was aborted before the page received it. The UI showed uncertainty. Retry returned 200 and restored the original confirmation with the same stored request key and body; the confirmation showed C+A at local 21:00.
- Lookup/cancel: lookup returned 200 and retained the C+A label and local time. The outlined `Cancel reservation` action was clicked once, returned 200, showed exact `cancelled` status, and disappeared. A new availability search showed C+A at 21:00 available while the competing 18:00 pair stayed unavailable.
- Browser console after the flow: zero errors and zero warnings.

## Reuse and remaining gap

The 64d0 commit changes only feedback focus/reveal and alert styling. Reused accepted backend/import evidence at ancestor `afdb3dc0a0eeca44583fe456186618de78525aca` and unchanged font/artwork, search-race, viewport, theme, and keyboard evidence at `57a3cfb99aaf53dcf63628640c4b17d26fccf0fb`.

The mobile account feedback and 409 focus defects are resolved on this source. Actual native 200% browser zoom remains unproven. The previously recorded control limitation in `evidence/s2-57a3cfb-01/native-zoom-attempt.md` remains applicable; identical unavailable controls were not retried and no viewport proxy is counted. Stage 2 is not accepted pending that requirement.
