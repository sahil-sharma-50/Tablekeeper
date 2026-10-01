# Final fresh-clone `--all` recheck

Checked 2026-10-01.

## Source and clone provenance

- Delivery revision tested: `efcfd4b1bdf10a1ada205448f1c8e0bea8aff324` (the delivery-only commit changes `DELIVERY.md`; accepted Stage 4 application revision is `a26a1cbb555b14f76c21abf42383e42f65d12543`).
- Created new ignored clone `evidence/fresh-clone/qa-final-efcfd4b-20261001-01` with `git clone --no-hardlinks`, then detached checkout at the delivery SHA.
- Verified clone SHA before and after the harness, detached state, clean tracked worktree/index, and each of the four stage folders has tracked content, `Dockerfile`, and `RUN.md`.
- The primary repository was at `efcfd4b...` when cloning. It later advanced through `fdb6a78320ce244d79e99d4d8ff48561a4b1567c` to `edc1acc87b19096c0338d81b29de599cb73a883a`; those commits changed only `.gitignore`, `run.json`, and Stage 3/4 demo README files. Application source stayed unchanged. The detached clone remained at `efcfd4b...` and clean.

## Command and outcome

Launched from `C:\Users\sahil\Desktop\BAND - Dark Factory`:

```powershell
wsl -d Ubuntu-24.04 -u bandbuilder --cd '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory' --exec bash factory/harness.sh run --track tablekeeper --repo '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory/submission/tablekeeper-v4/evidence/fresh-clone/qa-final-efcfd4b-20261001-01' --all --mode isolated --out '/mnt/c/Users/sahil/Desktop/BAND - Dark Factory/submission/tablekeeper-v4/evidence/final-efcfd4b-01'
```

The runner completed with exit code 0, run ID `final-efcfd4b-01`, mode `isolated`, and `summary.preview=true`. It reported all snapshots claimed, share 1.0, `overshoot=null`, and highest contiguous stages 1, 2, 3, and 4 respectively.

| Detached snapshot | Claimed suites passed | Failed / errors / skipped |
|---|---|---|
| Stage 1 | 120/120 | 0 / 0 / 0 |
| Stage 2 | 120/120 + 25/25 | 0 / 0 / 0 |
| Stage 3 | 120/120 + 25/25 + 7/7 | 0 / 0 / 0 |
| Stage 4 | 120/120 + 25/25 + 7/7 + 6/6 | 0 / 0 / 0 |

Report timestamps span 181.421 seconds from the Stage 1 run start through the Stage 4 run finish; the longest per-snapshot run was 50.022 seconds. Harness JSON leaves `revision` blank and labels provenance `working-tree`; the separately verified detached clone SHA provides exact source provenance.

The runner also records next-stage diagnostics against earlier snapshots; the Stage 2 probe against Stage 1 and Stage 4 probe against Stage 3 fail because those snapshots do not claim those later features. These are outside the earlier snapshots' claimed suites; their logs are retained. The harness explicitly says its checks are directional. Stage 4's shipped suite has six smoke tests and does not replace the independent API/optimizer/import/browser coverage already committed under `evidence/s4-a26a1cb-01/`.

## Timing reuse, privacy, and limits

This delivery-only change does not alter application code. Fresh `--all` does not measure runtime request/control latency; unchanged accepted Stage 4 offline/API evidence records 2 CPU/2 GiB, 841.1 ms cold launch-to-first-healthy, 12.2 ms first internal health probe, 31.6 ms maximum request, and 69.1 ms maximum across 67 control calls. These are reused measurements, not fresh `--all` results.

The harness created 31 report, count and log files under this directory. Two out-of-claim diagnostic logs contained fixture email strings; those strings were replaced with `[redacted-email]`. A post-redaction scan found no unredacted email, bearer, authorization or password values. The final Stage 4 report shows 120/120, 25/25, 7/7 and 6/6 with no failures, errors or skips.

All four application stages remain accepted. Participant-authored README/FACTORY, authentic room download, copied-mandate header and submission gates remain separate and are not established by this harness run. No application source was changed, and QA files have not been staged or committed.
