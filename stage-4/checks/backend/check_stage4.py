from __future__ import annotations

import datetime as dt
import itertools
import tempfile
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zoneinfo import ZoneInfo

from check_stage3 import (PARENT, call, date_after, expect, expect_empty, fixture,
                          free_port, login, make_booking, policy, run_populated_upgrade,
                          run_stage3, start_server, wait_ready)


ROOT = Path(__file__).resolve().parents[2]


def instant(date: str, at: str) -> str:
    hour, minute = (int(part) for part in at.split(":"))
    return dt.datetime.combine(dt.date.fromisoformat(date), dt.time(hour, minute),
                               ZoneInfo("Europe/Berlin")).isoformat(timespec="seconds")


def _fixture_with_pairs():
    data = fixture()
    data["restaurants"][0]["combinable"] = [["t_1", "t_2"], ["t_2", "t_3"]]
    return data


def check_replan_apply_and_closure(base):
    data = _fixture_with_pairs()
    expect_empty(base, "POST", "/_test/reset", data)
    ada = login(base)
    date = date_after(35)
    _, affected = make_booking(base, ada, date, table="t_2", party=4,
                               key="replan-affected")
    _, fixed = make_booking(base, ada, date, table="t_1", party=2,
                            key="replan-fixed")
    series = expect(base, "POST", "/series", 201,
                    {"anchor_reference": affected["reference"], "count": 2,
                     "interval_weeks": 1}, ada, "replan-series")
    series_path = f"/series/{series['series_id']}"
    series_before = expect(base, "GET", series_path, 200, token=ada)
    before = expect(base, "GET", "/_test/export", 200)["state"]
    next_date = (dt.date.fromisoformat(date) + dt.timedelta(weeks=1)).isoformat()
    request_body = {"table_id": "t_2", "from": instant(date, "18:00"),
                    "to": instant(next_date, "23:00")}
    path = "/restaurants/r_anker/replans"
    plan = expect(base, "POST", path, 201, request_body, ada, "replan-preview")
    assert plan["restaurant_revision"] == before["restaurants"][0]["restaurant_revision"]
    assert plan["closure"] == request_body
    assert plan["moved_count"] == 2 and plan["unused_seats"] == 4
    assert plan["assignments"] == [
        {"reference": row["reference"],
         "table_ids": ["t_3"] if row["reference"] in {
             affected["reference"], series["occurrences"][1]["reference"]} else ["t_1"],
         "changed": row["reference"] in {
             affected["reference"], series["occurrences"][1]["reference"]}}
        for row in sorted((affected, fixed, series_before["occurrences"][1]["reservation"]),
                          key=lambda item: item["reference"])]
    after_preview = expect(base, "GET", "/_test/export", 200)["state"]
    assert after_preview["reservations"] == before["reservations"]
    assert after_preview["restaurants"] == before["restaurants"]
    assert after_preview["series"] == before["series"]
    assert expect(base, "POST", path, 200, request_body, ada,
                  "replan-preview") == plan

    apply_path = f"{path}/{plan['plan_id']}/apply"
    applied = expect(base, "POST", apply_path, 201, {}, ada, "replan-apply")
    changed = next(row for row in applied["reservations"]
                   if row["reference"] == affected["reference"])
    unchanged = next(row for row in applied["reservations"]
                     if row["reference"] == fixed["reference"])
    changed_later = next(row for row in applied["reservations"]
                         if row["reference"] == series["occurrences"][1]["reference"])
    assert changed["table_ids"] == ["t_3"] and changed["revision"] == 2
    assert changed["starts_at_local"] == affected["starts_at_local"]
    assert changed["party_size"] == affected["party_size"]
    assert changed["accepted_terms"] == affected["accepted_terms"]
    assert unchanged["table_ids"] == ["t_1"] and unchanged["revision"] == 1
    assert changed_later["table_ids"] == ["t_3"] and changed_later["revision"] == 2
    history = expect(base, "GET", f"/reservations/{affected['reference']}/history",
                     200, token=ada)["entries"]
    assert history[-1]["event"] == "reassigned"
    assert history[-1]["plan_id"] == plan["plan_id"]
    assert history[-1]["changes"] == [
        {"field": "table_ids", "from": ["t_2"], "to": ["t_3"]}]
    after_apply = expect(base, "GET", "/_test/export", 200)["state"]
    assert after_apply["restaurants"][0]["restaurant_revision"] == (
        before["restaurants"][0]["restaurant_revision"] + 1)
    closure = after_apply["restaurants"][0]["closures"][0]
    assert closure["table_id"] == "t_2" and closure["plan_id"] == plan["plan_id"]
    series_after = expect(base, "GET", series_path, 200, token=ada)
    assert series_after["revision"] == series_before["revision"] + 1
    assert [row["exception"] for row in series_after["occurrences"]] == [False, False]
    assert [row["reservation"]["starts_at_local"] for row in series_after["occurrences"]] == [
        row["reservation"]["starts_at_local"] for row in series_before["occurrences"]]
    assert [row["reservation"]["table_ids"] for row in series_after["occurrences"]] == [
        ["t_3"], ["t_3"]]

    query = urllib.parse.urlencode({"restaurant_id": "r_anker", "date": date,
                                    "party_size": 2, "explain": "true"})
    slot = next(row for row in expect(base, "GET", "/availability?" + query, 200)["slots"]
                if row["starts_at_local"].endswith("T18:00"))
    t2 = next(row for row in slot["explain"] if row["table_id"] == "t_2")
    assert t2["rules"][1] == {"rule": "no_overlap", "holds": False}
    assert not any("t_2" in option["table_ids"] for option in slot["available_options"])
    blocked = expect(base, "POST", "/reservations", 409,
                     {"restaurant_id": "r_anker", "table_id": "t_2",
                      "starts_at_local": f"{date}T18:00", "party_size": 2},
                     ada, "closed-table-create")
    assert blocked["error"]["code"] == "table_unavailable"
    blocked = expect(base, "PATCH", f"/reservations/{fixed['reference']}", 409,
                     {"table_id": "t_2"}, ada)
    assert blocked["error"]["code"] == "table_unavailable"
    move_failure = expect(base, "POST", "/reservation-moves", 409,
                          {"moves": [{"reference": fixed["reference"],
                                      "table_id": "t_2"}]}, ada, "closed-table-move")
    assert move_failure["error"]["code"] == "table_unavailable"

    expect(base, "POST", f"/reservations/{fixed['reference']}/cancel", 200, token=ada)
    assert expect(base, "POST", apply_path, 200, {}, ada, "replan-apply") == applied
    already_applied = expect(base, "POST", apply_path, 409, {}, ada,
                             "replan-other-key")
    assert already_applied["error"]["code"] == "plan_already_applied"
    assert expect(base, "POST", path, 200, request_body, ada,
                  "replan-preview") == plan
    exported = expect(base, "GET", "/_test/export", 200)["state"]
    expect_empty(base, "POST", "/_test/import", {
        "track": "tablekeeper", "format_version": 1, "state": exported})
    assert expect(base, "GET", "/_test/export", 200)["state"] == exported


