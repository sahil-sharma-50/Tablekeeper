#!/usr/bin/env python3
"""Independent Stage 3 contract checks. Use only against disposable local services."""
from __future__ import annotations

import argparse
import concurrent.futures
import copy
import datetime as dt
import json
from urllib.parse import urlencode
import uuid
from zoneinfo import ZoneInfo

import stage1_independent as s1
import stage2_independent as s2


RID = "r_stage3_qa"


def key(label: str) -> str:
    return f"s3-{label}-{uuid.uuid4().hex}"


def fixture(*, pair: bool = False, cutoff: int = 0) -> tuple[dict, dict, dict]:
    manager, diner = s1.user(91), s1.user(92)
    restaurant = s1.restaurant(RID, cancellation_cutoff_minutes=cutoff)
    restaurant["manager_user_ids"] = [manager["id"]]
    if pair:
        restaurant["combinable"] = [["t_1", "t_2"], ["t_2", "t_3"]]
    return s1.fixture(users=[manager, diner], restaurants=[restaurant]), manager, diner


def policy(date: str, *, duration: int = 90, cutoff: int = 0,
           capacities: dict | None = None, opening: list | None = None) -> dict:
    return {
        "effective_from": date,
        "slot_minutes": 30,
        "reservation_duration_minutes": duration,
        "cancellation_cutoff_minutes": cutoff,
        "opening_hours": copy.deepcopy(opening) if opening is not None else [
            {"weekday": day, "opens": "18:00", "closes": "23:00"}
            for day in s1.WEEKDAYS
        ],
        "capacities": capacities or {"t_1": 2, "t_2": 4, "t_3": 6},
    }


def publish(base: str, token: str, body: dict, idem: str | None = None,
            status: int = 201) -> dict:
    return s1.expect(s1.call(base, f"/restaurants/{RID}/policies", "POST", body,
                             token=token, key=idem or key("policy")), status).body


def slot(base: str, date: str, *, explain: str | None = None,
         party: int = 4, at: str = "19:00") -> dict:
    query = {"restaurant_id": RID, "date": date, "party_size": party}
    if explain is not None:
        query["explain"] = explain
    body = s1.expect(s1.call(base, "/availability?" + urlencode(query)), 200).body
    return next((row for row in body["slots"]
                 if row["starts_at_local"] == f"{date}T{at}"), None) if body["slots"] else None


def reservation(base: str, ref: str, token: str | None = None) -> dict:
    return s1.expect(s1.call(base, f"/reservations/{ref}", token=token), 200).body


def history(base: str, ref: str, token: str | None = None) -> dict:
    return s1.expect(s1.call(base, f"/reservations/{ref}/history", token=token), 200).body


def series(base: str, series_id: str, token: str | None = None) -> dict:
    return s1.expect(s1.call(base, f"/series/{series_id}", token=token), 200).body


def reservations(base: str, token: str) -> list[dict]:
    return s1.expect(s1.call(base, "/reservations", token=token), 200).body["reservations"]


def restaurant_revision(base: str) -> int:
    state = s1.expect(s1.call(base, "/_test/export"), 200).body["state"]
    return next(row["restaurant_revision"] for row in state["restaurants"]
                if row["id"] == RID)


def create(base: str, token: str, date: str, *, table: str = "t_2",
           at: str = "19:00", party: int = 4, request_key: str | None = None) -> dict:
    body = {"restaurant_id": RID, "table_id": table,
            "starts_at_local": f"{date}T{at}", "party_size": party}
    return s1.expect(s1.call(base, "/reservations", "POST", body, token=token,
                             key=request_key or key("create")), 201).body


