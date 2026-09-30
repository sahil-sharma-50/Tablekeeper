# Stage 1 charset repair recheck

## Revision and authority

- Application revision: `79f39e13095f011fe9baadc3f17bf59636a1bcba`.
- Parent: `dffa0df05aac0b6053d790ef964ae467c8199cb5`.
- Requirements: `requirements.md` at immutable revision `a9c7024bfdaf39cdb8ae25018862d25c6719550b`; LF-normalized task digest `370f2b750a2e221f064f9452d0de6b716a50fc00f2bfea98f290e6abefd8489b`.
- `git rev-parse HEAD` was the application revision above. The commit changes only `stage-1/server/app.py` and `stage-1/checks/backend/check_stage1.py`. The app diff changes JSON response media-type wiring and response annotations; no reservation, occupancy, import/export, or time logic changed.
- `git show --check` passed.

## Official isolated Stage 1

Command, from `C:\Users\sahil\Desktop\BAND - Dark Factory`:

```powershell
wsl -d Ubuntu-24.04 -u bandbuilder --exec bash factory/harness.sh run --track tablekeeper --repo '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory/submission/tablekeeper-v4' --stage 1 --mode isolated --out '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory/submission/tablekeeper-v4/evidence/s1-79f39e1-01'
```

Stage 1 passed all 120 official tests: 12 health/reset/auth, 37 reservations, 18 restaurant/availability, 20 retries/time input, 20 sample, and 13 seeded-state. The report identifies `provenance: working-tree` and leaves its revision field blank; the full checked-out SHA is recorded above from `git rev-parse HEAD`. The only pytest warning is that the challenge directory is read-only and cannot store `.pytest_cache`.

The harness also emitted its normal next-stage probe. Stage 2 stops at direct navigation to `/` because this Stage 1 backend has no Stage 2 UI. This is outside the claimed Stage 1 result; `report.json` records Stage 1 pass and highest contiguous stage 1. Its full log is retained separately.

## Independent response and runtime checks

Build command:

```powershell
docker build --tag tablekeeper-stage-1:qa-79f39e1 --file stage-1\Dockerfile stage-1
```

The image ID was `sha256:ead8bb57f807f7c266f4e89fd3a4e62e4f71a35df2939f63b707260935a43fc6`. The unique tag prevents accidental reuse of the pre-repair `tablekeeper-stage-1:latest` image.

Command:

```powershell
python checks\stage1_runtime_probe.py --image tablekeeper-stage-1:qa-79f39e1
```

The probe ran all 11 groups in a fresh container with `--network none`, 2 CPU, 2 GiB, default `PORT=8080`, and bundled Berlin/New York timezone data. Cold container launch to the first healthy response was 752.8 ms. It recorded 385 requests (maximum 30.4 ms) and 43 test-control calls (maximum 943.3 ms), all below their limits.

The response checks independently confirmed exact `application/json; charset=utf-8` on:

- `/health`, `/restaurants`, `/auth/login`, and `/auth/signup`.
- Reservation create and move success responses (201).
- Protected-route 401, API and generic-path 404, conflict 409, and validation 422 errors.
- `/_test/export`.

`/_test/reset` and `/_test/import` both returned empty 204 bodies with no content type. `/docs` remained non-JSON with `text/html; charset=utf-8`. The 10 additional groups passed 50-way overlapping operations, same-key races, strict types and precedence, key boundaries and parsed JSON equality, PATCH behavior, move swaps/rollback/precedence, Berlin/New York DST and absolute durations, and populated import with retained sessions and receipts.

The exact after headers and regression output are in `offline-runtime.log`. The before-repair raw responses remain in `../s1-038a02b-followup/content-type-health.log`, `content-type-restaurants.log`, and `content-type-error.log`. No Stage 1 application files were changed during QA.