def check_replan_oracle_and_races(base):
    data = _fixture_with_pairs()
    expect_empty(base, "POST", "/_test/reset", data)
    ada = login(base)
    date = date_after(42)
    _, first = make_booking(base, ada, date, table="t_1", party=2,
                            key="oracle-first")
    _, second = make_booking(base, ada, date, table="t_2", party=4,
                             key="oracle-second")
    rows = sorted((first, second), key=lambda row: row["reference"])
    options = [([table["id"]], table["capacity"], rank)
               for rank, table in enumerate(data["restaurants"][0]["tables"])]
    pair_offset = len(options)
    for index, pair in enumerate(data["restaurants"][0]["combinable"]):
        canonical = [table["id"] for table in data["restaurants"][0]["tables"]
                     if table["id"] in pair]
        options.append((canonical, sum(next(t["capacity"] for t in data["restaurants"][0]["tables"]
                                                  if t["id"] == table_id)
                                       for table_id in canonical), pair_offset + index))
    candidates = []
    for choice in itertools.product(options, repeat=len(rows)):
        if any(option[1] < row["party_size"] or "t_1" in option[0]
               for row, option in zip(rows, choice)):
            continue
        if set(choice[0][0]).intersection(choice[1][0]):
            continue
        moved = sum(option[0] != row["table_ids"] for row, option in zip(rows, choice))
        unused = sum(option[1] - row["party_size"] for row, option in zip(rows, choice))
        candidates.append(((moved, unused, tuple(option[2] for option in choice)), choice))
    oracle_score, oracle_choice = min(candidates, key=lambda pair: pair[0])
    closure = {"table_id": "t_1", "from": instant(date, "18:00"),
               "to": instant(date, "23:00")}
    path = "/restaurants/r_anker/replans"
    plan = expect(base, "POST", path, 201, closure, ada, "oracle-plan")
    assert plan["moved_count"] == oracle_score[0]
    assert plan["unused_seats"] == oracle_score[1]
    assert [(item["table_ids"], item["changed"]) for item in plan["assignments"]] == [
        (option[0], option[0] != row["table_ids"])
        for row, option in zip(rows, oracle_choice)]
    assert plan["moved_count"] == 1, "primary objective must beat lower unused seats"

    apply_path = f"{path}/{plan['plan_id']}/apply"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: call(base, "POST", apply_path, {}, ada,
                                                "oracle-apply"), range(2)))
    assert sorted(result[0] for result in results) == [200, 201], results
    assert results[0][1] == results[1][1]
    assert expect(base, "POST", apply_path, 409, {}, ada,
                  "oracle-apply-other")["error"]["code"] == "plan_already_applied"

    # A later write does not alter the successful apply receipt.
    _, later = make_booking(base, ada, date_after(43), table="t_3", party=2,
                            key="oracle-later")
    assert expect(base, "POST", apply_path, 200, {}, ada,
                  "oracle-apply") == results[0][1]

    other_date = date_after(44)
    other_closure = {"table_id": "t_2", "from": instant(other_date, "18:00"),
                     "to": instant(other_date, "23:00")}
    other_plan = expect(base, "POST", path, 201, other_closure, ada,
                        "race-plan-preview")
    other_apply = f"{path}/{other_plan['plan_id']}/apply"
    before_race = expect(base, "GET", "/_test/export", 200)["state"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        distinct = list(pool.map(lambda key: call(base, "POST", other_apply, {}, ada, key),
                                 ("race-apply-a", "race-apply-b")))
    assert sorted(result[0] for result in distinct) == [201, 409], distinct
    failure = next(result[1] for result in distinct if result[0] == 409)
    assert failure["error"]["code"] == "plan_already_applied"
    after_race = expect(base, "GET", "/_test/export", 200)["state"]
    assert after_race["restaurants"][0]["restaurant_revision"] == (
        before_race["restaurants"][0]["restaurant_revision"] + 1)
    assert len(after_race["restaurants"][0]["closures"]) == (
        len(before_race["restaurants"][0]["closures"]) + 1)


def check_replan_uses_accepted_capacity(base):
    data = _fixture_with_pairs()
    expect_empty(base, "POST", "/_test/reset", data)
    ada = login(base)
    date = date_after(39)
    _, old_terms_booking = make_booking(base, ada, date, table="t_3", at="19:00",
                                        party=5, key="old-capacity-booking")
    expect(base, "POST", "/restaurants/r_anker/policies", 201,
           policy(date, capacities={"t_1": 2, "t_2": 4, "t_3": 4}),
           ada, "lower-capacity-policy")
    assert old_terms_booking["accepted_terms"]["capacities"]["t_3"] == 6
    request = {"table_id": "t_1", "from": instant(date, "18:00"),
               "to": instant(date, "23:00")}
    plan = expect(base, "POST", "/restaurants/r_anker/replans", 201,
                  request, ada, "old-capacity-plan")
    assert plan["assignments"] == [{"reference": old_terms_booking["reference"],
                                    "table_ids": ["t_3"], "changed": False}]
    assert plan["moved_count"] == 0


def check_replan_limits_and_failures(base):
    data = _fixture_with_pairs()
    expect_empty(base, "POST", "/_test/reset", data)
    ada = login(base)
    bob = login(base, "bob@example.com")
    date = date_after(40)
    body = {"table_id": "t_2", "from": instant(date, "18:00"),
            "to": instant(date, "23:00")}
    path = "/restaurants/r_anker/replans"
    assert call(base, "POST", path, body, key="plan-anon")[0] == 401
    assert call(base, "POST", path, body, bob, "plan-nonmanager")[0] == 403
    unknown_table = {**body, "table_id": "missing"}
    assert expect(base, "POST", path, 404, unknown_table, ada,
                  "plan-unknown-table")["error"]["code"] == "not_found"
    invalid_interval = {**body, "to": body["from"]}
    assert expect(base, "POST", path, 422, invalid_interval, ada,
                  "plan-invalid-interval")["error"]["code"] == "validation_failed"

    # Every allowed option is occupied by a fixed booking, so preview must roll back.
    for table, party in (("t_1", 2), ("t_2", 4), ("t_3", 6)):
        make_booking(base, ada, date, table=table, at="19:00", party=party,
                     key=f"no-plan-{table}")
    before = expect(base, "GET", "/_test/export", 200)["state"]
    no_plan = expect(base, "POST", path, 409, body, ada, "no-feasible-plan")
    assert no_plan["error"]["code"] == "no_feasible_plan"
    assert expect(base, "GET", "/_test/export", 200)["state"] == before

    large = fixture()
    large["restaurants"][0]["tables"] = [
        {"id": f"t_{index}", "label": str(index), "capacity": 4}
        for index in range(1, 8)]
    expect_empty(base, "POST", "/_test/reset", large)
    ada = login(base)
    too_many_tables = expect(base, "POST", path, 422,
                             {"table_id": "t_1", "from": instant(date, "18:00"),
                              "to": instant(date, "23:00")}, ada, "too-many-tables")
    assert too_many_tables["error"]["code"] == "planning_limit"

    large["restaurants"][0]["tables"] = [
        {"id": f"t_{index}", "label": str(index), "capacity": 4}
        for index in range(1, 5)]
    # Five declared pairs exceed the supported optimizer bound.
    large["restaurants"][0]["combinable"] = [
        ["t_1", "t_2"], ["t_1", "t_3"], ["t_1", "t_4"], ["t_2", "t_3"],
        ["t_2", "t_4"]]
    expect_empty(base, "POST", "/_test/reset", large)
    ada = login(base)
    too_many_pairs = expect(base, "POST", path, 422,
                            {"table_id": "t_1", "from": instant(date, "18:00"),
                             "to": instant(date, "23:00")}, ada, "too-many-pairs")
    assert too_many_pairs["error"]["code"] == "planning_limit"

    large["restaurants"][0]["combinable"] = []
    expect_empty(base, "POST", "/_test/reset", large)
    ada = login(base)
    for at, tables in (("18:00", ("t_1", "t_2", "t_3")),
                       ("19:30", ("t_1", "t_2", "t_3")),
                       ("21:00", ("t_1",))):
        for table in tables:
            make_booking(base, ada, date, table=table, at=at, party=2,
                         key=f"limit-{at}-{table}")
    too_many_bookings = expect(base, "POST", path, 422,
                               {"table_id": "t_1", "from": instant(date, "18:00"),
                                "to": instant(date, "23:00")}, ada, "too-many-bookings")
    assert too_many_bookings["error"]["code"] == "planning_limit"


def check_cross_restaurant_plan_revision(base):
    data = _fixture_with_pairs()
    other = {**data["restaurants"][0], "id": "r_other", "name": "Other"}
    data["restaurants"].append(other)
    expect_empty(base, "POST", "/_test/reset", data)
    ada = login(base)
    date = date_after(41)
    request = {"table_id": "t_2", "from": instant(date, "18:00"),
               "to": instant(date, "23:00")}
    first = expect(base, "POST", "/restaurants/r_anker/replans", 201,
                   request, ada, "restaurant-plan-a")
    second = expect(base, "POST", "/restaurants/r_other/replans", 201,
                    request, ada, "restaurant-plan-b")
    foreign = expect(base, "POST",
                     f"/restaurants/r_anker/replans/{second['plan_id']}/apply",
                     404, {}, ada, "foreign-plan")
    assert foreign["error"]["code"] == "not_found"
    expect(base, "POST", f"/restaurants/r_other/replans/{second['plan_id']}/apply",
           201, {}, ada, "restaurant-apply-b")
    first_applied = expect(base, "POST",
                           f"/restaurants/r_anker/replans/{first['plan_id']}/apply",
                           201, {}, ada, "restaurant-apply-a")
    assert first_applied["restaurant_revision"] == 1


def check_closure_half_open(base):
    expect_empty(base, "POST", "/_test/reset", _fixture_with_pairs())
    ada = login(base)
    date = date_after(36)
    path = "/restaurants/r_anker/replans"
    body = {"table_id": "t_2", "from": instant(date, "19:00"),
            "to": instant(date, "20:00")}
    plan = expect(base, "POST", path, 201, body, ada, "half-open-plan")
    expect(base, "POST", f"{path}/{plan['plan_id']}/apply", 201, {}, ada,
           "half-open-apply")
    query = urllib.parse.urlencode({"restaurant_id": "r_anker", "date": date,
                                    "party_size": 2, "explain": "true"})
    slots = expect(base, "GET", "/availability?" + query, 200)["slots"]
    before, after = (next(slot for slot in slots
                          if slot["starts_at_local"].endswith(f"T{at}"))
                     for at in ("19:30", "20:00"))
    before_table = next(row for row in before["explain"] if row["table_id"] == "t_2")
    after_table = next(row for row in after["explain"] if row["table_id"] == "t_2")
    assert before_table["rules"][1]["holds"] is False
    assert after_table["rules"][1]["holds"] is True
    assert {"table_ids": ["t_2"], "capacity": 4} in after["available_options"]


def check_series_amend_respects_closures(base):
    expect_empty(base, "POST", "/_test/reset", _fixture_with_pairs())
    ada = login(base)
    date = date_after(37)
    _, anchor = make_booking(base, ada, date, table="t_2", at="20:30", party=2,
                             key="closure-series-anchor")
    series = expect(base, "POST", "/series", 201,
                    {"anchor_reference": anchor["reference"], "count": 2,
                     "interval_weeks": 1}, ada, "closure-series-create")
    body = {"table_id": "t_2", "from": instant(date, "19:00"),
            "to": instant(date, "20:00")}
    path = "/restaurants/r_anker/replans"
    plan = expect(base, "POST", path, 201, body, ada, "closure-series-plan")
    expect(base, "POST", f"{path}/{plan['plan_id']}/apply", 201, {}, ada,
           "closure-series-plan-apply")
    before = expect(base, "GET", "/_test/export", 200)["state"]
    blocked = expect(base, "POST", f"/series/{series['series_id']}/amend", 409,
                     {"expected_revision": 1, "from_index": 0,
                      "local_time": "19:30"}, ada, "closed-series-amend")
    assert blocked["error"]["code"] == "table_unavailable"
    assert expect(base, "GET", "/_test/export", 200)["state"] == before


def check_series_creation_respects_closures(base):
    expect_empty(base, "POST", "/_test/reset", _fixture_with_pairs())
    ada = login(base)
    date = date_after(49)
    next_date = (dt.date.fromisoformat(date) + dt.timedelta(weeks=1)).isoformat()
    _, anchor = make_booking(base, ada, date, table="t_2", at="19:00", party=2,
                             key="blocked-series-anchor")
    path = "/restaurants/r_anker/replans"
    closure = {"table_id": "t_2", "from": instant(next_date, "18:00"),
               "to": instant(next_date, "23:00")}
    plan = expect(base, "POST", path, 201, closure, ada, "blocked-series-plan")
    expect(base, "POST", f"{path}/{plan['plan_id']}/apply", 201, {}, ada,
           "blocked-series-plan-apply")
    before = expect(base, "GET", "/_test/export", 200)["state"]
    status, payload, _ = call(base, "POST", "/series", {
        "anchor_reference": anchor["reference"], "count": 2,
        "interval_weeks": 1}, ada, "blocked-series-create")
    assert status == 409 and payload["error"]["code"] == "table_unavailable"
    assert expect(base, "GET", "/_test/export", 200)["state"] == before


def check_stale_replan_and_stage3_upgrade(stage3, stage4):
    data = _fixture_with_pairs()
    expect_empty(stage4, "POST", "/_test/reset", data)
    ada = login(stage4)
    date = date_after(38)
    closure = {"table_id": "t_2", "from": instant(date, "18:00"),
               "to": instant(date, "23:00")}
    plan = expect(stage4, "POST", "/restaurants/r_anker/replans", 201,
                  closure, ada, "stale-plan")
    make_booking(stage4, ada, date_after(45), table="t_1", party=2,
                 key="stale-plan-intervening")
    before = expect(stage4, "GET", "/_test/export", 200)["state"]
    failure = expect(stage4, "POST",
                      f"/restaurants/r_anker/replans/{plan['plan_id']}/apply", 409,
                      {}, ada, "stale-plan-apply")
    assert failure["error"]["code"] == "stale_plan"
    after = expect(stage4, "GET", "/_test/export", 200)["state"]
    assert after == before

    source_fixture = _fixture_with_pairs()
    expect_empty(stage3, "POST", "/_test/reset", source_fixture)
    token = login(stage3)
    booking_body = {"restaurant_id": "r_anker", "table_id": "t_2",
                    "starts_at_local": f"{date}T19:00", "party_size": 4}
    original_booking = expect(stage3, "POST", "/reservations", 201,
                              booking_body, token, "import-original-booking")
    expect(stage3, "PATCH", f"/reservations/{original_booking['reference']}", 200,
           {"table_id": "t_3", "starts_at_local": f"{date}T20:00"}, token)
    original_series_body = {"anchor_reference": original_booking["reference"],
                            "count": 2, "interval_weeks": 1}
    original_series = expect(stage3, "POST", "/series", 201,
                              original_series_body, token, "import-original-series")
    exception_ref = original_series["occurrences"][0]["reference"]
    expect(stage3, "PATCH", f"/reservations/{exception_ref}", 200,
           {"starts_at_local": f"{date}T21:00"}, token)
    source_state = expect(stage3, "GET", "/_test/export", 200)["state"]
    expect_empty(stage4, "POST", "/_test/import", {
        "track": "tablekeeper", "format_version": 1, "state": source_state})
    assert expect(stage4, "POST", "/reservations", 200, booking_body, token,
                  "import-original-booking") == original_booking
    assert expect(stage4, "POST", "/series", 200, original_series_body, token,
                  "import-original-series") == original_series
    history = expect(stage4, "GET", f"/reservations/{exception_ref}/history",
                     200, token=token)["entries"]
    assert history[-1]["event"] == "changed"
    imported_series = expect(stage4, "GET", f"/series/{original_series['series_id']}",
                              200, token=token)
    assert [item["exception"] for item in imported_series["occurrences"]] == [True, False]
    assert imported_series["occurrences"][0]["reservation"]["starts_at_local"] == f"{date}T21:00"
    assert imported_series["occurrences"][1]["reservation"]["starts_at_local"] == f"{(dt.date.fromisoformat(date) + dt.timedelta(weeks=1)).isoformat()}T20:00"
    roundtrip = expect(stage4, "GET", "/_test/export", 200)["state"]
    expect_empty(stage4, "POST", "/_test/import", {
        "track": "tablekeeper", "format_version": 1, "state": roundtrip})


def check_series_dst_atomicity_and_race(base):
    from check_stage3 import next_weekly_dst_pair

    data = _fixture_with_pairs()
    expect_empty(base, "POST", "/_test/reset", data)
    ada = login(base)
    anchor_date, next_date = next_weekly_dst_pair()
    _, anchor = make_booking(base, ada, anchor_date, table="t_2", at="19:00",
                             party=2, key="dst-series-anchor")
    series = expect(base, "POST", "/series", 201,
                    {"anchor_reference": anchor["reference"], "count": 2,
                     "interval_weeks": 1}, ada, "dst-series-create")
    series_path = f"/series/{series['series_id']}"
    # The half-open old end permits this booking; the proposed later clock conflicts.
    make_booking(base, ada, next_date, table="t_2", at="20:30", party=2,
                 key="dst-blocking-booking")
    blocked_state = expect(base, "GET", "/_test/export", 200)["state"]
    blocked = expect(base, "POST", f"{series_path}/amend", 409,
                     {"expected_revision": 1, "from_index": 0,
                      "local_time": "20:00"}, ada, "dst-atomic-failure")
    assert blocked["error"]["code"] == "table_unavailable"
    assert expect(base, "GET", "/_test/export", 200)["state"] == blocked_state


def check_series_dst_recurrence_and_race(base):
    from check_stage3 import next_weekly_dst_pair

    data = _fixture_with_pairs()
    expect_empty(base, "POST", "/_test/reset", data)
    ada = login(base)
    anchor_date, next_date = next_weekly_dst_pair()
    _, anchor = make_booking(base, ada, anchor_date, table="t_2", at="19:00",
                             party=2, key="dst-series-anchor")
    series = expect(base, "POST", "/series", 201,
                    {"anchor_reference": anchor["reference"], "count": 2,
                     "interval_weeks": 1}, ada, "dst-series-create")
    series_path = f"/series/{series['series_id']}"
    body_a = {"expected_revision": 1, "from_index": 0, "local_time": "20:00"}
    body_b = {"expected_revision": 1, "from_index": 0, "local_time": "21:00"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda args: call(base, "POST", f"{series_path}/amend",
                                                   args[0], ada, args[1]),
                                 [(body_a, "dst-race-a"), (body_b, "dst-race-b")]))
    assert sorted(row[0] for row in outcomes) == [201, 409], outcomes
    rejected = next(row[1] for row in outcomes if row[0] == 409)
    assert rejected["error"]["code"] == "stale_revision"
    current = expect(base, "GET", series_path, 200, token=ada)
    assert current["revision"] == 2
    starts = [item["reservation"]["starts_at_local"] for item in current["occurrences"]]
    assert starts == [f"{anchor_date}T20:00", f"{next_date}T20:00"] or \
           starts == [f"{anchor_date}T21:00", f"{next_date}T21:00"]
    instants = [dt.datetime.fromisoformat(item["reservation"]["starts_at"])
                for item in current["occurrences"]]
    assert (instants[0].utcoffset(), instants[1].utcoffset()) in (
        (dt.timedelta(hours=2), dt.timedelta(hours=1)),
        (dt.timedelta(hours=1), dt.timedelta(hours=2)))
    assert abs((instants[1] - instants[0]).total_seconds() / 3600 - 168) == 1