def check_policy_selection_validation_and_explanations(base: str) -> None:
    data, manager, diner = fixture()
    s1.reset(base, data)
    mgr = s1.login(base, manager)
    din = s1.login(base, diner)
    day = dt.date.fromisoformat(s1.local_date(14))
    earlier, later = day.isoformat(), (day + dt.timedelta(days=14)).isoformat()

    s1.expect(s1.call(base, f"/restaurants/{RID}/policies"), 200)
    s1.expect(s1.call(base, f"/restaurants/{RID}/policies", "POST", policy(earlier),
                      key=key("no-token")), 401, "unauthenticated")
    s1.expect(s1.call(base, f"/restaurants/{RID}/policies", "POST", policy(earlier),
                      token=din, key=key("diner")), 403, "forbidden")
    s1.expect(s1.call(base, "/restaurants/missing/policies", "POST", policy(earlier),
                      token=mgr, key=key("unknown-restaurant")), 404, "not_found")

    valid = policy(earlier)
    invalid = [
        {**valid, "effective_from": "2026-02-30"},
        {**valid, "effective_from": "2026/02/28"},
        {**valid, "effective_from": True},
        {**valid, "slot_minutes": True},
        {**valid, "slot_minutes": 0},
        {**valid, "slot_minutes": 1441},
        {**valid, "slot_minutes": 1.5},
        {**valid, "slot_minutes": "30"},
        {**valid, "reservation_duration_minutes": True},
        {**valid, "reservation_duration_minutes": 0},
        {**valid, "reservation_duration_minutes": 1441},
        {**valid, "reservation_duration_minutes": "90"},
        {**valid, "cancellation_cutoff_minutes": False},
        {**valid, "cancellation_cutoff_minutes": -1},
        {**valid, "cancellation_cutoff_minutes": 10081},
        {**valid, "cancellation_cutoff_minutes": "0"},
        {**valid, "opening_hours": [valid["opening_hours"][0], valid["opening_hours"][0]]},
        {**valid, "opening_hours": None},
        {**valid, "opening_hours": [{"opens": "18:00", "closes": "23:00"}]},
        {**valid, "opening_hours": [{"weekday": "mon", "opens": "25:00", "closes": "23:00"}]},
        {**valid, "opening_hours": [{"weekday": "mon", "opens": "23:00", "closes": "18:00"}]},
        {**valid, "capacities": {"t_1": 2, "t_2": 4}},
        {**valid, "capacities": {"t_1": 2, "t_2": 4, "t_3": 6, "other": 1}},
        {**valid, "capacities": {}},
        {**valid, "capacities": None},
        {**valid, "capacities": {"t_1": 2, "t_2": True, "t_3": 6}},
        {**valid, "capacities": {"t_1": 0, "t_2": 4, "t_3": 6}},
        {**valid, "capacities": {"t_1": 2, "t_2": 4, "t_3": 101}},
        {**valid, "capacities": {"t_1": 2, "t_2": 4, "t_3": 6.0}},
        *[{key_name: value for key_name, value in valid.items() if key_name != missing}
          for missing in valid],
    ]
    for body in invalid:
        s1.expect(s1.call(base, f"/restaurants/{RID}/policies", "POST", body,
                          token=mgr, key=key("invalid-policy")), 422, "validation_failed")
    reusable = key("failed-key-reusable")
    s1.expect(s1.call(base, f"/restaurants/{RID}/policies", "POST",
                      {**valid, "capacities": {"t_1": True, "t_2": 4, "t_3": 6}},
                      token=mgr, key=reusable), 422, "validation_failed")
    first = publish(base, mgr, {**valid, "ignored_unknown_field": "ignored"}, reusable)
    assert first["policy_version"] == 1 and "ignored_unknown_field" not in first
    first_replay = publish(base, mgr, {**valid, "ignored_unknown_field": "ignored"},
                           reusable, 200)
    assert first_replay == first

    # Publish by version in the order +28, +14, +14: selection must use the
    # latest applicable date and latest version for an effective-date tie.
    p_future = policy(later, duration=120)
    future_key = key("future-policy")
    future = publish(base, mgr, p_future, future_key)
    p_early = policy(earlier, capacities={"t_1": 2, "t_2": 4, "t_3": 6})
    early = publish(base, mgr, p_early)
    tied = publish(base, mgr, policy(earlier, duration=60))
    assert [future["policy_version"], early["policy_version"], tied["policy_version"]] == [2, 3, 4]
    rows = s1.expect(s1.call(base, f"/restaurants/{RID}/policies"), 200).body["policies"]
    assert [row["policy_version"] for row in rows] == [1, 2, 3, 4]
    assert publish(base, mgr, p_future, future_key, status=200) == future
    assert len(s1.expect(s1.call(base, f"/restaurants/{RID}/policies"), 200).body["policies"]) == 4
    detail = s1.expect(s1.call(base, f"/restaurants/{RID}"), 200).body
    assert detail["reservation_duration_minutes"] == 90
    assert [table["capacity"] for table in detail["tables"]] == [2, 4, 6]

    # Only the literal true enables explanations; the stage-1 response shape is
    # unchanged when the parameter is omitted.
    for explain in ("false", "1", ""):
        query = urlencode({"restaurant_id": RID, "date": earlier,
                           "party_size": 4, "explain": explain})
        s1.expect(s1.call(base, f"/availability?{query}"), 422, "validation_failed")
    base_slot = slot(base, earlier)
    assert base_slot and "explain" not in base_slot
    explained = slot(base, earlier, explain="true")
    assert explained is not None
    tables = [table["id"] for table in detail["tables"]]
    assert [row["table_id"] for row in explained["explain"]] == tables
    assert all([rule["rule"] for rule in row["rules"]] == ["capacity", "no_overlap"]
               for row in explained["explain"])
    assert [row["table_id"] for row in explained["explain"] if row["available"]] == explained["available_table_ids"]
    assert all(row["policy_version"] == tied["policy_version"] for row in explained["explain"])

    # Occupy t_2 and t_3 so the explanation checks both independent false rules
    # and a slot which remains present with no available tables.
    token = mgr
    for table_id in ("t_1", "t_2", "t_3"):
        s1.expect(s1.call(base, "/reservations", "POST", {
            "restaurant_id": RID, "table_id": table_id,
            "starts_at_local": f"{earlier}T19:00",
            "party_size": 2 if table_id == "t_1" else 4,
        }, token=token, key=key("occupancy")), 201)
    full = slot(base, earlier, explain="true")
    assert full is not None and full["available_table_ids"] == []
    by_id = {row["table_id"]: row for row in full["explain"]}
    assert by_id["t_1"]["rules"] == [
        {"rule": "capacity", "holds": False}, {"rule": "no_overlap", "holds": False}]
    for table_id in ("t_2", "t_3"):
        assert by_id[table_id]["rules"] == [
            {"rule": "capacity", "holds": True}, {"rule": "no_overlap", "holds": False}]
        assert by_id[table_id]["available"] is False
    assert all(row["available"] == all(rule["holds"] for rule in row["rules"])
               for row in full["explain"])
    assert [row["table_id"] for row in full["explain"] if row["available"]] == []

    # Latest effective date wins even when published before an earlier date;
    # a tie is resolved by the greatest policy version.
    selected_before = slot(base, (day - dt.timedelta(days=10)).isoformat(), explain="true")
    selected_tie = slot(base, earlier, explain="true")
    selected_later = slot(base, (day + dt.timedelta(days=35)).isoformat(), explain="true")
    assert selected_before and all(row["policy_version"] == 0 for row in selected_before["explain"])
    assert selected_tie and all(row["policy_version"] == 4 for row in selected_tie["explain"])
    assert selected_later and all(row["policy_version"] == 2 for row in selected_later["explain"])

    closed_policy = policy((day + dt.timedelta(days=30)).isoformat(), opening=[
        {"weekday": "mon", "opens": "18:00", "closes": "23:00"}])
    publish(base, mgr, closed_policy)
    closed_day = day + dt.timedelta(days=31)
    if closed_day.strftime("%a").lower() == "mon":
        closed_day += dt.timedelta(days=1)
    query = urlencode({"restaurant_id": RID, "date": closed_day.isoformat(),
                       "party_size": 4, "explain": "true"})
    assert s1.expect(s1.call(base, f"/availability?{query}"), 200).body["slots"] == []
    past_policy = publish(base, mgr, policy((dt.date.today() - dt.timedelta(days=7)).isoformat()))
    past_selection = slot(base, s1.local_date(2), explain="true")
    assert past_selection and all(row["policy_version"] == past_policy["policy_version"]
                                  for row in past_selection["explain"])
    minimum = policy((day + dt.timedelta(days=45)).isoformat(), duration=1,
                     capacities={"t_1": 1, "t_2": 1, "t_3": 1})
    minimum["slot_minutes"] = 1
    assert publish(base, mgr, minimum)["policy_version"] == 7
    maximum = policy((day + dt.timedelta(days=46)).isoformat(), duration=1440,
                     cutoff=10080, capacities={"t_1": 1, "t_2": 100, "t_3": 1})
    maximum["slot_minutes"] = 1440
    assert publish(base, mgr, maximum)["policy_version"] == 8
    print("PASS Stage 3 policy authorization, validation, effective-date selection, replay, and explanations")


