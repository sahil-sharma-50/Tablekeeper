#!/usr/bin/env python3
"""Independent Stage 4 API checks; use only against disposable services."""
from __future__ import annotations

import argparse
import concurrent.futures
import copy
import datetime as dt
import json
import uuid
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import stage1_independent as s1
import stage3_independent as s3
from stage4_optimizer import Booking, Closure, Occupancy, optimize


RID = "r_stage4_qa"
OTHER_RID = "r_stage4_other_qa"
BERLIN = ZoneInfo("Europe/Berlin")


def key(label: str) -> str:
    return f"s4-{label}-{uuid.uuid4().hex}"


def fixture(*, cutoff: int = 0, other: bool = False,
            capacities: dict[str, int] | None = None,
            maximum: bool = False) -> tuple[dict, dict, dict]:
    data, manager, diner = s3.fixture(pair=True, cutoff=cutoff)
    restaurant = data["restaurants"][0]
    restaurant["id"] = RID
    if capacities:
        for table in restaurant["tables"]:
            if table["id"] in capacities:
                table["capacity"] = capacities[table["id"]]
    if maximum:
        restaurant["tables"].extend(
            {"id": f"t_{index}", "label": chr(64 + index), "capacity": 2}
            for index in range(4, 7))
        restaurant["combinable"] = [
            ["t_1", "t_2"], ["t_2", "t_3"],
            ["t_3", "t_4"], ["t_4", "t_5"],
        ]
        restaurant["reservation_duration_minutes"] = 30
    if other:
        second = copy.deepcopy(restaurant)
        second["id"] = OTHER_RID
        second["name"] = "Independent QA second restaurant"
        data["restaurants"].append(second)
    return data, manager, diner


def reset(base: str, *, cutoff: int = 0, other: bool = False,
          capacities: dict[str, int] | None = None, maximum: bool = False):
    data, manager, diner = fixture(cutoff=cutoff, other=other,
                                   capacities=capacities, maximum=maximum)
    s1.reset(base, data)
    return manager, diner, s1.local_date(14)


def login(base: str, manager: dict, diner: dict) -> tuple[str, str]:
    return s1.login(base, manager), s1.login(base, diner)


def book(base: str, token: str, date: str, *, restaurant_id: str = RID,
         table: str = "t_2", at: str = "19:00", party: int = 4,
         request_key: str | None = None) -> dict:
    body = {"restaurant_id": restaurant_id, "table_id": table,
            "starts_at_local": f"{date}T{at}", "party_size": party}
    return s1.expect(s1.call(base, "/reservations", "POST", body,
                             token=token, key=request_key or key("book")), 201).body


def export_state(base: str) -> dict:
    return s1.expect(s1.call(base, "/_test/export"), 200).body["state"]


def restaurant_revision(base: str, restaurant_id: str = RID) -> int:
    row = next(row for row in export_state(base)["restaurants"]
               if row["id"] == restaurant_id)
    return row["restaurant_revision"]


def detail(base: str, reference: str, token: str) -> dict:
    return s1.expect(s1.call(base, f"/reservations/{reference}", token=token), 200).body


def reservation_owner(base: str, reference: str) -> str:
    return next(row["user_id"] for row in export_state(base)["reservations"]
                if row["reference"] == reference)


def history(base: str, reference: str, token: str) -> dict:
    return s1.expect(s1.call(base, f"/reservations/{reference}/history",
                             token=token), 200).body


def series_read(base: str, series_id: str, token: str) -> dict:
    return s1.expect(s1.call(base, f"/series/{series_id}", token=token), 200).body


def shift_series_dates_in_import(base: str, series_id: str,
                                 first_date: dt.date) -> dict:
    """Move a valid persisted series into its accepted cutoff window in test state."""
    envelope = s1.expect(s1.call(base, "/_test/export"), 200).body
    state = envelope["state"]
    series = next(row for row in state["series"]
                  if row["series_id"] == series_id)
    restaurant = next(row for row in state["restaurants"]
                      if row["id"] == series["restaurant_id"])
    zone = ZoneInfo(restaurant["timezone"])
    reservations = {row["reference"]: row for row in state["reservations"]}
    for occurrence in series["occurrences"]:
        reservation = reservations[occurrence["reference"]]
        scheduled = dt.datetime.fromisoformat(
            occurrence["scheduled_starts_at_local"])
        scheduled_date = first_date + dt.timedelta(
            weeks=occurrence["index"] * series["interval_weeks"])
        local = f"{scheduled_date.isoformat()}T{scheduled:%H:%M}"
        starts = dt.datetime.fromisoformat(local).replace(tzinfo=zone).astimezone(dt.timezone.utc)
        ends = starts + dt.timedelta(
            minutes=reservation["accepted_terms"]["reservation_duration_minutes"])
        occurrence["scheduled_starts_at_local"] = local
        reservation["starts_at_local"] = local
        reservation["starts_at"] = starts.isoformat(timespec="seconds")
        reservation["ends_at"] = ends.isoformat(timespec="seconds")
        for event in reservation["history"]:
            if event["event"] == "created":
                for change in event["changes"]:
                    if change["field"] == "starts_at_local":
                        change["to"] = local
    s1.expect(s1.call(base, "/_test/import", "POST", envelope), 204)
    return series