def check_series_amend(base):
    data = _fixture_with_pairs()
    expect_empty(base, "POST", "/_test/reset", data)
    ada = login(base)
    bob = login(base, "bob@example.com")
    date = date_after(35)
    policy_day = (dt.date.fromisoformat(date) + dt.timedelta(weeks=1)).isoformat()
    policy_response = expect(base, "POST", "/restaurants/r_anker/policies", 201,
                             policy(policy_day, duration=60), ada, "series-policy")
    _, anchor = make_booking(base, ada, date, table="t_1", party=2,
                             key="series-anchor")
    series = expect(base, "POST", "/series", 201,
                    {"anchor_reference": anchor["reference"], "count": 4,
                     "interval_weeks": 1}, ada, "series-create")
    series_path = f"/series/{series['series_id']}"
    denied_body = {"expected_revision": 1, "from_index": 0, "local_time": "20:00"}
    assert call(base, "POST", f"{series_path}/amend", denied_body,
                key="series-anonymous")[0] == 401
    wrong_owner = expect(base, "POST", f"{series_path}/amend", 404,
                         denied_body, bob, "series-wrong-owner")
    assert wrong_owner["error"]["code"] == "not_found"
    for key, value in (("expected_revision", True), ("from_index", True),
                       ("local_time", "24:00")):
        invalid_body = {**denied_body, key: value}
        invalid_response = expect(base, "POST", f"{series_path}/amend", 422,
                                  invalid_body, ada, f"series-invalid-{key}")
        assert invalid_response["error"]["code"] == "validation_failed"
    refs = [row["reference"] for row in series["occurrences"]]
    changed_exception = expect(base, "PATCH", f"/reservations/{refs[1]}", 200,
                               {"table_ids": ["t_2", "t_3"]}, ada)
    assert changed_exception["revision"] == 2
    cancelled = expect(base, "POST", f"/reservations/{refs[2]}/cancel", 200, token=ada)
    assert cancelled["status"] == "cancelled"
    before_series = expect(base, "GET", series_path, 200, token=ada)
    before_stale = expect(base, "GET", "/_test/export", 200)["state"]
    stale = expect(base, "POST", f"{series_path}/amend", 409,
                   {"expected_revision": 1, "from_index": 0,
                    "local_time": "20:00"}, ada, "series-stale")
    assert stale["error"]["code"] == "stale_revision"
    assert expect(base, "GET", "/_test/export", 200)["state"] == before_stale
    before_state = expect(base, "GET", "/_test/export", 200)["state"]
    amend_body = {"expected_revision": before_series["revision"],
                  "from_index": 0, "local_time": "20:00", "ignored": "unknown"}
    amended = expect(base, "POST", f"{series_path}/amend", 201, amend_body,
                     ada, "series-amend")
    rows = amended["occurrences"]
    assert amended["revision"] == before_series["revision"] + 1
    assert [row["exception"] for row in rows] == [False, True, False, False]
    assert [row["reservation"]["status"] for row in rows] == [
        "confirmed", "confirmed", "cancelled", "confirmed"]
    assert rows[0]["reservation"]["starts_at_local"] == f"{date}T20:00"
    assert rows[1]["reservation"]["starts_at_local"] == (
        before_series["occurrences"][1]["reservation"]["starts_at_local"])
    assert rows[2]["reservation"]["starts_at_local"] == (
        before_series["occurrences"][2]["reservation"]["starts_at_local"])
    assert rows[3]["reservation"]["starts_at_local"] == f"{(dt.date.fromisoformat(date) + dt.timedelta(weeks=3)).isoformat()}T20:00"
    assert rows[0]["reservation"]["accepted_terms"]["policy_version"] == 0
    assert rows[3]["reservation"]["accepted_terms"]["policy_version"] == policy_response["policy_version"]
    assert rows[1]["reservation"]["table_ids"] == changed_exception["table_ids"]
    assert rows[0]["reservation"]["revision"] == 2
    assert rows[3]["reservation"]["revision"] == 2
    after_state = expect(base, "GET", "/_test/export", 200)["state"]
    assert after_state["restaurants"][0]["restaurant_revision"] == (
        before_state["restaurants"][0]["restaurant_revision"] + 1)

    no_op_body = {"expected_revision": amended["revision"], "from_index": 0,
                  "local_time": "20:00"}
    state_before_noop = expect(base, "GET", "/_test/export", 200)["state"]
    no_op = expect(base, "POST", f"{series_path}/amend", 201, no_op_body,
                   ada, "series-amend-noop")
    assert no_op == amended
    state_after_noop = expect(base, "GET", "/_test/export", 200)["state"]
    assert state_after_noop["restaurants"] == state_before_noop["restaurants"]
    assert state_after_noop["reservations"] == state_before_noop["reservations"]

    expect(base, "POST", f"/reservations/{refs[0]}/cancel", 200, token=ada)
    assert expect(base, "POST", f"{series_path}/amend", 200, no_op_body,
                  ada, "series-amend-noop") == no_op
    assert expect(base, "POST", f"{series_path}/amend", 200, amend_body,
                  ada, "series-amend") == amended
    amended_state = expect(base, "GET", "/_test/export", 200)["state"]
    expect_empty(base, "POST", "/_test/import", {
        "track": "tablekeeper", "format_version": 1, "state": amended_state})
    assert expect(base, "GET", "/_test/export", 200)["state"] == amended_state