def check_history_accepted_terms_and_revision_rules(base: str) -> None:
    data, owner, other = fixture(cutoff=0)
    s1.reset(base, data)
    token, other_token = s1.login(base, owner), s1.login(base, other)
    day = dt.date.fromisoformat(s1.local_date(14))
    next_day = (day + dt.timedelta(days=1)).isoformat()
    body = {"restaurant_id": RID, "table_id": "t_2",
            "starts_at_local": f"{day.isoformat()}T19:00", "party_size": 4}
    create_key = key("create-history")
    created = s1.expect(s1.call(base, "/reservations", "POST", body,
                                token=token, key=create_key), 201).body
    initial_terms = copy.deepcopy(created["accepted_terms"])
    first_history = history(base, created["reference"], token)["entries"]
    assert created["revision"] == 1 and initial_terms["policy_version"] == 0
    assert len(first_history) == 1 and first_history[0]["seq"] == 1
    assert first_history[0]["event"] == "created"
    assert [change["field"] for change in first_history[0]["changes"]] == [
        "table_id", "starts_at_local", "party_size"]
    assert all(change["from"] is None for change in first_history[0]["changes"])
    assert first_history[0]["revision"] == 1 and first_history[0]["accepted_terms"] == initial_terms
    decision_path = f"/reservations/{created['reference']}/decision"
    decision = s1.expect(s1.call(base, decision_path, token=token), 200).body
    assert decision == {"reference": created["reference"], "revision": 1,
                        "accepted_terms": initial_terms}
    for auth in (None, other_token):
        s1.expect(s1.call(base, f"/reservations/{created['reference']}/history", token=auth),
                  404, "not_found")
        s1.expect(s1.call(base, decision_path, token=auth), 404, "not_found")

    # A later effective policy cannot rewrite the accepted snapshot. The real
    # amendment moves into its date and adopts that date's complete policy.
    # The fixture makes the booking owner a manager without granting any
    # access to another diner's private reservation data.
    future_policy = policy(next_day, duration=120, capacities={"t_1": 2, "t_2": 3, "t_3": 6})
    s1.expect(s1.call(base, f"/restaurants/{RID}/policies", "POST", future_policy,
                      token=token, key=key("terms-policy")), 201)
    assert reservation(base, created["reference"], token)["accepted_terms"] == initial_terms
    assert history(base, created["reference"], token)["entries"] == first_history

    amended_body = {"table_id": "t_3", "starts_at_local": f"{next_day}T19:00", "party_size": 5}
    amended = s1.expect(s1.call(base, f"/reservations/{created['reference']}", "PATCH",
                                amended_body, token=token), 200).body
    assert amended["revision"] == 2 and amended["accepted_terms"]["policy_version"] == 1
    assert amended["accepted_terms"]["reservation_duration_minutes"] == 120
    assert amended["ends_at"] == (dt.datetime.fromisoformat(amended["starts_at"])
                                    + dt.timedelta(minutes=120)).isoformat()
    entries = history(base, created["reference"], token)["entries"]
    assert [entry["seq"] for entry in entries] == [1, 2]
    assert [dt.datetime.fromisoformat(entry["at"]) for entry in entries] == sorted(
        dt.datetime.fromisoformat(entry["at"]) for entry in entries)
    assert [change["field"] for change in entries[1]["changes"]] == [
        "table_id", "starts_at_local", "party_size"]
    assert entries[1]["revision"] == 2 and entries[1]["accepted_terms"] == amended["accepted_terms"]

    no_op = s1.expect(s1.call(base, f"/reservations/{created['reference']}", "PATCH", {
        "table_id": amended["table_id"], "starts_at_local": amended["starts_at_local"],
        "party_size": amended["party_size"],
    }, token=token), 200).body
    assert no_op == amended and history(base, created["reference"], token)["entries"] == entries
    s1.expect(s1.call(base, f"/reservations/{created['reference']}", "PATCH", {
        "expected_revision": 1, "table_id": "missing-table",
    }, token=token), 409, "stale_revision")
    s1.expect(s1.call(base, f"/reservations/{created['reference']}", "PATCH", {
        "expected_revision": True, "table_id": "missing-table",
    }, token=token), 422, "validation_failed")
    for invalid_revision in (0, -1, 1.5, "2"):
        s1.expect(s1.call(base, f"/reservations/{created['reference']}", "PATCH", {
            "expected_revision": invalid_revision, "table_id": "missing-table",
        }, token=token), 422, "validation_failed")
    assert reservation(base, created["reference"], token) == amended

    # Idempotent creation replay keeps the original receipt and adds no history.
    replay = s1.expect(s1.call(base, "/reservations", "POST", body,
                               token=token, key=create_key), 200).body
    assert replay == created
    assert history(base, created["reference"], token)["entries"] == entries
    cancelled = s1.expect(s1.call(base, f"/reservations/{created['reference']}/cancel",
                                  "POST", token=token), 200).body
    assert cancelled["status"] == "cancelled" and cancelled["revision"] == 3
    cancelled_entries = history(base, created["reference"], token)["entries"]
    assert cancelled_entries[-1]["event"] == "cancelled" and cancelled_entries[-1]["changes"] == []
    assert cancelled_entries[-1]["revision"] == 3
    decision_after_cancel = s1.expect(s1.call(base, decision_path, token=token), 200).body
    assert decision_after_cancel["revision"] == 3
    repeated = s1.expect(s1.call(base, f"/reservations/{created['reference']}/cancel",
                                 "POST", token=token), 200).body
    assert repeated == cancelled and history(base, created["reference"], token)["entries"] == cancelled_entries
    assert cancelled_entries[-1]["event"] == "cancelled"
    print("PASS Stage 3 history snapshots, owner privacy, accepted terms, no-op, stale revision, cancellation, and replay")