def local_instant(date: str, clock: str) -> dt.datetime:
    return dt.datetime.fromisoformat(f"{date}T{clock}").replace(tzinfo=BERLIN)


def offset_iso(date: str, clock: str) -> str:
    return local_instant(date, clock).isoformat()


def replan(base: str, token: str, *, date: str, table: str = "t_2",
           start: str = "18:00", end: str = "23:00",
           restaurant_id: str = RID, request_key: str | None = None,
           status: int = 201) -> dict:
    body = {"table_id": table, "from": offset_iso(date, start),
            "to": offset_iso(date, end)}
    return s1.expect(s1.call(base, f"/restaurants/{restaurant_id}/replans", "POST",
                             body, token=token,
                             key=request_key or key("replan")), status).body


def _availability(base: str, date: str, party: int = 4) -> dict:
    query = urlencode({"restaurant_id": RID, "date": date,
                       "party_size": party, "explain": "true"})
    return s1.expect(s1.call(base, "/availability?" + query), 200).body


def _observation(base: str, token: str, refs: list[str], date: str) -> dict:
    return {
        "restaurant_revision": restaurant_revision(base),
        "reservations": [detail(base, ref, token) for ref in refs],
        "history": [history(base, ref, token) for ref in refs],
        "availability": _availability(base, date),
    }


def _oracle_inputs(base: str, token: str, refs: list[str], date: str,
                   closure: Closure) -> tuple[list[Booking], tuple[str, ...], tuple[tuple[str, ...], ...]]:
    restaurant = next(row for row in export_state(base)["restaurants"]
                      if row["id"] == RID)
    singles = tuple(table["id"] for table in restaurant["tables"])
    pairs = tuple(tuple(pair) for pair in restaurant.get("combinable", []))
    bookings: list[Booking] = []
    for reference in refs:
        row = detail(base, reference, token)
        starts_at = dt.datetime.fromisoformat(row["starts_at_local"]).replace(tzinfo=BERLIN)
        duration = row["accepted_terms"]["reservation_duration_minutes"]
        bookings.append(Booking(
            reference=reference,
            starts_at=starts_at,
            ends_at=starts_at + dt.timedelta(minutes=duration),
            party_size=row["party_size"],
            table_ids=tuple(row["table_ids"]),
            accepted_capacities=row["accepted_terms"]["capacities"],
        ))
    assert all(closure.starts_at.date().isoformat() == date for _ in bookings)
    return bookings, singles, pairs


def check_replan_guards(base: str) -> None:
    manager, diner, date = reset(base)
    mgr, din = login(base, manager, diner)
    body = {"table_id": "t_2", "from": offset_iso(date, "18:00"),
            "to": offset_iso(date, "23:00")}
    path = f"/restaurants/{RID}/replans"
    s1.expect(s1.call(base, path, "POST", body, key=key("anonymous")), 401)
    s1.expect(s1.call(base, path, "POST", body, token=din,
                      key=key("diner")), 403)
    s1.expect(s1.call(base, path, "POST", body, token=mgr),
              400, "missing_idempotency_key")
    no_offset = {**body, "from": f"{date}T18:00", "to": f"{date}T23:00"}
    s1.expect(s1.call(base, path, "POST", no_offset, token=mgr,
                      key=key("offset")), 422, "validation_failed")
    reversed_interval = {**body, "from": body["to"], "to": body["from"]}
    s1.expect(s1.call(base, path, "POST", reversed_interval, token=mgr,
                      key=key("interval")), 422, "validation_failed")
    unknown_table = {**body, "table_id": "t_missing"}
    s1.expect(s1.call(base, path, "POST", unknown_table, token=mgr,
                      key=key("table")), 404)
    s1.expect(s1.call(base, f"/restaurants/{RID}-missing/replans", "POST",
                      body, token=mgr, key=key("restaurant")), 404)
    plan = replan(base, mgr, date=date, request_key=key("apply-guard-plan"))
    apply_path = f"/restaurants/{RID}/replans/{plan['plan_id']}/apply"
    s1.expect(s1.call(base, apply_path, "POST", {}, key=key("apply-anon")), 401)
    s1.expect(s1.call(base, apply_path, "POST", {}, token=din,
                      key=key("apply-diner")), 403)
    s1.expect(s1.call(base,
                      f"/restaurants/{OTHER_RID}/replans/{plan['plan_id']}/apply",
                      "POST", {}, token=mgr, key=key("wrong-restaurant-plan")), 404)
    s1.expect(s1.call(base,
                      f"/restaurants/{RID}/replans/missing-plan/apply",
                      "POST", {}, token=mgr, key=key("unknown-plan")), 404)
    print("PASS Stage 4 replan auth, key, offset, interval and unknown-resource guards")


def check_replan_bypasses_cutoff(base: str) -> None:
    manager, diner, _ = reset(base, cutoff=10080)
    mgr, _ = login(base, manager, diner)
    date = s1.local_date(2)
    row = book(base, mgr, date, table="t_2", at="19:00", party=4)
    plan = replan(base, mgr, date=date, request_key=key("cutoff-repair"))
    assert len(plan["assignments"]) == 1
    assignment = plan["assignments"][0]
    assert assignment["reference"] == row["reference"]
    assert assignment["changed"] is True and "t_2" not in assignment["table_ids"]
    applied = s1.expect(s1.call(
        base, f"/restaurants/{RID}/replans/{plan['plan_id']}/apply", "POST", {},
        token=mgr, key=key("cutoff-repair-apply")), 201).body
    assert applied["reservations"][0]["reference"] == row["reference"]
    print("PASS Stage 4 manager repair succeeds inside the accepted cancellation cutoff")


