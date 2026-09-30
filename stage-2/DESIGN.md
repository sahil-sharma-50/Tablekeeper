# Stage 2 UI plan

## Routes and components

- `/` renders the search form, availability grid, and reservation review panel.
- `/login` and `/signup` share the account layout, artwork frame, and labeled form.
- `/lookup` loads and cancels one reservation by reference.
- `AppShell` owns navigation, persisted theme, and the authenticated user label.
- `HomePage` composes `VisitSearch`, `AvailabilityResults`, and `ReservationPanel`.

## State and requests

- The browser calls same-origin JSON routes; login/signup save only the returned token and display name.
- Search carries a monotonically increasing request id so late responses cannot replace newer results.
- Results render every single table and declared pair for every returned slot, with availability and test IDs taken from the server response and fixture order.
- The review panel retains the selected restaurant/date/time/party/tables. An uncertain submit keeps its original body and idempotency key for retry; a confirmed refusal clears uncertainty but keeps the form editable.
- Errors and pending/success states stay beside the action that caused them. Logged-out booking remains enabled and shows `auth-error` directly below Sign in inside the review panel.
- Lookup keeps the reference and displays the server's returned status; cancellation is single-click and removes its action after success.

## Visual and accessibility rules

- Use bundled Source Sans 3, the supplied illustrations and seating icons, and retain their licenses/notices.
- Follow the warm ivory, olive, rust, and sage palette; support a remembered dark theme and OS preference.
- Use visible labels, native inputs, keyboard focus, semantic headings, and live feedback. Authentication artwork stays separate from its bordered form card.
- On desktop, bound the results list to its own scroll region and keep reservation review sticky below navigation. On mobile, move a newly selected reservation into view with a navigation offset.
- Keep browser routes and API calls on one origin. Do not add manager, recovery, series, or SMS behavior in this stage.