def check_old_cutoff_precedence_and_concurrent_revision(base: str) -> None:
    data, manager, _ = fixture(cutoff=10080)
    s1.reset(base, data)
    token = s1.login(base, manager)
    day = dt.date.fromisoformat(s1.local_date(2))
    body = {"restaurant_id": RID, "table_id": "t_3",
            "starts_at_local": f"{day.isoformat()}T19:00", "party_size": 4}
    created = s1.expect(s1.call(base, "/reservations", "POST", body,
                                token=token, key=key("old-cutoff")), 201).body
    next_day = (day + dt.timedelta(days=2)).isoformat()
    publish(base, token, policy(next_day, cutoff=0, capacities={"t_1": 1, "t_2": 1, "t_3": 1}))
    invalid_result = {"starts_at_local": f"{next_day}T19:00", "table_id": "missing",
                      "party_size": 99}
    s1.expect(s1.call(base, f"/reservations/{created['reference']}", "PATCH",
                      invalid_result, token=token), 409, "cutoff_passed")
    s1.expect(s1.call(base, f"/reservations/{created['reference']}", "PATCH",
                      {**invalid_result, "expected_revision": 2}, token=token),
              409, "stale_revision")
    s1.expect(s1.call(base, f"/reservations/{created['reference']}/cancel", "POST",
                      token=token), 409, "cutoff_passed")
    s1.expect(s1.call(base, "/reservation-moves", "POST", {"moves": [{
        "reference": created["reference"], "table_id": "missing-table",
    }]}, token=token, key=key("move-old-cutoff")), 409, "cutoff_passed")
    s1.expect(s1.call(base, "/reservation-moves", "POST", {"moves": [{
        "reference": created["reference"], "expected_revision": 2,
        "table_id": "missing-table",
    }]}, token=token, key=key("move-stale-before-cutoff")), 409, "stale_revision")
    # Publication must not replace the cutoff accepted when this booking was made.
    assert reservation(base, created["reference"], token) == created
    print("PASS old accepted cutoff precedes resulting-policy validation; stale revision precedes cutoff")

    data, manager, _ = fixture(cutoff=0)
    s1.reset(base, data)
    token = s1.login(base, manager)
    day = s1.local_date(14)
    body = {"restaurant_id": RID, "table_id": "t_1",
            "starts_at_local": f"{day}T19:00", "party_size": 2}
    created = s1.expect(s1.call(base, "/reservations", "POST", body,
                                token=token, key=key("concurrent-revision")), 201).body

    def amend(table_id: str):
        return s1.call(base, f"/reservations/{created['reference']}", "PATCH",
                       {"expected_revision": 1, "table_id": table_id}, token=token)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(amend, ("t_2", "t_3")))
    statuses = sorted(reply.status for reply in replies)
    assert statuses == [200, 409], statuses
    assert any(reply.body.get("error", {}).get("code") == "stale_revision" for reply in replies)
    final = reservation(base, created["reference"], token)
    assert final["revision"] == 2 and final["table_id"] in ("t_2", "t_3")
    assert [entry["seq"] for entry in history(base, created["reference"], token)["entries"]] == [1, 2]
    print("PASS concurrent same-revision amendments commit at most one real change")


