# Stage 1 receipt replay after Stage 2 pair upgrade

## Source and image

- Application source: `afdb3dc0a0eeca44583fe456186618de78525aca`.
- Stage 2 repair image: `tablekeeper-s2-afdb3dc:latest`, image ID `sha256:82f6dc5185d8417c7d31161f013b45ff85c525246e810680fc368188de113558`.
- Stage 1 source image: `tablekeeper-s1-79f39e1:latest`, image ID `sha256:ee926b5a55b25c88d653e66b00c72813ac1e5d576f15c30a1a53d90fafa9ceb5`.
- Both services ran in new disposable containers with 2 CPU / 2 GiB limits; host ports 18086 (Stage 2) and 18087 (Stage 1). No existing test service was reset.
- Fresh Stage 2 container launch-to-first-healthy was 1298.5 ms. Image IDs and timing are in `runtime-startup.log`.

## Check

The new independent case in `checks/stage2_independent.py` performed this sequence:

1. On Stage 1, create a reservation and save the exact create response.
2. Move it from `t_2` to `t_3`, then back to `t_2`, saving both exact move responses and their request keys/bodies.
3. Cancel the reservation. Confirm the original create and both move keys replay with the original response JSON after cancellation.
4. Export the populated Stage 1 state, add Stage 2 combinable pairs, and import that state into a fresh Stage 2 service.
5. Confirm the Stage 2 read shape has `table_ids` for the imported reservation, then create a later reservation to change resource occupancy.
6. Replay the original Stage 1 create and both move requests. All return HTTP 200 and JSON equal to the respective original Stage 1 response; the receipt bodies retain the Stage 1 response shape without `table_ids`.

Command:

```powershell
python checks/stage2_independent.py --base-url http://127.0.0.1:18086 --stage1-url http://127.0.0.1:18087 --receipt-result evidence/s2-afdb3dc-followup-01/receipt-pair-upgrade.json
```

Result: PASS. Create response equality is `true`; both move response equality checks are `true`; source create/move statuses were 201, source replay statuses after cancellation were 200, Stage 2 pair-upgrade import was 204, the later resource-changing write was 201, and all three post-upgrade receipt replays were 200. Full output is in `stage2-receipt-recheck.log`; the redacted structured result is in `receipt-pair-upgrade.json`. The populated export, auth token and receipt bodies were not written to disk.

The official isolated Stage 1 120/120 and Stage 2 25/25 result on this same exact source remains in `evidence/s2-afdb3dc-01/`. Its report revision field is blank; the pre-run workspace HEAD was recorded as the SHA above. It was not rerun because neither application source nor official input changed. Browser lost-response recovery across the populated Stage 1 import was independently exercised on the exact afdb3dc image earlier; see `evidence/s2-afdb3dc-01/ui-browser-upgrade.json`.

This receipt check passes. Overall Stage 2 remains unaccepted due the separate UI failures and unproven usability items recorded in `COVERAGE.md` and `evidence/s2-afdb3dc-01/qa-recheck.md`.
