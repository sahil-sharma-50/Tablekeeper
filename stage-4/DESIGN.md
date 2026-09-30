# Tablekeeper Stage 4 UI plan

## Components and routes

- Keep booking, lookup, confirmation, history, policies, and recurring visits on the existing same-origin routes.
- Add a Service recovery navigation anchor to the manager section on `/`; show the section only when restaurant detail authorizes the signed-in account.
- `SeatingRecovery` owns closure inputs, immutable preview, apply, and recovery feedback. The existing availability and lookup views continue to read server state after application.
- `SeriesPanel` keeps current occurrences in index order and adds an `AmendSeries` form for a local time change from a chosen occurrence onward.

## State and requests

- Preview sends `{table_id, from, to}` with an idempotency key and only stores a plan. The UI displays the server's revision, closure, ordered assignments, moved count, and unused seats. After labels come from the proposed table IDs; a before label is shown only if a plan-bound authorized source supplies it, otherwise the UI says that prior assignment is unavailable.
- Apply sends `{}` with its own stable key and the exact `plan_id`. A stale-plan refusal discards the preview and asks for a new one. An uncertain preview or apply keeps its original body/key and exposes only a same-request retry; it never claims that no change occurred.
- Series amendment sends `{expected_revision, from_index, local_time}` with a retained key/body on uncertainty. The server response replaces current series state. Cancelled and independently changed occurrences remain visible and unchanged.
- Keep the existing typography, palette, themes, table cells, feedback reveal/focus, one-click cancellation, and responsive layout. Recovery and amendment status stays beside its action; accepted terms and booking times remain those returned by the service.