def check_replan_oracle_preview_apply(base: str) -> None:
    manager, diner, date = reset(base, cutoff=10080, other=True)
    mgr, _ = login(base, manager, diner)
    first = book(base, mgr, date, table="t_2", at="19:00", party=4)
    second = book(base, mgr, date, table="t_2", at="20:30", party=2)
    series_created = s1.expect(s1.call(base, "/series", "POST", {
        "anchor_reference": first["reference"], "count": 2,
        "interval_weeks": 1}, token=mgr, key=key("replan-series")), 201).body
    series_before = series_read(base, series_created["series_id"], mgr)
    refs = [first["reference"], second["reference"]]
    closure = Closure("t_2", local_instant(date, "18:00"),
                      local_instant(date, "23:00"))
    before = _observation(base, mgr, refs, date)
    owners_before = {reference: reservation_owner(base, reference) for reference in refs}
    request_key = key("preview")
    plan = replan(base, mgr, date=date, request_key=request_key)
    after = _observation(base, mgr, refs, date)
    assert before == after, "preview changed reservations, history, occupancy or revision"

    bookings, singles, pairs = _oracle_inputs(base, mgr, refs, date, closure)
    expected = optimize(singles, pairs, bookings, proposed=closure)
    assert expected is not None
    got_assignments = plan["assignments"]
    expected_rows = [
        {"reference": reference,
         "table_ids": list(expected.assignments[reference]),
         "changed": frozenset(expected.assignments[reference]) !=
                    frozenset(next(b.table_ids for b in bookings if b.reference == reference))}
        for reference in sorted(refs)
    ]
    assert got_assignments == expected_rows, (got_assignments, expected_rows)
    assert plan["moved_count"] == expected.moved_count
    assert plan["unused_seats"] == expected.unused_seats
    replay = s1.expect(s1.call(base, f"/restaurants/{RID}/replans", "POST", {
        "table_id": "t_2", "from": offset_iso(date, "18:00"),
        "to": offset_iso(date, "23:00")}, token=mgr, key=request_key), 200).body
    assert replay == plan

    # A separately applied closure at another restaurant does not stale this plan.
    other_plan = replan(base, mgr, date=date, restaurant_id=OTHER_RID,
                        request_key=key("other-restaurant-plan"))
    assert other_plan["assignments"] == []
    s1.expect(s1.call(base,
                      f"/restaurants/{OTHER_RID}/replans/{other_plan['plan_id']}/apply",
                      "POST", {}, token=mgr, key=key("other-restaurant-apply")), 201)
    original_revision = restaurant_revision(base)
    apply_path = f"/restaurants/{RID}/replans/{plan['plan_id']}/apply"
    apply_key = key("apply")
    applied = s1.expect(s1.call(base, apply_path, "POST", {}, token=mgr,
                                key=apply_key), 201).body
    assert [row["reference"] for row in applied["reservations"]] == sorted(refs)
    assert applied["restaurant_revision"] == original_revision + 1
    assert restaurant_revision(base) == original_revision + 1
    series_after = series_read(base, series_created["series_id"], mgr)
    assert series_after["revision"] == series_before["revision"] + 1
    assert [row["exception"] for row in series_after["occurrences"]] == [False, False]
    assert [row["reservation"]["reference"] for row in series_after["occurrences"]] == [
        row["reservation"]["reference"] for row in series_before["occurrences"]]
    assert [row["reservation"]["starts_at_local"] for row in series_after["occurrences"]] == [
        row["reservation"]["starts_at_local"] for row in series_before["occurrences"]]
    assert [row["reservation"]["accepted_terms"] for row in series_after["occurrences"]] == [
        row["reservation"]["accepted_terms"] for row in series_before["occurrences"]]
    before_by_ref = {row["reference"]: row for row in before["reservations"]}
    changed = {row["reference"] for row in got_assignments if row["changed"]}
    for row in got_assignments:
        current = detail(base, row["reference"], mgr)
        previous = before_by_ref[row["reference"]]
        assert reservation_owner(base, row["reference"]) == owners_before[row["reference"]]
        assert current["table_ids"] == row["table_ids"]
        assert current["starts_at_local"] == previous["starts_at_local"]
        assert current["party_size"] == previous["party_size"]
        assert current["accepted_terms"] == previous["accepted_terms"]
        assert current["revision"] == previous["revision"] + (row["reference"] in changed)
        new_history = history(base, row["reference"], mgr)["entries"]
        old_history = dict(zip(refs, before["history"]))[row["reference"]]["entries"]
        assert len(new_history) == len(old_history) + (row["reference"] in changed)
        if row["changed"]:
            event = new_history[-1]
            assert event.get("plan_id") == plan["plan_id"]
            assert any(change.get("field") == "table_ids"
                       for change in event.get("changes", []))

    s1.expect(s1.call(base, apply_path, "POST", {}, token=mgr,
                      key=key("second-apply")), 409, "plan_already_applied")
    # The closure blocks future use of the closed single and every pair containing it.
    query = urlencode({"restaurant_id": RID, "date": date, "party_size": 2,
                       "explain": "true"})
    availability = s1.expect(s1.call(base, "/availability?" + query), 200).body
    target_slot = next(row for row in availability["slots"]
                       if row["starts_at_local"] == f"{date}T19:00")
    assert all("t_2" not in option["table_ids"]
               for option in target_slot["available_options"])
    t2_explanation = next(row for row in target_slot["explain"]
                          if row["table_id"] == "t_2")
    assert {rule["rule"]: rule["holds"] for rule in t2_explanation["rules"]}[
        "no_overlap"] is False
    closed_create = s1.call(base, "/reservations", "POST", {
        "restaurant_id": RID, "table_id": "t_2",
        "starts_at_local": f"{date}T19:00", "party_size": 2},
        token=mgr, key=key("closed-create"))
    s1.expect(closed_create, 409, "table_unavailable")
    current_second = detail(base, second["reference"], mgr)
    s1.expect(s1.call(base, f"/reservations/{second['reference']}", "PATCH", {
        "expected_revision": current_second["revision"],
        "table_id": "t_2"}, token=mgr, key=key("closed-patch")),
        409, "table_unavailable")

    # A later successful write cannot change the original apply receipt.
    later = s1.local_date(15)
    book(base, mgr, later, table="t_1", at="19:00", party=2)
    replay_apply = s1.expect(s1.call(base, apply_path, "POST", {}, token=mgr,
                                     key=apply_key), 200).body
    assert replay_apply == applied
    print("PASS Stage 4 oracle-matched preview/apply, cutoff bypass, atomic history, closure and exact replay")


