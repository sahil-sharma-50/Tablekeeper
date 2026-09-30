# Accepted delivery revisions

| Stage | Accepted application revision | Independent evidence | Status |
| --- | --- | --- | --- |
| 1 | 79f39e13095f011fe9baadc3f17bf59636a1bcba | evidence/s1-79f39e1-01/qa-recheck.md; evidence commit 2aa318b82c73c74a6876a999c3420a9f7c54d2cc | Accepted by independent QA; official 120/120 and 11 independent groups |
| 2 | Pending | Pending | Authorized to extend a tracked copy of accepted Stage 1 |
| 3 | Pending | Pending | Awaiting Stage 2 acceptance |
| 4 | Pending | Pending | Awaiting Stage 3 acceptance |

Stage 1 QA found a real JSON response charset defect at 038a02b54df4cabf76ebfe3e00e28dede664ba57. Backend repaired it in 79f39e13095f011fe9baadc3f17bf59636a1bcba; independent QA rechecked success/error JSON, empty 204 and HTML responses. Original failure evidence remains tracked.

Measured Stage 1 offline runtime: network none, 2 CPU/2 GiB; cold launch to first health 752.8 ms, maximum observed normal request 30.4 ms across 385 requests, maximum control 943.3 ms across 43 calls. These are observed checks, not universal latency guarantees or provider billing.

Stage 1 is frozen. Later features belong only in the next-stage copy. Evidence-only commits reuse verified application evidence when source is unchanged. Final fresh-clone all-stage verification and participant submission gates remain pending.
