# Submission packaging validation

Date: October 1, 2026. Checked revision: `ec7d6c1a4f34cf7ac2518d5086f1011bd7481aaf`, cloned with `git clone --no-local` to a new temporary directory. The clone was clean. SHA-256 of cloned `room.json` matched the participant-supplied `Tablekeeper.json`. Application source under all four stages and authored checks was unchanged from the pre-packaging revision `a508ac9958ae3fc5c8a07b16f222b9bc47bd4e25`.

## Official harness

Using the previously pinned official challenge and its Python 3.12 environment, run from the challenge checkout:

```sh
python -m harness check /absolute/path/to/fresh-clone --track tablekeeper
python -m harness run --track tablekeeper --repo /absolute/path/to/fresh-clone --all --mode isolated --out /absolute/path/to/new-output
```

Both commands exited 0. The offline check passed its applicable packaging gates. The isolated run passed each snapshot's claimed suites:

| Snapshot | Passed checks | Highest contiguous stage |
| --- | ---: | ---: |
| Stage 1 | 120 | 1 |
| Stage 2 | 145 | 2 |
| Stage 3 | 152 | 3 |
| Stage 4 | 158 | 4 |

There were no claimed failures, errors or skips. Earlier snapshots' probes of the next stage failed as expected; those genuine logs are retained. The runner labels results partial, preview/directional, and leaves its revision field blank. Clone provenance above establishes the tested revision, not that blank field. [Summary](isolated/summary.json) and per-stage reports/counts/logs are retained under [isolated/](isolated/).

## Each RUN.md

All four snapshots were built independently from the fresh clone using their documented image names, ports and `PORT` values. For automation, containers were detached, given unique validation names, and bound to loopback. Stage 1 and Stage 2 were run separately because both document port 8102; Stage 3 used 8103 and Stage 4 used 8104.

All builds and `/health` checks passed. Stages 2–4 returned successful, nonempty responses for their main/login/signup/lookup routes, font and three illustrations. Their opt-in demo reset returned 204 and populated restaurant data. This runbook check is not a substitute for browser interaction checks; the isolated shipped suites separately exercised the UI. Every validation container was stopped afterward.

The exact [runbook checker used](runbooks.py) uses only Python's standard library and the Docker CLI. It retains the original local paths; replace its `clone`, `out` and `source` paths with your fresh clone, a new external output directory and the original repository before reuse. [Runbook results](runbooks.json) record the observed outcomes. This record and its README/facts links were added after testing; they change no application source.