def main():
    with tempfile.TemporaryDirectory(prefix="tablekeeper-stage4-") as temporary:
        temp = Path(temporary)
        static = temp / "static"
        (static / "assets").mkdir(parents=True)
        (static / "index.html").write_text("<!doctype html><title>check</title>",
                                            encoding="utf-8")
        roots = {"stage1": PARENT / "stage-1", "stage2": PARENT / "stage-2",
                 "stage3": PARENT / "stage-3", "stage4": ROOT}
        ports = {name: free_port() for name in roots}
        bases = {name: f"http://127.0.0.1:{port}" for name, port in ports.items()}
        processes = {name: start_server(root, temp / f"{name}.sqlite3", ports[name], static)
                     for name, root in roots.items()}
        try:
            for name, process in processes.items():
                wait_ready(bases[name], process)
            run_stage3(bases["stage4"])
            check_replan_apply_and_closure(bases["stage4"])
            check_replan_oracle_and_races(bases["stage4"])
            check_replan_uses_accepted_capacity(bases["stage4"])
            check_replan_limits_and_failures(bases["stage4"])
            check_cross_restaurant_plan_revision(bases["stage4"])
            check_closure_half_open(bases["stage4"])
            check_series_amend_respects_closures(bases["stage4"])
            check_series_creation_respects_closures(bases["stage4"])
            check_series_amend(bases["stage4"])
            check_series_dst_atomicity_and_race(bases["stage4"])
            check_series_dst_recurrence_and_race(bases["stage4"])
            check_stale_replan_and_stage3_upgrade(bases["stage3"], bases["stage4"])
            run_populated_upgrade(bases["stage1"], bases["stage2"], bases["stage4"])
        finally:
            for process in processes.values():
                process.terminate()
            for process in processes.values():
                try:
                    process.wait(timeout=5)
                except TimeoutError:
                    process.kill()
                    process.wait(timeout=5)
    print("Stage 4 checks passed: inherited API/import contracts, optimal seating repairs, closures, and series amendments.")


if __name__ == "__main__":
    main()