def check_series_atomicity_and_lifecycle(base: str) -> None:
    data, owner, other = fixture()
    s1.reset(base, data)
    token, other_token = s1.login(base, owner), s1.login(base, other)
    day = s1.local_date(14)
    anchor = create(base, token, day, request_key=key("series-anchor"))
    anchor_before = copy.deepcopy(anchor)

    # A collision at occurrence one must leave no partial occurrences and no
    # idempotency claim, so the same key succeeds after the conflict is cleared.
    blocker = create(base, token, (dt.date.fromisoformat(day) + dt.timedelta(days=7)).isoformat(),
                     table="t_2", request_key=key("series-blocker"))
    adopt_key = key("series-conflict-reusable")
    adopt_body = {"anchor_reference": anchor["reference"], "count": 2,
                  "interval_weeks": 1}
    before_refs = {row["reference"] for row in reservations(base, token)}
    failed_revision = restaurant_revision(base)
    s1.expect(s1.call(base, "/series", "POST", adopt_body, token=token,
                      key=adopt_key), 409, "table_unavailable")
    assert {row["reference"] for row in reservations(base, token)} == before_refs
    assert restaurant_revision(base) == failed_revision
    s1.expect(s1.call(base, f"/reservations/{blocker['reference']}/cancel", "POST",
                      token=token), 200)

    for bad in ((1, 1), (13, 1), (True, 1), (2, 0), (2, 5), (2, False)):
        s1.expect(s1.call(base, "/series", "POST", {
            "anchor_reference": anchor["reference"], "count": bad[0],
            "interval_weeks": bad[1]}, token=token, key=key("invalid-series")),
            422, "validation_failed")
    s1.expect(s1.call(base, "/series", "POST", adopt_body, key=key("series-no-auth")),
              401, "unauthenticated")
    s1.expect(s1.call(base, "/series", "POST", {
        **adopt_body, "anchor_reference": "unknown-reference"}, token=token,
        key=key("series-unknown")), 404, "not_found")
    other_anchor = create(base, other_token, day, table="t_1", party=2)
    s1.expect(s1.call(base, "/series", "POST", {
        **adopt_body, "anchor_reference": other_anchor["reference"]}, token=token,
        key=key("series-other-owner")), 404, "not_found")

    # The same request key from the failed attempt remains available.
    future_policy = policy((dt.date.fromisoformat(day) + dt.timedelta(days=7)).isoformat(),
                           duration=120, capacities={"t_1": 2, "t_2": 4, "t_3": 6})
    publish(base, token, future_policy)
    successful_body = {**adopt_body, "ignored": "ignored", "count": 3}
    before_adoption_revision = restaurant_revision(base)
    adopted = s1.expect(s1.call(base, "/series", "POST", successful_body,
                                token=token, key=adopt_key), 201).body
    assert restaurant_revision(base) == before_adoption_revision + 1
    assert len(adopted["occurrences"]) == 3
    assert adopted["occurrences"][0]["index"] == 0
    assert adopted["occurrences"][0]["reservation"] == anchor_before
    first, second, third = [row["reservation"] for row in adopted["occurrences"]]
    assert first["reference"] == anchor["reference"]
    assert second["starts_at_local"] == f"{(dt.date.fromisoformat(day) + dt.timedelta(days=7)).isoformat()}T19:00"
    assert first["accepted_terms"]["policy_version"] == 0
    assert second["accepted_terms"]["policy_version"] == 1
    assert second["accepted_terms"]["reservation_duration_minutes"] == 120
    assert third["starts_at_local"] == f"{(dt.date.fromisoformat(day) + dt.timedelta(days=14)).isoformat()}T19:00"
    assert len({row["reservation"]["reference"] for row in adopted["occurrences"]}) == 3
    assert [row["exception"] for row in adopted["occurrences"]] == [False, False, False]
    current = series(base, adopted["series_id"], token)
    assert current == adopted
    s1.expect(s1.call(base, "/series", "POST", adopt_body, token=token,
                      key=key("already-adopted")), 409, "already_in_series")
    for auth in (None, other_token):
        s1.expect(s1.call(base, f"/series/{adopted['series_id']}", token=auth),
                  404, "not_found")
    listed = {row["reference"] for row in reservations(base, token)}
    assert {first["reference"], second["reference"], third["reference"]} <= listed
    assert history(base, second["reference"], token)["entries"][0]["event"] == "created"

    # No-op, real amendment, cancellation and anchor cancellation have distinct
    # exception/revision semantics; the original adoption receipt stays stable.
    no_op = s1.expect(s1.call(base, f"/reservations/{second['reference']}", "PATCH", {
        "table_id": second["table_id"], "starts_at_local": second["starts_at_local"],
        "party_size": second["party_size"]}, token=token), 200).body
    assert no_op == second
    assert series(base, adopted["series_id"], token)["revision"] == 1
    assert len(history(base, second["reference"], token)["entries"]) == 1

    changed = s1.expect(s1.call(base, f"/reservations/{second['reference']}", "PATCH", {
        "table_id": "t_3", "expected_revision": 1}, token=token), 200).body
    after_change = series(base, adopted["series_id"], token)
    assert after_change["revision"] == 2
    assert after_change["occurrences"][1]["exception"] is True
    assert changed["revision"] == 2
    changed_history = history(base, second["reference"], token)["entries"]
    assert len(changed_history) == 2 and changed_history[1]["event"] == "changed"

    cancelled_second = s1.expect(s1.call(
        base, f"/reservations/{second['reference']}/cancel", "POST", token=token), 200).body
    after_cancel = series(base, adopted["series_id"], token)
    assert after_cancel["revision"] == 3
    assert after_cancel["occurrences"][1]["exception"] is True
    assert cancelled_second["status"] == "cancelled"
    sibling = reservation(base, first["reference"], token)
    assert sibling["status"] == "confirmed"
    cancelled_anchor = s1.expect(s1.call(
        base, f"/reservations/{first['reference']}/cancel", "POST", token=token), 200).body
    after_anchor_cancel = series(base, adopted["series_id"], token)
    assert after_anchor_cancel["revision"] == 4
    assert after_anchor_cancel["occurrences"][0]["reservation"]["status"] == "cancelled"
    assert after_anchor_cancel["occurrences"][1]["reservation"]["status"] == "cancelled"
    assert after_anchor_cancel["occurrences"][2]["reservation"]["status"] == "confirmed"
    assert after_anchor_cancel["occurrences"][0]["exception"] is False
    assert after_anchor_cancel["occurrences"][1]["exception"] is True
    assert after_anchor_cancel["occurrences"][2]["exception"] is False
    cancelled_third = s1.expect(s1.call(
        base, f"/reservations/{third['reference']}/cancel", "POST", token=token), 200).body
    after_third_cancel = series(base, adopted["series_id"], token)
    assert after_third_cancel["revision"] == 5 and cancelled_third["status"] == "cancelled"
    assert after_third_cancel["occurrences"][2]["exception"] is False
    repeated = s1.expect(s1.call(
        base, f"/reservations/{first['reference']}/cancel", "POST", token=token), 200).body
    assert repeated == cancelled_anchor
    assert series(base, adopted["series_id"], token)["revision"] == 5
    receipt = s1.expect(s1.call(base, "/series", "POST", successful_body,
                                token=token, key=adopt_key), 200).body
    assert receipt == adopted
    assert series(base, adopted["series_id"], token)["revision"] == 5

    # Exercise both inclusive upper bounds without a large bespoke fixture.
    top_anchor = create(base, token,
                        (dt.date.fromisoformat(day) + dt.timedelta(days=28)).isoformat(),
                        table="t_3", party=5)
    top = s1.expect(s1.call(base, "/series", "POST", {
        "anchor_reference": top_anchor["reference"], "count": 12,
        "interval_weeks": 4}, token=token, key=key("series-upper-bounds")), 201).body
    assert len(top["occurrences"]) == 12
    assert top["interval_weeks"] == 4

    data, owner, _ = fixture()
    s1.reset(base, data)
    token = s1.login(base, owner)
    cancelled = create(base, token, s1.local_date(14))
    s1.expect(s1.call(base, f"/reservations/{cancelled['reference']}/cancel", "POST",
                      token=token), 200)
    s1.expect(s1.call(base, "/series", "POST", {
        "anchor_reference": cancelled["reference"], "count": 2,
        "interval_weeks": 1}, token=token, key=key("cancelled-anchor")),
        409, "reservation_cancelled")

    data, owner, _ = fixture(cutoff=10080)
    s1.reset(base, data)
    token = s1.login(base, owner)
    within_cutoff = create(base, token, s1.local_date(2))
    s1.expect(s1.call(base, "/series", "POST", {
        "anchor_reference": within_cutoff["reference"], "count": 2,
        "interval_weeks": 1}, token=token, key=key("series-cutoff")),
        409, "cutoff_passed")
    print("PASS Stage 3 series authorization, atomic failure/key reuse, policy dates, owner reads, exceptions, cancellations, and original replay")


