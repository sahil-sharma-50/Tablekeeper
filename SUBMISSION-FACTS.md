# Verified delivery facts

Application: Tablekeeper. Room: `018b7708-b06b-404a-8c00-2cc53c64a9d3`. Exact seat handles, models, efforts and subscription authentication are recorded in `run.json`. No nested agents were recruited.

## Functional acceptance

All four self-contained snapshots were independently accepted before copying forward. Accepted application revisions and retained failures are recorded in `DELIVERY.md`; requirement coverage is in `COVERAGE.md`.

The final fresh clone was detached and clean at `efcfd4b1bdf10a1ada205448f1c8e0bea8aff324`. Its Stage 4 application source is `a26a1cbb555b14f76c21abf42383e42f65d12543`. Later metadata and demo-guide commits changed no application implementation. Final evidence: `evidence/final-efcfd4b-01/qa-final-recheck.md` and `summary.json`.

| Snapshot | Claimed suites passed |
| --- | --- |
| Stage 1 | 120/120 |
| Stage 2 | 120/120 + 25/25 |
| Stage 3 | 120/120 + 25/25 + 7/7 |
| Stage 4 | 120/120 + 25/25 + 7/7 + 6/6 |

No claimed suite had failures, errors or skips. The final isolated `--all` exited 0; report timestamps span 181.421 seconds, with a longest snapshot run of 50.022 seconds. Earlier snapshots' out-of-claim next-stage diagnostic failures are retained and separated from acceptance. The runner labels results preview/directional and leaves its revision field blank; detached Git provenance and source-labeled images establish the checked revisions. Stage 4's shipped six tests are smoke coverage, supplemented by independent exact optimizer enumeration, concurrency, atomic rollback, populated cross-stage imports, original receipt recovery, DST, authorization and browser checks.

## Runtime and packaging measurements

Accepted Stage 4 measurements reused from its unchanged backend: network disabled, 2 CPU, 2 GiB; cold launch to first healthy 841.1 ms; first internal health request 12.2 ms; maximum normal request 31.6 ms across 247 requests; maximum control call 69.1 ms across 67 controls. These are sampled observations, not universal guarantees or timings measured by the final `--all` run. Across other accepted stage checks the largest recorded normal request was 61.4 ms and control call 1,729.2 ms; Stage 3 cold startup was 1,976.7 ms.

All stages have standalone Dockerfile and RUN.md. Stages 2–4 serve compiled UI and API from one origin with bundled fonts, illustrations, licenses and timezone data. Runtime requires no outgoing network; image builds require base-image/npm/pip registry access. No external database, SMS, payments or fabricated authentication is included. State can be ephemeral across restart; export/import compatibility is independently checked.

| Snapshot | Tracked files | Working-file bytes |
| --- | ---: | ---: |
| Stage 1 | 6 | 50,525 |
| Stage 2 | 47 | 5,329,184 |
| Stage 3 | 49 | 5,431,996 |
| Stage 4 | 52 | 5,561,578 |

Counts include each snapshot's assets and copied authored checks/evidence, exclude Git internals, ignored caches and untracked files, and were measured after the demo-guide correction. First repository commit: 2026-09-30 11:58:16 +02:00. Demo-guide audit commit: 2026-10-01 02:17:41 +02:00. That 14 h 19 min 25 s span includes coordination and idle time; it is not measured active compute time. Provider tokens and actual billing were not measured. Subscription authentication and available provider capacity do not establish billing.

Final preview: http://localhost:8102, container `tablekeeper-stage4-final-preview`, accepted Stage 4 source `a26a1cbb555b14f76c21abf42383e42f65d12543`, image `sha256:3290b91b2283828c03266da019838dfd98ad469427d2d6a3a1da7867c98cef5b`. It starts with empty state, no seeded accounts and no mounted volumes. Opt-in seven-day demo fixtures have separate disposable-container instructions; no manager account is fabricated.

The exact preview contract supplies proposed assignments, not plan-bound prior assignments. Moved rows disclose unavailable prior seating instead of inventing a before-state. Accepted times and terms remain preserved. Native Chromium tab zoom 2.0 was verified with an isolated temporary extension/profile, including normal pointer and keyboard selection at outer 375×812; CSS viewport emulation was not counted as native zoom acceptance.

## Historical submission gates before packaging

The official offline submission check was run against this repository with Python 3.12:

    python -m harness check <repository> --track tablekeeper

It exited 1 with exactly 11 reported issues: missing README.md, missing FACTORY.md, missing authentic room.json, and missing Harness:/Model: headers in each of the four mandate files. The participant guide requires the participant to author README.md and FACTORY.md and download the whole authentic room unchanged. These files were not fabricated. The four generic mandates were verified byte-for-byte against the supplied inputs and left unchanged as explicitly instructed; `run.json` records harness/model facts but does not satisfy the mandate-header gate.

This is a functionally accepted local application delivery, not a completed public submission. Authentic room export, participant narratives, resolution of the unchanged-mandate header gate, public repository publication and event submission remain participant gates. Original implementation commits and genuine defect evidence are preserved.

### Packaging update — October 1, 2026

The preceding gate result records the pre-packaging state. The participant subsequently supplied the authentic room export and requested README/FACTORY drafts and accurate mandate headers. Those additions resolved the 11 offline gate issues; instruction bodies and accepted application source were preserved. The offline check passed both locally and from a fresh clone. The fresh clone also passed every claimed isolated stage chain and all four documented Docker runbooks. See [packaging validation](evidence/packaging-ec7d6c1/VALIDATION.md). Participant narrative review, public publication, video and event submission remain outstanding.
