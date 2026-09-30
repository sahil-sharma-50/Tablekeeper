# Stage 3 UI plan

## Routes and components

- `/` renders the search form, explained availability grid, reservation review panel, and manager policy editor when server-authorized.
- `/login` and `/signup` share the account layout, artwork frame, and labeled form.
- `/lookup` loads one reservation by reference, its accepted terms, owner-only expandable history, and recurring agreement actions/details.
- `AppShell` owns navigation, persisted theme, and the authenticated user label.
- `HomePage` composes `VisitSearch`, `AvailabilityResults`, `ReservationPanel`, and `PolicyEditor`.
- `AvailabilityResults` keeps every official single/pair cell visible and explains unavailable singles from the server's ordered capacity/occupancy rules.
- `LookupPage` composes reservation facts, considered terms, a separate `HistoryDisclosure`, and `SeriesPanel`.

## State and requests

- The browser calls same-origin JSON routes; login/signup save only the returned token and display name.
- Search requests `explain=true` and carries a monotonically increasing request id so late responses cannot replace newer results.
- Results render every single table and declared pair for every returned slot, with availability and test IDs taken from the server response and fixture order.
- The review panel retains the selected restaurant/date/time/party/tables. An uncertain submit keeps its original body and idempotency key for retry; a confirmed refusal clears uncertainty but keeps the form editable.
- Confirmation and lookup render the server's reservation revision and full accepted-terms snapshot. History loads only after owner expansion and remains visibly separate from the reservation facts.
- Policy publication submits a complete dated policy with a stable idempotency key; server membership controls access. The editor shows actual publication results and adjacent authorization/validation failures.
- Series adoption submits the chosen anchor, count, and interval with a retained original body/key on uncertainty. Series detail always comes from GET and shows current occurrences in index order, actual reservation states, references, and exception flags; each occurrence can be looked up or cancelled with the ordinary single-click action.
- Errors and pending/success states stay beside the action that caused them. Logged-out booking remains enabled and shows `auth-error` directly below Sign in inside the review panel.
- Lookup keeps the reference and displays the server's returned status; cancellation is single-click and removes its action after success.

## Visual and accessibility rules

- Use bundled Source Sans 3, the supplied illustrations and seating icons, and retain their licenses/notices.
- Follow the warm ivory, olive, rust, and sage palette; support a remembered dark theme and OS preference.
- Use visible labels, native inputs, keyboard focus, semantic headings, and live feedback. Authentication artwork stays separate from its bordered form card.
- On desktop, bound the results list to its own scroll region and keep reservation review sticky below navigation. On mobile, move a newly selected reservation into view with a navigation offset.
- Keep browser routes and API calls on one origin. Do not expose a role picker, fabricate usage metrics, expose manager access to diner history, or implement Stage 4 recovery/series-amendment behavior.
