# Accepted delivery revisions

| Stage | Accepted application revision | Independent evidence | Status |
| --- | --- | --- | --- |
| 1 | 79f39e13095f011fe9baadc3f17bf59636a1bcba | evidence/s1-79f39e1-01/qa-recheck.md; evidence commit 2aa318b82c73c74a6876a999c3420a9f7c54d2cc | Accepted by independent QA; official 120/120 and 11 independent groups |
| 2 | 64d0f501f733f773c3357092c6ea5676b90512d0 | evidence/s2-64d0f50-01/qa-recheck.md and native-zoom-recheck.md; evidence commit 070c0d9f60d9f4357f2c68b999ba370bd0d3680b | Independently accepted; official 120/120 and 25/25; native 200% zoom 24/24 |
| 3 | Pending | Pending | Authorized to extend a tracked copy of accepted Stage 2 |
| 4 | Pending | Pending | Awaiting Stage 3 acceptance |

Stage 1 QA found a real JSON response charset defect at 038a02b54df4cabf76ebfe3e00e28dede664ba57. Backend repaired it in 79f39e13095f011fe9baadc3f17bf59636a1bcba; independent QA rechecked success/error JSON, empty 204 and HTML responses. Original failure evidence remains tracked.

Measured Stage 1 offline runtime: network none, 2 CPU/2 GiB; cold launch to first health 752.8 ms, maximum observed normal request 30.4 ms across 385 requests, maximum control 943.3 ms across 43 calls. These are observed checks, not universal latency guarantees or provider billing.

Stage 2 QA reproduced and retained failures in imported receipt replay, typography/artwork, signup layout, stale refusal feedback, and mobile error visibility/focus. Repairs were independently rechecked. Native zoom used Chromium tabs.setZoom/getZoom in an isolated profile, not viewport emulation. Observed Stage 2 cold startup was 826.4 ms under 2 CPU/2 GiB; official harness elapsed 46.460 seconds. Backend/import evidence from unchanged accepted ancestors was reused.

Stages 1 and 2 are frozen. Later features belong only in the next-stage copy. Evidence-only commits reuse verified application evidence when source is unchanged. Final fresh-clone all-stage verification and participant submission gates remain pending.