def _next_local_transition(day_from: dt.date, *, gap: bool) -> dt.date:
    zone = ZoneInfo("Europe/Berlin")
    for offset in range(1, 730):
        day = day_from + dt.timedelta(days=offset)
        local = dt.datetime.combine(day, dt.time(2, 30))
        first = local.replace(tzinfo=zone, fold=0)
        second = local.replace(tzinfo=zone, fold=1)
        roundtrip_first = first.astimezone(dt.timezone.utc).astimezone(zone).replace(tzinfo=None)
        ambiguous = first.utcoffset() != second.utcoffset() and roundtrip_first == local
        nonexistent = roundtrip_first != local
        if (gap and nonexistent) or (not gap and ambiguous):
            return day
    raise AssertionError("could not locate a Berlin 02:30 DST transition within two years")


def check_series_dst(base: str) -> None:
    zone = ZoneInfo("Europe/Berlin")
    spring = _next_local_transition(dt.date.today(), gap=True)
    anchor_day = spring - dt.timedelta(days=7)
    owner = s1.user(101)
    restaurant = s1.restaurant(RID, timezone="Europe/Berlin", opens="01:00", closes="04:00")
    restaurant["manager_user_ids"] = [owner["id"]]
    s1.reset(base, s1.fixture(users=[owner], restaurants=[restaurant]))
    token = s1.login(base, owner)
    anchor = create(base, token, anchor_day.isoformat(), at="02:30", party=2)
    before = {row["reference"] for row in reservations(base, token)}
    s1.expect(s1.call(base, "/series", "POST", {
        "anchor_reference": anchor["reference"], "count": 2, "interval_weeks": 1},
        token=token, key=key("series-gap")), 422, "invalid_local_time")
    assert {row["reference"] for row in reservations(base, token)} == before

    fall = _next_local_transition(spring + dt.timedelta(days=1), gap=False)
    anchor_day = fall - dt.timedelta(days=7)
    anchor = create(base, token, anchor_day.isoformat(), at="02:30", party=2)
    adopted = s1.expect(s1.call(base, "/series", "POST", {
        "anchor_reference": anchor["reference"], "count": 2, "interval_weeks": 1},
        token=token, key=key("series-fold")), 201).body
    folded = adopted["occurrences"][1]["reservation"]
    expected = dt.datetime.combine(fall, dt.time(2, 30)).replace(
        tzinfo=zone, fold=0).utcoffset()
    assert dt.datetime.fromisoformat(folded["starts_at"]).utcoffset() == expected
    print("PASS recurring local dates reject a DST gap atomically and choose the first fold")


def check_combined_table_history(base: str) -> None:
    data, owner, _ = fixture(pair=True)
    s1.reset(base, data)
    token = s1.login(base, owner)
    day = s1.local_date(14)
    publish(base, token, policy(day, capacities={"t_1": 1, "t_2": 2, "t_3": 6}))
    single = create(base, token, day, table="t_3", party=3)
    s1.expect(s1.call(base, f"/reservations/{single['reference']}", "PATCH", {
        "table_ids": ["t_2", "t_1"], "party_size": 4}, token=token),
        422, "party_exceeds_capacity")
    assert reservation(base, single["reference"], token) == single
    pair_body = {"table_ids": ["t_2", "t_1"]}
    paired = s1.expect(s1.call(base, f"/reservations/{single['reference']}", "PATCH",
                               pair_body, token=token), 200).body
    assert paired["table_ids"] == ["t_1", "t_2"] and "table_id" not in paired
    assert paired["accepted_terms"]["capacities"] == {"t_1": 1, "t_2": 2, "t_3": 6}
    assert paired["accepted_terms"]["policy_version"] == 1
    entries = history(base, single["reference"], token)["entries"]
    assert [row["seq"] for row in entries] == [1, 2]
    assert entries[0]["changes"] == [
        {"field": "table_id", "from": None, "to": "t_3"},
        {"field": "starts_at_local", "from": None, "to": f"{day}T19:00"},
        {"field": "party_size", "from": None, "to": 3},
    ]
    assert entries[1]["changes"] == [
        {"field": "table_ids", "from": ["t_3"], "to": ["t_1", "t_2"]}]
    assert entries[1]["accepted_terms"] == paired["accepted_terms"]
    before = copy.deepcopy(entries)
    reversed_noop = s1.expect(s1.call(base, f"/reservations/{single['reference']}", "PATCH",
                                     {"table_ids": ["t_2", "t_1"]}, token=token), 200).body
    after_reversed = history(base, single["reference"], token)["entries"]
    noop_failures = []
    if reversed_noop != paired:
        noop_failures.append(
            f"revision {paired['revision']} -> {reversed_noop['revision']}")
    if after_reversed != before:
        noop_failures.append(f"history entries {len(before)} -> {len(after_reversed)}")
    created_pair = s1.expect(s1.call(base, "/reservations", "POST", {
        "restaurant_id": RID, "table_ids": ["t_2", "t_1"],
        "starts_at_local": f"{day}T21:00", "party_size": 3,
    }, token=token, key=key("pair-created-history")), 201).body
    assert created_pair["table_ids"] == ["t_1", "t_2"]
    pair_creation = history(base, created_pair["reference"], token)["entries"][0]
    assert pair_creation["changes"] == [
        {"field": "table_ids", "from": None, "to": ["t_1", "t_2"]},
        {"field": "starts_at_local", "from": None, "to": f"{day}T21:00"},
        {"field": "party_size", "from": None, "to": 3},
    ]
    pair_series = s1.expect(s1.call(base, "/series", "POST", {
        "anchor_reference": created_pair["reference"], "count": 2, "interval_weeks": 1,
    }, token=token, key=key("pair-move-noop-series")), 201).body
    series_before_move_noop = series(base, pair_series["series_id"], token)
    move_history_before = history(base, created_pair["reference"], token)["entries"]
    restaurant_before_move_noop = restaurant_revision(base)
    reversed_pair_move = s1.expect(s1.call(base, "/reservation-moves", "POST", {
        "moves": [{"reference": created_pair["reference"],
                   "table_ids": ["t_2", "t_1"], "expected_revision": 1}],
    }, token=token, key=key("reversed-pair-collective-noop")), 201).body
    if reversed_pair_move["reservations"] != [created_pair]:
        noop_failures.append("reversed pair collective move changed the receipt")
    if history(base, created_pair["reference"], token)["entries"] != move_history_before:
        noop_failures.append("reversed pair collective move appended history")
    if restaurant_revision(base) != restaurant_before_move_noop:
        noop_failures.append("reversed pair collective move changed restaurant revision")
    if series(base, pair_series["series_id"], token) != series_before_move_noop:
        noop_failures.append("reversed pair collective move changed series revision or exceptions")
    single_again = s1.expect(s1.call(base, f"/reservations/{single['reference']}", "PATCH",
                                     {"table_id": "t_3"}, token=token), 200).body
    assert single_again["table_ids"] == ["t_3"]
    final_entry = history(base, single["reference"], token)["entries"][-1]
    assert final_entry["changes"] == [
        {"field": "table_ids", "from": ["t_1", "t_2"], "to": ["t_3"]}]
    assert not noop_failures, "reversed input for the same declared pair changed the reservation: " + ", ".join(noop_failures)
    print("PASS pair PATCH and collective-move no-ops preserve reservation history, series state and revisions")