def check_replan_no_plan_stale_and_concurrent_apply(base: str) -> None:
    # Closure removes the only adequate single and all adequate declared pairs.
    manager, diner, date = reset(base, capacities={"t_1": 2, "t_2": 2, "t_3": 6})
    mgr, _ = login(base, manager, diner)
    oversized = book(base, mgr, date, table="t_3", at="19:00", party=6)
    request_key = key("no-plan")
    before = _observation(base, mgr, [oversized["reference"]], date)
    impossible = replan(base, mgr, date=date, table="t_3", request_key=request_key,
                        status=409)
    assert impossible.get("error", {}).get("code") == "no_feasible_plan"
    assert _observation(base, mgr, [oversized["reference"]], date) == before
    # Failed preview keys are reusable; this closure leaves the booking feasible.
    reusable = replan(base, mgr, date=date, table="t_1", request_key=request_key)
    assert reusable["assignments"]

    # A real target-restaurant write makes a saved plan stale and changes no plan state.
    second_day = s1.local_date(15)
    stale_plan = replan(base, mgr, date=second_day, table="t_2")
    book(base, mgr, second_day, table="t_3", at="19:00", party=2)
    stale_before = _observation(base, mgr, [oversized["reference"]], date)
    stale_path = f"/restaurants/{RID}/replans/{stale_plan['plan_id']}/apply"
    s1.expect(s1.call(base, stale_path, "POST", {}, token=mgr,
                      key=key("stale-apply")), 409, "stale_plan")
    assert _observation(base, mgr, [oversized["reference"]], date) == stale_before

    # Concurrent applications may have one winner, but never partial plan state.
    manager, diner, date = reset(base)
    mgr, _ = login(base, manager, diner)
    first = book(base, mgr, date, table="t_2", at="19:00", party=4)
    plan = replan(base, mgr, date=date)
    path = f"/restaurants/{RID}/replans/{plan['plan_id']}/apply"
    def apply(index: int):
        return s1.call(base, path, "POST", {}, token=mgr,
                       key=key(f"racing-apply-{index}"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        replies = list(pool.map(apply, range(8)))
    assert sum(reply.status == 201 for reply in replies) == 1
    assert all(reply.status in (201, 409) for reply in replies)
    assert all(reply.status != 409 or
               reply.body.get("error", {}).get("code") == "plan_already_applied"
               for reply in replies)
    expected = {row["reference"]: row["table_ids"] for row in plan["assignments"]}
    actual = detail(base, first["reference"], mgr)
    assert actual["table_ids"] == expected[first["reference"]]
    assert restaurant_revision(base) == plan["restaurant_revision"] + 1
    print("PASS Stage 4 no-feasible atomicity, failed-key reuse, stale-plan rejection and concurrent apply")


def check_replan_maximum_supported_input(base: str) -> None:
    manager, diner, date = reset(base, maximum=True)
    mgr, _ = login(base, manager, diner)
    refs = []
    for index in range(6):
        at = (dt.datetime.combine(dt.date.fromisoformat(date), dt.time(18, 0)) +
              dt.timedelta(minutes=30 * index)).strftime("%H:%M")
        refs.append(book(base, mgr, date, table="t_1", at=at, party=2)["reference"])
    next_date = s1.local_date(15)
    outside = book(base, mgr, next_date, table="t_1", at="18:00", party=2)
    outside_before = detail(base, outside["reference"], mgr)
    closure = Closure("t_1", local_instant(date, "18:00"),
                      local_instant(date, "23:00"))
    plan = replan(base, mgr, date=date, table="t_1")
    assert len(plan["assignments"]) == 6
    assert [row["reference"] for row in plan["assignments"]] == sorted(refs)
    bookings, singles, pairs = _oracle_inputs(base, mgr, refs, date, closure)
    expected = optimize(singles, pairs, bookings, proposed=closure)
    assert expected is not None
    assert plan["assignments"] == [
        {"reference": ref, "table_ids": list(expected.assignments[ref]),
         "changed": frozenset(expected.assignments[ref]) !=
                    frozenset(next(item.table_ids for item in bookings
                                   if item.reference == ref))}
        for ref in sorted(refs)]
    assert plan["moved_count"] == expected.moved_count
    assert plan["unused_seats"] == expected.unused_seats
    applied = s1.expect(s1.call(base,
        f"/restaurants/{RID}/replans/{plan['plan_id']}/apply", "POST", {},
        token=mgr, key=key("max-bound-apply")), 201).body
    assert len(applied["reservations"]) == 6
    assert detail(base, outside["reference"], mgr) == outside_before
    print("PASS Stage 4 maximum 6-table/4-pair/6-booking input and unchanged out-of-interval booking")


def check_series_amendment(base: str) -> None:
    manager, diner, date = reset(base)
    mgr, _ = login(base, manager, diner)
    anchor = book(base, mgr, date, table="t_2", at="18:00", party=2)
    series_body = {"anchor_reference": anchor["reference"], "count": 4,
                   "interval_weeks": 1}
    created = s1.expect(s1.call(base, "/series", "POST", series_body,
                                token=mgr, key=key("make-series")), 201).body
    series_id = created["series_id"]
    original = series_read(base, series_id, mgr)
    occurrences = original["occurrences"]
    references = [row["reservation"]["reference"] for row in occurrences]
    # A date-effective policy published after series creation applies to later
    # real changes, while unchanged/exception/cancelled rows retain accepted terms.
    policy_date = (dt.date.fromisoformat(date) + dt.timedelta(days=21)).isoformat()
    published = s1.expect(s1.call(
        base, f"/restaurants/{RID}/policies", "POST",
        s3.policy(policy_date, duration=60, cutoff=0), token=mgr,
        key=key("amend-policy")), 201).body

    # A real individual move becomes an exception; a cancellation stays in the series.
    moved_ref, cancelled_ref = references[1], references[2]
    moved = s1.expect(s1.call(base, f"/reservations/{moved_ref}", "PATCH", {
        "expected_revision": 1, "table_id": "t_3"}, token=mgr,
        key=key("make-exception")), 200).body
    cancelled = s1.expect(s1.call(base, f"/reservations/{cancelled_ref}/cancel",
                                  "POST", {}, token=mgr,
                                  key=key("cancel-occurrence")), 200).body
    before = series_read(base, series_id, mgr)
    before_restaurant_revision = restaurant_revision(base)
    before_rows = {row["reservation"]["reference"]: copy.deepcopy(row)
                   for row in before["occurrences"]}
    owners_before = {reference: reservation_owner(base, reference)
                     for reference in references}
    histories_before = {reference: history(base, reference, mgr)["entries"]
                        for reference in references}
    expected_revision = before["revision"]
    amended_body = {"expected_revision": expected_revision,
                    "from_index": 0, "local_time": "20:00"}
    amend_key = key("amend"); path = f"/series/{series_id}/amend"
    amended = s1.expect(s1.call(base, path, "POST", amended_body, token=mgr,
                                key=amend_key), 201).body
    after_rows = {row["reservation"]["reference"]: row
                  for row in amended["occurrences"]}
    changed_refs = {references[0], references[3]}
    assert set(after_rows) == set(references)
    for reference in references:
        old = before_rows[reference]
        new = after_rows[reference]
        old_res = old["reservation"]
        new_res = new["reservation"]
        assert reservation_owner(base, reference) == owners_before[reference]
        assert new_res["reference"] == old_res["reference"]
        assert new_res["table_ids"] == old_res["table_ids"]
        assert new_res["party_size"] == old_res["party_size"]
        assert new_res["starts_at_local"][:10] == old_res["starts_at_local"][:10]
        if reference in changed_refs:
            assert new_res["starts_at_local"].endswith("T20:00")
            assert new_res["revision"] == old_res["revision"] + 1
            expected_version = published["policy_version"] if reference == references[3] else 0
            assert new_res["accepted_terms"]["policy_version"] == expected_version
            current_history = history(base, reference, mgr)["entries"]
            assert len(current_history) == len(histories_before[reference]) + 1
            assert current_history[-1]["event"] != "created"
            assert any(change["field"] == "starts_at_local"
                       for change in current_history[-1]["changes"])
        else:
            assert new == old
            assert history(base, reference, mgr)["entries"] == histories_before[reference]
    assert after_rows[moved_ref].get("exception") is True
    assert after_rows[cancelled_ref]["reservation"]["status"] == "cancelled"
    assert amended["revision"] == expected_revision + 1
    assert restaurant_revision(base) == before_restaurant_revision + 1
    assert amended["occurrences"] == series_read(base, series_id, mgr)["occurrences"]

    # Retry returns the original response after a later occurrence cancellation.
    last_ref = references[3]
    s1.expect(s1.call(base, f"/reservations/{last_ref}/cancel", "POST", {},
                      token=mgr, key=key("cancel-after-amend")), 200)
    replay = s1.expect(s1.call(base, path, "POST", amended_body,
                               token=mgr, key=amend_key), 200).body
    assert replay == amended
    print("PASS Stage 4 series amendment preserves identities/dates/tables and skips exceptions/cancellations")


def check_series_amend_validation_precedence_and_concurrency(base: str) -> None:
    manager, diner, date = reset(base, cutoff=10080)
    mgr, din = login(base, manager, diner)
    anchor = book(base, mgr, date, table="t_2", at="18:00", party=2)
    created = s1.expect(s1.call(base, "/series", "POST", {
        "anchor_reference": anchor["reference"], "count": 2,
        "interval_weeks": 1}, token=mgr, key=key("series-guards")), 201).body
    series_id = created["series_id"]
    shift_series_dates_in_import(base, series_id, dt.date.fromisoformat(s1.local_date(2)))
    path = f"/series/{series_id}/amend"
    current = series_read(base, series_id, mgr)
    revision = current["revision"]
    valid = {"expected_revision": revision, "from_index": 0,
             "local_time": "20:00"}
    s1.expect(s1.call(base, path, "POST", valid, key=key("anon-amend")), 401)
    s1.expect(s1.call(base, path, "POST", valid, token=din,
                      key=key("other-owner")), 404)
    malformed = [
        {**valid, "expected_revision": True},
        {**valid, "expected_revision": 1.5},
        {**valid, "expected_revision": 0},
        {**valid, "from_index": True},
        {**valid, "from_index": -1},
        {**valid, "from_index": 2},
        {**valid, "local_time": "20:0"},
        {**valid, "local_time": "24:00"},
    ]
    for body in malformed:
        s1.expect(s1.call(base, path, "POST", body, token=mgr,
                          key=key("bad-amend")), 422, "validation_failed")
    s1.expect(s1.call(base, path, "POST", valid, token=mgr),
              400, "missing_idempotency_key")
    stale = {**valid, "expected_revision": revision + 1,
             "local_time": "21:00"}
    before = series_read(base, series_id, mgr)
    s1.expect(s1.call(base, path, "POST", stale, token=mgr,
                      key=key("stale-amend")), 409, "stale_revision")
    assert series_read(base, series_id, mgr) == before

    # Current revision reaches the accepted cutoff path without changing state.
    cutoff_before = copy.deepcopy(before)
    current = {**valid, "expected_revision": revision, "local_time": "21:00"}
    s1.expect(s1.call(base, path, "POST", current, token=mgr,
                      key=key("current-cutoff")), 409, "cutoff_passed")
    assert series_read(base, series_id, mgr) == cutoff_before

    # Two same-revision real amendments may not both win.
    manager, diner, date = reset(base)
    mgr, _ = login(base, manager, diner)
    anchor = book(base, mgr, date, table="t_2", at="18:00", party=2)
    created = s1.expect(s1.call(base, "/series", "POST", {
        "anchor_reference": anchor["reference"], "count": 2,
        "interval_weeks": 1}, token=mgr, key=key("series-race")), 201).body
    series_id = created["series_id"]
    before = series_read(base, series_id, mgr)
    revision = before["revision"]
    path = f"/series/{series_id}/amend"
    def amend(clock: str):
        return s1.call(base, path, "POST", {
            "expected_revision": revision, "from_index": 0,
            "local_time": clock}, token=mgr, key=key("amend-race"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(amend, ("20:00", "21:00")))
    assert sum(reply.status == 201 for reply in replies) == 1
    assert sorted(reply.status for reply in replies) == [201, 409]
    assert next(reply for reply in replies if reply.status == 409).body[
        "error"]["code"] == "stale_revision"
    assert series_read(base, series_id, mgr)["revision"] == revision + 1
    print("PASS Stage 4 series strict types, privacy, stale-before-cutoff and same-revision concurrency")


def check_series_noop_empty_and_atomic_rollback(base: str) -> None:
    manager, diner, date = reset(base)
    mgr, _ = login(base, manager, diner)
    anchor = book(base, mgr, date, table="t_2", at="18:00", party=2)
    created = s1.expect(s1.call(base, "/series", "POST", {
        "anchor_reference": anchor["reference"], "count": 2,
        "interval_weeks": 1}, token=mgr, key=key("series-noop")), 201).body
    series_id = created["series_id"]
    path = f"/series/{series_id}/amend"
    before = series_read(base, series_id, mgr)
    refs = [row["reservation"]["reference"] for row in before["occurrences"]]
    before_restaurant_revision = restaurant_revision(base)
    before_histories = [history(base, ref, mgr) for ref in refs]
    noop_body = {"expected_revision": before["revision"], "from_index": 0,
                 "local_time": "18:00", "ignored_unknown_field": "ignored"}
    noop = s1.expect(s1.call(base, path, "POST", noop_body, token=mgr,
                             key=key("all-noop")), 201).body
    assert noop == before
    assert series_read(base, series_id, mgr) == before
    assert restaurant_revision(base) == before_restaurant_revision
    assert [history(base, ref, mgr) for ref in refs] == before_histories

    # Exclude every member, then a valid amendment is an empty eligible set.
    s1.expect(s1.call(base, f"/reservations/{refs[0]}", "PATCH", {
        "expected_revision": 1, "table_id": "t_3"}, token=mgr,
        key=key("noop-exception")), 200)
    s1.expect(s1.call(base, f"/reservations/{refs[1]}/cancel", "POST", {},
                      token=mgr, key=key("noop-cancel")), 200)
    empty_before = series_read(base, series_id, mgr)
    empty_restaurant_revision = restaurant_revision(base)
    empty_histories = [history(base, ref, mgr) for ref in refs]
    empty = s1.expect(s1.call(base, path, "POST", {
        "expected_revision": empty_before["revision"], "from_index": 0,
        "local_time": "21:00"}, token=mgr, key=key("empty-eligible")), 201).body
    assert empty == empty_before
    assert series_read(base, series_id, mgr) == empty_before
    assert restaurant_revision(base) == empty_restaurant_revision
    assert [history(base, ref, mgr) for ref in refs] == empty_histories

    # A later-occurrence collision rolls the complete amendment back. Its key
    # remains available, so the same request succeeds after the blocker is removed.
    manager, diner, date = reset(base)
    mgr, _ = login(base, manager, diner)
    anchor = book(base, mgr, date, table="t_2", at="18:00", party=2)
    created = s1.expect(s1.call(base, "/series", "POST", {
        "anchor_reference": anchor["reference"], "count": 3,
        "interval_weeks": 1}, token=mgr, key=key("series-conflict")), 201).body
    series_id = created["series_id"]
    path = f"/series/{series_id}/amend"
    before = series_read(base, series_id, mgr)
    refs = [row["reservation"]["reference"] for row in before["occurrences"]]
    conflict_date = before["occurrences"][1]["reservation"]["starts_at_local"][:10]
    blocker = book(base, mgr, conflict_date, table="t_2", at="20:00", party=2)
    before = series_read(base, series_id, mgr)
    before_reservations = [detail(base, ref, mgr) for ref in refs]
    before_histories = [history(base, ref, mgr) for ref in refs]
    before_restaurant_revision = restaurant_revision(base)
    body = {"expected_revision": before["revision"], "from_index": 1,
            "local_time": "20:00"}
    failed_key = key("atomic-rollback")
    s1.expect(s1.call(base, path, "POST", body, token=mgr, key=failed_key),
              409, "table_unavailable")
    assert series_read(base, series_id, mgr) == before
    assert [detail(base, ref, mgr) for ref in refs] == before_reservations
    assert [history(base, ref, mgr) for ref in refs] == before_histories
    assert restaurant_revision(base) == before_restaurant_revision

    s1.expect(s1.call(base, f"/reservations/{blocker['reference']}/cancel",
                      "POST", {}, token=mgr, key=key("remove-blocker")), 200)
    accepted = s1.expect(s1.call(base, path, "POST", body, token=mgr,
                                 key=failed_key), 201).body
    assert accepted["revision"] == before["revision"] + 1
    assert accepted["occurrences"][0] == before["occurrences"][0]
    assert accepted["occurrences"][1]["reservation"]["starts_at_local"].endswith("T20:00")
    assert accepted["occurrences"][2]["reservation"]["starts_at_local"].endswith("T20:00")
    assert not accepted["occurrences"][1].get("exception", False)
    print("PASS Stage 4 no-op/empty revisions, atomic rollback and failed-key reuse")


def check_series_nonoccupancy_precedence(base: str) -> None:
    manager, diner, date = reset(base, cutoff=10080)
    mgr, _ = login(base, manager, diner)
    anchor = book(base, mgr, date, table="t_2", at="18:00", party=2)
    created = s1.expect(s1.call(base, "/series", "POST", {
        "anchor_reference": anchor["reference"], "count": 2,
        "interval_weeks": 1}, token=mgr, key=key("precedence-series")), 201).body
    series_id = created["series_id"]
    shift_series_dates_in_import(base, series_id, dt.date.fromisoformat(s1.local_date(2)))
    before = series_read(base, series_id, mgr)
    later_date = before["occurrences"][1]["reservation"]["starts_at_local"][:10]
    blocker = book(base, mgr, later_date, table="t_2", at="20:00", party=2)
    path = f"/series/{series_id}/amend"
    refs = [row["reservation"]["reference"] for row in before["occurrences"]]
    before_rows = [detail(base, reference, mgr) for reference in refs]
    before_histories = [history(base, reference, mgr) for reference in refs]
    before_restaurant_revision = restaurant_revision(base)
    s1.expect(s1.call(base, path, "POST", {
        "expected_revision": before["revision"], "from_index": 0,
        "local_time": "20:00"}, token=mgr, key=key("precedence-error")),
        409, "cutoff_passed")
    assert series_read(base, series_id, mgr) == before
    assert [detail(base, reference, mgr) for reference in refs] == before_rows
    assert [history(base, reference, mgr) for reference in refs] == before_histories
    assert restaurant_revision(base) == before_restaurant_revision
    assert detail(base, blocker["reference"], mgr) == blocker
    print("PASS Stage 4 earlier non-occupancy cutoff error takes precedence over later occupancy conflict")


def check_populated_imports(stage1: str, stage2: str, stage3: str, target: str) -> None:
    # Reuse exact populated source/receipt checks already verified for earlier contracts.
    s3.check_stage1_import_and_adopt(stage1, target)
    s3.check_stage2_import_and_adopt(stage2, target)

    data, manager, diner = s3.fixture(pair=True)
    s1.reset(stage3, data)
    s1.reset(target, data)
    source_token = login(stage3, manager, diner)[0]
    date = s1.local_date(21)
    create_body = {"restaurant_id": s3.RID, "table_id": "t_2",
                   "starts_at_local": f"{date}T18:00", "party_size": 2}
    create_key = key("stage3-import-create")
    created = s1.expect(s1.call(stage3, "/reservations", "POST", create_body,
                               token=source_token, key=create_key), 201).body
    series_body = {"anchor_reference": created["reference"], "count": 3,
                   "interval_weeks": 1}
    series_key = key("stage3-import-series")
    made = s1.expect(s1.call(stage3, "/series", "POST", series_body,
                             token=source_token, key=series_key), 201).body
    references = [row["reservation"]["reference"]
                  for row in made["occurrences"]]
    move_body = {"moves": [{"reference": references[1], "table_id": "t_3",
                             "expected_revision": 1}]}
    move_key = key("stage3-import-move")
    moved = s1.expect(s1.call(stage3, "/reservation-moves", "POST", move_body,
                              token=source_token, key=move_key), 201).body
    cancel_key = key("stage3-import-cancel")
    cancelled = s1.expect(s1.call(stage3,
                                  f"/reservations/{references[2]}/cancel", "POST", {},
                                   token=source_token, key=cancel_key), 200).body
    owners_before = {reference: reservation_owner(stage3, reference)
                     for reference in references}
    envelope = s1.expect(s1.call(stage3, "/_test/export"), 200).body
    s1.expect(s1.call(target, "/_test/import", "POST", envelope), 204)
    # The imported source session and original successful receipts remain valid.
    s1.expect(s1.call(target, "/restaurants", token=source_token), 200)
    assert s1.expect(s1.call(target, "/reservations", "POST", create_body,
                             token=source_token, key=create_key), 200).body == created
    assert s1.expect(s1.call(target, "/series", "POST", series_body,
                             token=source_token, key=series_key), 200).body == made
    assert s1.expect(s1.call(target, "/reservation-moves", "POST", move_body,
                             token=source_token, key=move_key), 200).body == moved
    assert s1.expect(s1.call(target, f"/reservations/{references[2]}/cancel",
                             "POST", {}, token=source_token, key=cancel_key), 200).body == cancelled
    final = series_read(target, made["series_id"], source_token)
    assert {reference: reservation_owner(target, reference)
            for reference in references} == owners_before
    assert final["occurrences"][1].get("exception") is True
    assert final["occurrences"][2]["reservation"]["status"] == "cancelled"
    print("PASS populated Stage 3 import retains session, series states, histories and create/move/cancel receipts")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="disposable Stage 4 service")
    parser.add_argument("--stage1-url", required=True, help="populated Stage 1 source")
    parser.add_argument("--stage2-url", required=True, help="populated Stage 2 source")
    parser.add_argument("--stage3-url", required=True, help="populated Stage 3 source")
    parser.add_argument("--result-json", help="sanitized result summary path")
    args = parser.parse_args()
    checks = [check_replan_guards, check_replan_bypasses_cutoff,
              check_replan_oracle_preview_apply,
              check_replan_no_plan_stale_and_concurrent_apply,
              check_replan_maximum_supported_input,
              check_series_amendment, check_series_amend_validation_precedence_and_concurrency,
              check_series_noop_empty_and_atomic_rollback,
              check_series_nonoccupancy_precedence]
    for check in checks:
        check(args.base_url)
    check_populated_imports(args.stage1_url, args.stage2_url,
                            args.stage3_url, args.base_url)
    max_request = max(s1.REQUEST_TIMINGS, default=0.0)
    max_control = max(s1.CONTROL_TIMINGS, default=0.0)
    assert max_request < 5 and max_control < 10, (
        f"request/control limit exceeded: {max_request:.3f}s/{max_control:.3f}s")
    print(f"TIMING requests={len(s1.REQUEST_TIMINGS)} max_request_ms={max_request * 1000:.1f} "
          f"controls={len(s1.CONTROL_TIMINGS)} max_control_ms={max_control * 1000:.1f}")
    if args.result_json:
        with open(args.result_json, "w", encoding="utf-8", newline="\n") as stream:
            json.dump({"api_check_functions": len(checks),
                       "stage1_import": "pass", "stage2_import": "pass",
                       "stage3_import": "pass",
                       "request_count": len(s1.REQUEST_TIMINGS),
                       "max_request_ms": round(max_request * 1000, 1),
                       "control_count": len(s1.CONTROL_TIMINGS),
                       "max_control_ms": round(max_control * 1000, 1)}, stream, indent=2)
            stream.write("\n")
    print("PASS independent Stage 4 API checks")


if __name__ == "__main__":
    main()
