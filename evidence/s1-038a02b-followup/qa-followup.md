# Stage 1 independent follow-up

## Revision and scope

- Application source checked: `038a02b54df4cabf76ebfe3e00e28dede664ba57`, parent `d0a2d155ed1e76132929de146ad85ccbc89ff958`.
- `git rev-parse HEAD` before follow-up work was `e0423b841aec401b8e9a172fa8bfbb0d61149afc`; `git diff 038a02b54df4cabf76ebfe3e00e28dede664ba57 -- stage-1` is empty. The application source has not changed.
- Requirements remain `requirements.md` at immutable bootstrap revision `a9c7024bfdaf39cdb8ae25018862d25c6719550b`, acknowledged normalized task digest `370f2b750a2e221f064f9452d0de6b716a50fc00f2bfea98f290e6abefd8489b`.
- The official Stage 1 result is reused from the same source SHA, not rerun: 120/120 passed. Per-file counts are 12 `test_health_reset_auth.py`, 37 `test_reservations.py`, 18 `test_restaurants_availability.py`, 20 `test_retries_time_input.py`, 20 `test_sample.py`, and 13 `test_seeded_state.py`; see `../s1-038a02b-01/report.json` and `stage1.log`.
- The original `qa-run.md` records the evidence available at the first handoff. This follow-up closes its explicitly listed independent-coverage gaps; `COVERAGE.md` is the current assessment.

## Final independent runs

Mapped-container command, from the repository root. The independent client sends JSON as `application/json; charset=utf-8`:

```powershell
python checks/stage1_independent.py --base-url http://127.0.0.1:8102 --source-url http://127.0.0.1:8103
```

The target and export source were separate containers built from the pinned Stage 1 image, mapped to host ports 8102 and 8103. The final run passed all 10 groups: 50 overlapping create requests; 50 identical-key create retries; 50 identical move retries; strict types and idempotency precedence; key boundaries and parsed JSON equality; single-reservation PATCH behavior; atomic swap and rollback; move boundaries, order, ownership and precedence; Berlin/New York DST; and populated export/import. It recorded 373 normal requests (maximum 51.2 ms) and 39 test-control calls (maximum 962.7 ms). Full output: `cross-container-final-6.log`.

Fresh-container offline/resource command:

```powershell
python checks/stage1_runtime_probe.py
```

The probe starts a fresh container with `--network none --cpus=2 --memory=2g`, leaves `PORT` unset, times from before `docker run` until the first `200 {"status":"ok"}` health response, confirms Docker's 2 CPU / 2 GiB limits and default `PORT=8080`, verifies bundled Berlin and New York zone data, then runs the same independent checks in that container. It passed all 10 groups. Startup was 1,128.6 ms against 60,000 ms; among 373 normal requests the maximum was 29.1 ms, and among 39 test controls the maximum was 1,003.6 ms. Full output: `offline-runtime-final-6.log`.

Both runs stayed within the per-request limits (5 seconds normal, 10 seconds for controls); the 50-way tests produced no 5xx responses. Earlier `*-attempt-*` logs retain corrected QA fixture errors and are not application failures.

## Requirement-to-check reconciliation

The six shipped Stage 1 files above cover health/reset/auth, reservation validation and ownership, public restaurant/availability behavior, cancellation, sample flows, seeded state, DST, and the original 10-client/idempotency examples. The independent checks add the specific cases that were absent or thin in those tests:

- Runtime and model §§2–4: offline cold-start and limits; independent overlapping writes; past-date booking; acceptance of 64-character fixture IDs plus the shipped rejection above 64; fixture timezone and opening/closing behavior.
- Errors and authentication §§5–6: exact `{error:{code,message}}` shape on induced failures; strict JSON types, party/time/query formats, public and protected access; source inspection confirms per-user passwords use salted scrypt and constant-time verification.
- Idempotency §7 on both write paths: absent, empty, 1-, 255- and 256-character keys; parsed JSON key-order equality; user and path scope; body-reuse and validation precedence; failed-key reuse; 50 concurrent identical requests with exactly one 201 and 49 identical 200 replays; original receipts after later state changes, cancellation and import.
- Availability, reservations and amendment §§8–9: capacity, fixture order, full and closed slots, overlap and adjacency, past dates, every specified Berlin/New York spring and fall transition, first-fold choice, absolute duration, and both DST zones offline. PATCH tests verify each field subset, empty no-op, identity preservation, old-slot release, failed-change rollback, cutoff based on the current start, caller ownership and cancelled refusal.
- Export/import §10: populated cross-container transfer and exact snapshot state equality; retained accounts, login, old bearer token, reservation/move receipts, statuses, IDs, timestamps and failed-key reuse; repeated replacement; malformed JSON, non-object envelope, missing/wrong envelope fields and invalid state all preserve a populated destination; reset clears imported state.
- Atomic moves §11: 0/1/8/9 items, invalid shapes, duplicates, table/time/party subsets, unknown fields, mixed owners/restaurants, no-op and input ordering, 404/422 precedence in both item orders, cutoff-before-validation, conflict with an unlisted booking, all-or-nothing swap/rollback, failed-key reuse, user-scoped and concurrent idempotency, cancellation replay and retained imported receipt.

## Blocking protocol defect: JSON response charset

Requirements §3.4 specify `application/json; charset=utf-8` for JSON responses. The pinned service returns `content-type: application/json` without the required charset parameter on successful and error responses. This was reproduced from the mapped container with:

```powershell
curl.exe --include --silent --show-error http://127.0.0.1:8102/health
curl.exe --include --silent --show-error http://127.0.0.1:8102/restaurants
curl.exe --include --silent --show-error http://127.0.0.1:8102/no-such-path
```

Expected header: `Content-Type: application/json; charset=utf-8`.

Actual header on all three: `content-type: application/json`. Full raw responses are in `content-type-health.log`, `content-type-restaurants.log` and `content-type-error.log`. No application source was changed. Stage 1 acceptance therefore remains blocked on this concrete contract defect; the other listed Stage 1 requirements pass. Recheck the repair at its exact committed source SHA.

## Commands and evidence index

- Official command and full 120-test output: `../s1-038a02b-01/qa-run.md`, `../s1-038a02b-01/stage1.log`, `../s1-038a02b-01/report.json`.
- Independent check source: `../../checks/stage1_independent.py`.
- Offline launch-to-health probe source: `../../checks/stage1_runtime_probe.py`.
- Requirement matrix: `../../COVERAGE.md`.
- Final mapped-container output: `cross-container-final-6.log`.
- Final offline/resource output: `offline-runtime-final-6.log`.
- Charset reproductions: `content-type-health.log`, `content-type-restaurants.log`, `content-type-error.log`.
