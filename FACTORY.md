# Tablekeeper factory

This factory separates delivery coordination, implementation and independent verification into four BAND Desktop seats. The standing mandates describe reusable working roles; the product, paths, stage contracts and visual brief live in the initial task, preserved in [requirements.md](requirements.md).

Participant: Sahil Sharma. Submitted run: [Tablekeeper](https://app.band.ai/sessions/018b7708-b06b-404a-8c00-2cc53c64a9d3), exported as [room.json](room.json). This narrative was drafted with Codex assistance from the recorded run and requires participant review; it does not claim that tooling authored the participant's personal experience.

## Seats

| Seat / handle | Harness / model / effort | Ownership |
| --- | --- | --- |
| Engineering Lead / `sahilatfau/engineering-lead` | Codex app-server / `gpt-6.1-sol` / medium | Requirement coverage, assignments, integration, stage copying and exclusive commit-token grants; no application source. |
| Backend Engineer / `sahilatfau/backend-engineer` | Codex app-server / `gpt-6-luna` / xhigh | Service, storage, domain and algorithm source; focused backend checks. |
| Frontend Engineer / `sahilatfau/frontend-engineer` | Codex app-server / `gpt-6-luna` / xhigh | Interface, accessibility, visual assets, Docker/build files and runbooks. |
| QA Engineer / `sahilatfau/qa-engineer` | Codex app-server / `gpt-6-luna` / xhigh | Independent checks, coverage matrix and revision-attributed evidence; no application repairs. |

The generic instructions are in [mandates/](mandates/), with accurate harness/model headers added during submission packaging. Their original standing instruction bodies are retained unchanged. [run.json](run.json) records subscription authentication; no API credentials are included. There was no designer seat and no nested agent recruitment in this run.

## Stand up the factory

1. Install BAND Desktop and its CLI/Codex integration. Authenticate BAND and Codex using your own account. Install Git, Docker and the official Python 3.12 harness. The original machine also used Node/npm and Ubuntu-24.04 WSL2; Windows frontend commands used `npm.cmd` without changing execution policy.
2. Create a fresh, independent Git workspace and four BAND-owned Codex seats with the roles, model IDs and reasoning efforts above. Set each seat's instructions from its corresponding mandate file. Model availability depends on your account; record any substitutions for a new run.
3. Configure each seat's working directory to that workspace. The original runtime settings were subscription authentication, approval `never`, sandbox `danger-full-access` and compaction at 80,000 input tokens. Use a disposable workspace and review that access choice before reproducing it. Do not include credentials in instructions or task messages.
4. Set BAND room-activity mirroring to `off` before dispatch. Explicit addressed handoffs, task events and committed evidence remain the collaboration record. Earlier development attempts hit the room's 10,000-message cap with full telemetry; this setting avoids flooding the submitted room with every tool/reasoning event. Do not delete or fabricate room history to manage volume.
5. Create one human-owned room with the four seats. Supply the complete task and specifications in one initial lead dispatch, using the new workspace and actual handles. Approved images/fonts/icons are static input assets, not application code. For this product, assets and their provenance are bundled in the stage frontends; a different product can supply different assets without changing the mandates.
6. Leave the seats to assign, implement, inspect, repair and extend the four snapshots. Explicit `@handle` mentions deliver handoffs; ordinary final prose does not substitute for routing. The participant downloads the full completed room through BAND's console, without synthesizing an export.

## Delivery loop and acceptance

The lead reads the full specification, creates a requirement-to-evidence matrix and grants non-overlapping file ownership. Engineers agree interfaces directly. Handoffs carry requirements, constraints, absolute workspace, owned paths, runnable commands, results, checked SHA and unresolved gaps. A digest/file reference preserves acknowledged immutable details without repeatedly copying a full unchanged specification into messages.

Exactly one seat owns the Git commit token at a time. It stages only explicit completed owned paths, commits, reports the full revision and releases the token. QA then checks that committed implementation independently, using both the shipped suites and additional checks derived from requirements. Findings go to the responsible engineer and lead with the trigger, expected/actual behavior, command and revision. The engineer repairs the shared cause; QA rechecks the committed fix. The lead copies an accepted snapshot forward only when writers are idle, preserving earlier stages.

Waiting seats end their turns and resume on addressed inbound messages rather than polling. Duplicate inbound messages are settled without duplicate handoffs. Documentation-only commits reuse accepted application evidence when ancestry and unchanged source establish that it remains applicable. Final acceptance includes a clean detached clone and isolated evaluation of every snapshot.

This design keeps integration decisions separate from application changes and QA separate from implementation. Serialized commits avoid races in the shared Windows/WSL Git index. The tradeoff is a sequential stage dependency and review overhead: independent acceptance can delay copying forward, but it prevents a later stage from masking an earlier defect.

## Actual failures caught and repaired

| Finding | Repair and independent evidence |
| --- | --- |
| Stage 1 JSON response charset defect | Backend repair accepted at `79f39e1`; QA checked success/error JSON, empty 204 and HTML. Original defect and recheck are recorded in [DELIVERY.md](DELIVERY.md). |
| Stage 2 imported receipt replay and visible-feedback defects | Backend repaired receipt preservation; frontend repaired typography/artwork, signup fit, mobile feedback and stale refusal state. Independent API/browser and native 200% zoom checks accepted `64d0f50`. |
| Stage 3 reversed-pair no-op changed revisions/history | Backend canonicalized pair order before shared PATCH/collective-move comparisons. QA verified unchanged terms/history, aggregate counters and series exception flags at `bc58262`. |
| Stage 4 native-zoom mobile overflow and header pointer interception | Frontend repaired minimum widths, narrow layouts and interaction scroll/focus. QA checked normal pointer/keyboard selection and all 16 zoom layout samples at `a26a1cb`. |

These are retained observed failures, not invented disagreements. [COVERAGE.md](COVERAGE.md), [DELIVERY.md](DELIVERY.md), independent [checks/](checks/) and [evidence/](evidence/) link their commands and outcomes. The completed room and Git history establish the collaboration; a narrative alone is not teamwork evidence.

## Measured outcome and cost

All four snapshots were independently accepted. Final detached-clone isolated `--all` passed the claimed suite chains: 120; 120+25; 120+25+7; and 120+25+7+6, with no claimed failures, errors or skips. The final accepted Stage 4 application revision is `a26a1cbb555b14f76c21abf42383e42f65d12543`. The final check's report timestamps span **181.421 seconds**, with a longest snapshot run of **50.022 seconds**. See [final QA evidence](evidence/final-efcfd4b-01/qa-final-recheck.md).

The first implementation commit to the demo-guide audit commit spans **14 hours 19 minutes 25 seconds**, from September 30, 2026 at 11:58:16 to October 1 at 02:17:41 Europe/Berlin. This is elapsed repository history including idle time, not measured active compute time or the entire preparation period. Provider token usage and actual model billing were not measured; subscription access is not a cost measurement. No dollar estimate is fabricated.

Accepted Stage 4 runtime sampling, reused for unchanged backend source: outbound network disabled, 2 CPU/2 GiB, cold first-health **841.1 ms**, maximum normal request **31.6 ms** across 247 requests and maximum control call **69.1 ms** across 67 controls. Across other accepted stage checks, the largest recorded normal request was **61.4 ms** and control call **1,729.2 ms**. These sampled timings are not latency guarantees and were not measured by the final `--all` run. Full context is in [SUBMISSION-FACTS.md](SUBMISSION-FACTS.md).

## Limits and submission provenance

The official runner labels results preview/directional; shipped tests are partial, and Stage 4's six checks are smoke coverage. Independent optimizer enumeration, concurrency, rollback, imports, DST, privacy, native zoom and browser recovery checks supplement them but cannot establish hidden-suite perfection. Earlier-stage future-stage probe failures are retained separately from claimed-stage results.

The seating preview supplies proposed assignments, not plan-bound prior assignments. The UI discloses unavailable prior seating rather than inventing a before-state. Accepted times and terms remain unchanged. Assets are bundled, no runtime network is needed, and builds require registry access. No SMS provider, payments, invented manager metrics or self-service manager role is added. State is ephemeral across restart, with independently checked export/import compatibility.

After the autonomous implementation run, the participant supplied the authentic room download and requested documentation/mandate metadata packaging. The original export bytes are preserved as `room.json`; header additions do not rewrite the standing instruction bodies or imply the new headers were present during the run. Historical paths in evidence describe the original workspace before relocation. No application source was changed during this packaging step. Public publication, video/presentation and final event submission remain separate participant actions.