def check_collective_moves_and_series_revision(base: str) -> None:
    data, owner, _ = fixture(pair=True)
    s1.reset(base, data)
    token = s1.login(base, owner)
    day = s1.local_date(14)
    left = create(base, token, day, table="t_1", party=2)
    right = create(base, token, day, table="t_2", party=2)
    before_swap_revision = restaurant_revision(base)
    swap_key = key("policy-swap")
    swap = {"moves": [
        {"reference": left["reference"], "table_id": "t_2", "expected_revision": 1},
        {"reference": right["reference"], "table_id": "t_1", "expected_revision": 1},
    ]}
    swapped = s1.expect(s1.call(base, "/reservation-moves", "POST", swap,
                                token=token, key=swap_key), 201).body
    assert restaurant_revision(base) == before_swap_revision + 1
    assert [row["table_id"] for row in swapped["reservations"]] == ["t_2", "t_1"]
    for original in (left, right):
        entries = history(base, original["reference"], token)["entries"]
        assert len(entries) == 2 and entries[-1]["event"] == "changed"
        assert entries[-1]["revision"] == 2
    after_swap_refs = [row["reference"] for row in swapped["reservations"]]
    assert after_swap_refs == [left["reference"], right["reference"]]
    replay = s1.expect(s1.call(base, "/reservation-moves", "POST", swap,
                               token=token, key=swap_key), 200).body
    assert replay == swapped
    assert restaurant_revision(base) == before_swap_revision + 1

    no_op_before = restaurant_revision(base)
    before_entries = history(base, left["reference"], token)["entries"]
    no_op_move = {"moves": [{"reference": left["reference"], "table_id": "t_2",
                              "expected_revision": 2}]}
    s1.expect(s1.call(base, "/reservation-moves", "POST", no_op_move,
                      token=token, key=key("move-no-op")), 201)
    assert restaurant_revision(base) == no_op_before
    assert history(base, left["reference"], token)["entries"] == before_entries
    stale_move = {"moves": [{"reference": left["reference"], "table_id": "t_1",
                              "expected_revision": 1}]}
    s1.expect(s1.call(base, "/reservation-moves", "POST", stale_move,
                      token=token, key=key("move-stale")), 409, "stale_revision")
    assert restaurant_revision(base) == no_op_before
    assert history(base, left["reference"], token)["entries"] == before_entries

    # Build a series, then prove that a failed collective write changes neither
    # reservations, histories, nor the series revision/exception set.
    anchor = create(base, token, day, table="t_1", party=2, at="20:30")
    before_adopt_revision = restaurant_revision(base)
    adopted = s1.expect(s1.call(base, "/series", "POST", {
        "anchor_reference": anchor["reference"], "count": 3, "interval_weeks": 1},
        token=token, key=key("move-series-adopt")), 201).body
    assert restaurant_revision(base) == before_adopt_revision + 1
    occurrences = [row["reservation"] for row in adopted["occurrences"]]
    blocker = create(base, token, occurrences[1]["starts_at_local"][:10],
                     table="t_3", party=2, at="20:30")
    move_batch = {"moves": [
        {"reference": occurrences[0]["reference"], "table_id": "t_3", "expected_revision": 1},
        {"reference": occurrences[1]["reference"], "table_id": "t_3", "expected_revision": 1},
    ]}
    batch_key = key("series-move-atomic")
    before_batch_revision = restaurant_revision(base)
    s1.expect(s1.call(base, "/reservation-moves", "POST", move_batch,
                      token=token, key=batch_key), 409, "table_unavailable")
    assert restaurant_revision(base) == before_batch_revision
    unchanged = series(base, adopted["series_id"], token)
    assert unchanged["revision"] == 1
    assert [row["exception"] for row in unchanged["occurrences"]] == [False, False, False]
    assert [len(history(base, row["reference"], token)["entries"])
            for row in occurrences] == [1, 1, 1]
    s1.expect(s1.call(base, f"/reservations/{blocker['reference']}/cancel", "POST",
                      token=token), 200)
    before_success_revision = restaurant_revision(base)
    moved = s1.expect(s1.call(base, "/reservation-moves", "POST", move_batch,
                              token=token, key=batch_key), 201).body
    assert restaurant_revision(base) == before_success_revision + 1
    assert len(moved["reservations"]) == 2
    moved_series = series(base, adopted["series_id"], token)
    assert moved_series["revision"] == 2
    assert [row["exception"] for row in moved_series["occurrences"]] == [True, True, False]
    assert [len(history(base, row["reference"], token)["entries"])
            for row in occurrences] == [2, 2, 1]
    replay = s1.expect(s1.call(base, "/reservation-moves", "POST", move_batch,
                               token=token, key=batch_key), 200).body
    assert replay == moved
    assert series(base, adopted["series_id"], token)["revision"] == 2
    assert restaurant_revision(base) == before_success_revision + 1
    assert s1.expect(s1.call(base, "/reservation-moves", "POST", swap,
                             token=token, key=swap_key), 200).body == swapped
    assert restaurant_revision(base) == before_success_revision + 1
    print("PASS policy-aware collective swap, atomic series rollback, shared series revision, exceptions, and move replay")


