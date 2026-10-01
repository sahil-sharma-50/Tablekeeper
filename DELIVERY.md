# Accepted delivery revisions

| Stage | Accepted application revision | Independent evidence | Status |
| --- | --- | --- | --- |
| 1 | 79f39e13095f011fe9baadc3f17bf59636a1bcba | evidence/s1-79f39e1-01/qa-recheck.md; evidence commit 2aa318b82c73c74a6876a999c3420a9f7c54d2cc | Accepted by independent QA; official 120/120 and 11 independent groups |
| 2 | 64d0f501f733f773c3357092c6ea5676b90512d0 | evidence/s2-64d0f50-01/qa-recheck.md and native-zoom-recheck.md; evidence commit 070c0d9f60d9f4357f2c68b999ba370bd0d3680b | Independently accepted; official 120/120 and 25/25; native 200% zoom 24/24 |
| 3 | bc5826217c1c8aa234e9270baf3b93c3cea9a398 | evidence/s3-bc58262-01/qa-recheck.md; evidence commit 31b31910f62591ee9db50f0ada2b43a07acc7612 | Independently accepted; official 120/120, 25/25, 7/7; API/import/native zoom/offline checks pass |
| 4 | a26a1cbb555b14f76c21abf42383e42f65d12543 | evidence/s4-a26a1cb-01/qa-recheck.md; evidence commit e8957ff96d8ae2401910b7be43d082e6b238b686 | Independently accepted; official 120/120, 25/25, 7/7, 6/6; independent optimizer/API/import/native zoom checks pass |

Stage 1 QA found a real JSON response charset defect at 038a02b54df4cabf76ebfe3e00e28dede664ba57. Backend repaired it in 79f39e13095f011fe9baadc3f17bf59636a1bcba; independent QA rechecked success/error JSON, empty 204 and HTML responses. Original failure evidence remains tracked.

Measured Stage 1 offline runtime: network none, 2 CPU/2 GiB; cold launch to first health 752.8 ms, maximum observed normal request 30.4 ms across 385 requests, maximum control 943.3 ms across 43 calls. These are observed checks, not universal latency guarantees or provider billing.

Stage 2 QA reproduced and retained failures in imported receipt replay, typography/artwork, signup layout, stale refusal feedback, and mobile error visibility/focus. Repairs were independently rechecked. Native zoom used Chromium tabs.setZoom/getZoom in an isolated profile, not viewport emulation. Observed Stage 2 cold startup was 826.4 ms under 2 CPU/2 GiB; official harness elapsed 46.460 seconds. Backend/import evidence from unchanged accepted ancestors was reused.

Stage 3 QA reproduced a reversed-pair no-op that incorrectly changed revision/history. Backend fixed shared canonicalization before PATCH and collective-move comparisons; independent checks confirm unchanged history, terms, series exception flags and counters. Original failure evidence is retained. Offline 2 CPU/2 GiB cold startup was 1,976.7 ms; maximum observed normal request was 61.4 ms and overall control maximum 1,729.2 ms across the recorded contexts. Official Stage 3 harness elapsed 85.666 seconds.

Stage 4 QA retained genuine native 200% mobile overflow and pointer/header interception defects. Frontend repaired the root minimum width, narrow layouts and interaction scroll/focus; independent labeled-image checks confirm ordinary pointer and keyboard selection, feedback and all 16 zoom layout samples. The unchanged backend passed nine independent optimizer/API/import groups. Observed offline 2 CPU/2 GiB startup was 841.1 ms, API maximum 31.6 ms and control maximum 69.1 ms in that Stage 4 run. The shipped Stage 4 official suite is six smoke tests; independent checks provide additional contract coverage. Proposed prior assignments are unavailable under the exact preview response shape and are disclosed rather than invented.

All four application snapshots are frozen. Evidence-only commits reuse verified application evidence when source is unchanged. Final fresh-clone all-stage verification and participant submission gates remain pending.