def check_stage1_import_and_adopt(source: str, target: str) -> None:
    account = s1.user(111)
    restaurant = s1.restaurant("r_stage1_import")
    s1.reset(source, s1.fixture(users=[account], restaurants=[restaurant]))
    token = s1.login(source, account)
    day = s1.local_date(14)
    body = {"restaurant_id": restaurant["id"], "table_id": "t_2",
            "starts_at_local": f"{day}T19:00", "party_size": 4}
    create_key, move_key = key("stage1-import-create"), key("stage1-import-move")
    created = s1.expect(s1.call(source, "/reservations", "POST", body,
                                token=token, key=create_key), 201).body
    move_body = {"moves": [{"reference": created["reference"], "table_id": "t_3"}]}
    moved = s1.expect(s1.call(source, "/reservation-moves", "POST", move_body,
                              token=token, key=move_key), 201).body
    snapshot = s1.expect(s1.call(source, "/_test/export"), 200).body
    s1.reset(target, s1.fixture(users=[s1.user(112)],
                                restaurants=[s1.restaurant("r_discarded")] ))
    s1.expect(s1.call(target, "/_test/import", "POST", snapshot, timeout=10), 204)
    assert s1.expect(s1.call(target, "/reservations", token=token), 200).body["reservations"][0]["reference"] == created["reference"]
    create_replay = s1.expect(s1.call(target, "/reservations", "POST", body,
                                      token=token, key=create_key), 200).body
    move_replay = s1.expect(s1.call(target, "/reservation-moves", "POST", move_body,
                                    token=token, key=move_key), 200).body
    assert create_replay == created and move_replay == moved
    current = reservation(target, created["reference"], token)
    adopted = s1.expect(s1.call(target, "/series", "POST", {
        "anchor_reference": created["reference"], "count": 2, "interval_weeks": 1},
        token=token, key=key("adopt-stage1-import")), 201).body
    assert adopted["occurrences"][0]["reservation"] == current
    assert adopted["occurrences"][0]["reservation"]["table_id"] == "t_3"
    assert s1.expect(s1.call(target, "/reservations", "POST", body,
                             token=token, key=create_key), 200).body == created
    assert s1.expect(s1.call(target, "/reservation-moves", "POST", move_body,
                             token=token, key=move_key), 200).body == moved
    print("PASS populated Stage 1 import retains session and exact create/move receipts; imported booking adopts")


def check_stage2_import_and_adopt(source: str, target: str) -> None:
    data = s2.pair_fixture()
    s1.reset(source, data)
    token = s2.token_for(source)
    day = s1.local_date(14)
    create_body = {"restaurant_id": "r_combo", "starts_at_local": f"{day}T19:00",
                   "party_size": 5, "table_ids": ["t_a", "t_c"]}
    create_key, move_key = key("stage2-import-create"), key("stage2-import-move")
    created = s1.expect(s1.call(source, "/reservations", "POST", create_body,
                                token=token, key=create_key), 201).body
    move_body = {"moves": [{"reference": created["reference"], "table_id": "t_d"}]}
    moved = s1.expect(s1.call(source, "/reservation-moves", "POST", move_body,
                              token=token, key=move_key), 201).body
    snapshot = s1.expect(s1.call(source, "/_test/export"), 200).body
    s1.reset(target, s1.fixture(users=[s1.user(113)],
                                restaurants=[s1.restaurant("r_discarded")]))
    s1.expect(s1.call(target, "/_test/import", "POST", snapshot, timeout=10), 204)
    assert s1.expect(s1.call(target, "/reservations", token=token), 200).body["reservations"][0]["reference"] == created["reference"]
    assert s1.expect(s1.call(target, "/reservations", "POST", create_body,
                             token=token, key=create_key), 200).body == created
    assert s1.expect(s1.call(target, "/reservation-moves", "POST", move_body,
                             token=token, key=move_key), 200).body == moved
    current = reservation(target, created["reference"], token)
    assert current["table_ids"] == ["t_d"]
    adopted = s1.expect(s1.call(target, "/series", "POST", {
        "anchor_reference": created["reference"], "count": 2, "interval_weeks": 1},
        token=token, key=key("adopt-stage2-import")), 201).body
    assert adopted["occurrences"][0]["reservation"] == current
    assert adopted["occurrences"][0]["reservation"]["accepted_terms"]["policy_version"] == 0
    assert s1.expect(s1.call(target, "/reservation-moves", "POST", move_body,
                             token=token, key=move_key), 200).body == moved
    print("PASS populated Stage 2 pair import retains session, pair-upgrade receipt, and supports adoption")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Stage 3 service under test")
    parser.add_argument("--stage1-url", required=True, help="populated Stage 1 export source")
    parser.add_argument("--stage2-url", required=True, help="populated Stage 2 export source")
    parser.add_argument("--result-json", help="optional sanitized result summary path")
    args = parser.parse_args()

    checks = [
        check_policy_selection_validation_and_explanations,
        check_history_accepted_terms_and_revision_rules,
        check_old_cutoff_precedence_and_concurrent_revision,
        check_series_atomicity_and_lifecycle,
        check_series_dst,
        check_combined_table_history,
        check_collective_moves_and_series_revision,
    ]
    for check in checks:
        check(args.base_url)
    check_stage1_import_and_adopt(args.stage1_url, args.base_url)
    check_stage2_import_and_adopt(args.stage2_url, args.base_url)
    max_request = max(s1.REQUEST_TIMINGS, default=0.0)
    max_control = max(s1.CONTROL_TIMINGS, default=0.0)
    assert max_request < 5 and max_control < 10, (
        f"request/control limit exceeded: {max_request:.3f}s/{max_control:.3f}s")
    print(f"TIMING requests={len(s1.REQUEST_TIMINGS)} max_request_ms={max_request * 1000:.1f} "
          f"controls={len(s1.CONTROL_TIMINGS)} max_control_ms={max_control * 1000:.1f}")
    if args.result_json:
        with open(args.result_json, "w", encoding="utf-8", newline="\n") as stream:
            json.dump({"independent_check_functions": len(checks),
                       "stage1_import": "pass", "stage2_import": "pass",
                       "request_count": len(s1.REQUEST_TIMINGS),
                       "max_request_ms": round(max_request * 1000, 1),
                       "control_count": len(s1.CONTROL_TIMINGS),
                       "max_control_ms": round(max_control * 1000, 1)},
                      stream, indent=2)
            stream.write("\n")
    print("PASS independent Stage 3 API checks")


if __name__ == "__main__":
    main()
