#!/usr/bin/env python3
"""Independent HTTP checks for Tablekeeper concurrency, transactions, and time."""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import threading
import time
from collections import Counter
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
PASSWORD = "correct horse"
REQUEST_TIMINGS: list[float] = []
CONTROL_TIMINGS: list[float] = []
TIMING_LOCK = threading.Lock()


@dataclass(frozen=True)
class Reply:
    status: int
    body: dict


def call(base: str, path: str, method: str = "GET", body=None, *,
         token: str | None = None, key: str | None = None, timeout: float = 5,
         raw_body: str | bytes | None = None) -> Reply:
    headers = {"Accept": "application/json"}
    data = None
    if raw_body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
        data = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
    elif body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if key is not None:
        headers["Idempotency-Key"] = key
    request = Request(base.rstrip("/") + path, data=data,
                      headers=headers, method=method)
    started = time.perf_counter()
    try:
        try:
            response = urlopen(request, timeout=timeout)
        except HTTPError as error:
            response = error
        raw = response.read()
    finally:
        elapsed = time.perf_counter() - started
        timings = CONTROL_TIMINGS if path.startswith("/_test/") else REQUEST_TIMINGS
        with TIMING_LOCK:
            timings.append(elapsed)
    parsed = json.loads(raw) if raw else {}
    return Reply(response.code, parsed)


def expect(reply: Reply, status: int, code: str | None = None) -> Reply:
    got_code = reply.body.get("error", {}).get("code")
    if reply.status >= 400:
        assert set(reply.body) == {"error"}, reply.body
        detail = reply.body["error"]
        assert (isinstance(detail, dict) and set(detail) == {"code", "message"} and
                isinstance(detail["code"], str) and isinstance(detail["message"], str)), reply.body
    assert reply.status == status and (code is None or got_code == code), (
        f"expected HTTP {status}{' '+code if code else ''}; "
        f"got HTTP {reply.status}{' '+str(got_code) if got_code else ''}")
    return reply


def user(index: int, email: str | None = None) -> dict:
    return {"id": f"u_qa_{index}", "email": email or f"qa{index}@example.com",
            "password": PASSWORD, "display_name": f"QA {index}"}


def restaurant(rid: str = "r_qa", *, timezone: str = "Europe/Berlin",
               opens: str = "18:00", closes: str = "23:00",
               tables: list[dict] | None = None,
               cancellation_cutoff_minutes: int = 120) -> dict:
    return {
        "id": rid, "name": "QA Restaurant", "timezone": timezone,
        "slot_minutes": 30, "reservation_duration_minutes": 90,
        "cancellation_cutoff_minutes": cancellation_cutoff_minutes,
        "opening_hours": [{"weekday": day, "opens": opens, "closes": closes}
                           for day in WEEKDAYS],
        "tables": tables or [
            {"id": "t_1", "label": "1", "capacity": 2},
            {"id": "t_2", "label": "2", "capacity": 4},
            {"id": "t_3", "label": "3", "capacity": 6},
        ],
    }


def fixture(*, users: list[dict] | None = None,
            restaurants: list[dict] | None = None) -> dict:
    return {"users": users if users is not None else [user(0), user(1)],
            "restaurants": restaurants if restaurants is not None else [restaurant()],
            "reservations": []}


def reset(base: str, data: dict) -> None:
    expect(call(base, "/_test/reset", "POST", data, timeout=10), 204)


def login(base: str, account: dict) -> str:
    reply = expect(call(base, "/auth/login", "POST", {
        "email": account["email"], "password": account["password"]}), 200)
    token = reply.body.get("token")
    assert isinstance(token, str) and token
    return token


def local_date(days: int = 14) -> str:
    return (dt.date.today() + dt.timedelta(days=days)).isoformat()


def booking_body(date: str, table: str = "t_2", at: str = "19:00",
                 party: int = 4, restaurant_id: str = "r_qa") -> dict:
    return {"restaurant_id": restaurant_id, "table_id": table,
            "starts_at_local": f"{date}T{at}", "party_size": party}


def check_fifty_overlapping_writes(base: str) -> None:
    accounts = [user(i) for i in range(50)]
    only_table = [{"id": "t_shared", "label": "Shared", "capacity": 8}]
    reset(base, fixture(users=accounts,
                        restaurants=[restaurant(tables=only_table)]))
    tokens = [login(base, account) for account in accounts]
    body = booking_body(local_date(), table="t_shared")

    def submit(index: int) -> Reply:
        return call(base, "/reservations", "POST", body, token=tokens[index],
                    key=f"overlap-{index:02d}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as pool:
        replies = list(pool.map(submit, range(50)))
    counts = Counter(reply.status for reply in replies)
    assert counts == Counter({201: 1, 409: 49}), (
        f"50 overlapping writes must produce one winner and 49 conflicts; got {counts}")
    assert all(reply.body.get("error", {}).get("code") == "table_unavailable"
               for reply in replies if reply.status == 409)


def check_identical_key_race(base: str) -> None:
    account = user(0)
    reset(base, fixture(users=[account]))
    token = login(base, account)
    body = booking_body(local_date())

    def submit(_: int) -> Reply:
        return call(base, "/reservations", "POST", body, token=token,
                    key="same-user-same-request")

    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as pool:
        replies = list(pool.map(submit, range(50)))
    counts = Counter(reply.status for reply in replies)
    assert counts == Counter({201: 1, 200: 49}), (
        f"identical concurrent retries must elect one 201; got {counts}")
    assert all(reply.body == replies[0].body for reply in replies)
    listed = expect(call(base, "/reservations", token=token), 200).body["reservations"]
    assert len(listed) == 1 and listed[0]["reference"] == replies[0].body["reference"]


def check_identical_move_key_race(base: str) -> None:
    account = user(0)
    reset(base, fixture(users=[account]))
    token = login(base, account)
    booking = expect(call(base, "/reservations", "POST",
                          booking_body(local_date(), table="t_1", party=2),
                          token=token, key="move-race-seed"), 201).body
    body = {"moves": [{"reference": booking["reference"], "table_id": "t_2"}]}

    def submit(_: int) -> Reply:
        return call(base, "/reservation-moves", "POST", body, token=token,
                    key="same-move-request")

    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as pool:
        replies = list(pool.map(submit, range(50)))
    counts = Counter(reply.status for reply in replies)
    assert counts == Counter({201: 1, 200: 49}), (
        f"identical concurrent move retries must elect one 201; got {counts}")
    assert all(reply.body == replies[0].body for reply in replies)
    listed = expect(call(base, "/reservations", token=token), 200).body["reservations"]
    assert len(listed) == 1 and listed[0]["table_id"] == "t_2"


def check_validation_precedence(base: str) -> None:
    account = user(0)
    other = user(1)
    reset(base, fixture(users=[account, other]))
    token = login(base, account)
    date = local_date()
    valid = booking_body(date, table="t_1", party=2)

    expect(call(base, "/reservations", "POST", valid, token=token,
                key="priority-key"), 201)
    changed_but_invalid = {**valid, "party_size": "not-an-integer"}
    expect(call(base, "/reservations", "POST", changed_but_invalid,
                token=token, key="priority-key"), 409, "idempotency_key_reuse")

    failed_key = "retry-after-validation-failure"
    invalid = booking_body(date, table="missing-table", party=2)
    expect(call(base, "/reservations", "POST", invalid, token=token,
                key=failed_key), 404, "not_found")
    corrected = booking_body(date, table="t_2", party=4)
    expect(call(base, "/reservations", "POST", corrected, token=token,
                key=failed_key), 201)

    expect(call(base, "/reservations", "POST", valid, token=token),
           400, "missing_idempotency_key")
    expect(call(base, "/reservations", "POST", valid, token=token, key=""),
           400, "missing_idempotency_key")
    expect(call(base, "/reservations", "POST", valid, token=token,
                key="k" * 256), 422, "validation_failed")
    expect(call(base, "/reservations", "POST", {
        **valid, "restaurant_id": 17}, token=token, key="wrong-json-type"),
        400, "malformed_request")
    expect(call(base, "/reservations", "POST", {
        **valid, "starts_at_local": 123}, token=token, key="wrong-time-type"),
        400, "malformed_request")
    expect(call(base, "/reservations", "POST", {
        **valid, "party_size": True}, token=token, key="boolean-party"),
        422, "validation_failed")

    key = "scope-by-user-and-method"
    expect(call(base, "/reservations", token=token, key=key), 200)
    other_token = login(base, other)
    other_body = booking_body(date, table="t_2", at="20:30")
    expect(call(base, "/reservations", "POST", other_body,
                token=other_token, key=key), 201)
    own_body = booking_body(date, table="t_3", at="20:30")
    expect(call(base, "/reservations", "POST", own_body,
                token=token, key=key), 201)

    cross_path = booking_body(date, table="t_3")
    created = expect(call(base, "/reservations", "POST", cross_path,
                          token=token, key="same-key-different-path"), 201).body
    no_op_move = {"moves": [{"reference": created["reference"], "table_id": "t_3"}]}
    expect(call(base, "/reservation-moves", "POST", no_op_move, token=token,
                key="same-key-different-path"), 201)

    for value in ("4.0", "+4", "1e9"):
        query = urlencode({"restaurant_id": "r_qa", "date": date,
                           "party_size": value})
        expect(call(base, "/availability?" + query), 422, "validation_failed")


def check_key_boundaries_and_json_equality(base: str) -> None:
    account = user(0)
    reset(base, fixture(users=[account]))
    token = login(base, account)
    date = local_date()

    body = booking_body(date, table="t_1", party=2)
    original = expect(call(base, "/reservations", "POST", body, token=token,
                           key="k"), 201).body
    reordered = {"party_size": 2, "starts_at_local": body["starts_at_local"],
                 "table_id": "t_1", "restaurant_id": "r_qa"}
    replay = expect(call(base, "/reservations", "POST", reordered,
                         token=token, key="k"), 200).body
    assert replay == original, "JSON object key order must not change the replay value"

    longest = booking_body(date, table="t_2", at="20:30")
    expect(call(base, "/reservations", "POST", longest, token=token,
                key="x" * 255), 201)
    past_date = (dt.date.today() - dt.timedelta(days=8)).isoformat()
    past = expect(call(base, "/reservations", "POST",
                       booking_body(past_date, "t_3", "19:00", 4),
                       token=token, key="past-date-accepted"), 201).body
    assert past["starts_at_local"] == f"{past_date}T19:00"

    long_account = {**user(1), "id": "u" * 64}
    long_table = "t" * 64
    long_restaurant = restaurant("r" * 64, tables=[
        {"id": long_table, "label": "64-character ID", "capacity": 4}])
    reset(base, fixture(users=[long_account], restaurants=[long_restaurant]))
    long_token = login(base, long_account)
    detail = expect(call(base, f"/restaurants/{long_restaurant['id']}"), 200).body
    assert detail["id"] == long_restaurant["id"]
    long_booking = expect(call(base, "/reservations", "POST",
                               booking_body(local_date(), long_table, party=2,
                                            restaurant_id=long_restaurant["id"]),
                               token=long_token, key="maximum-opaque-ids"), 201).body
    assert long_booking["table_id"] == long_table


def check_move_swap_and_rollback(base: str) -> None:
    ada, bob = user(0), user(1)
    reset(base, fixture(users=[ada, bob]))
    ada_token, bob_token = login(base, ada), login(base, bob)
    date = local_date()

    first = expect(call(base, "/reservations", "POST",
                        booking_body(date, "t_1", party=2), token=ada_token,
                        key="seed-booking-a"), 201).body
    second = expect(call(base, "/reservations", "POST",
                         booking_body(date, "t_2", party=2), token=ada_token,
                         key="seed-booking-b"), 201).body
    blocker = expect(call(base, "/reservations", "POST",
                          booking_body(date, "t_3", party=4), token=bob_token,
                          key="seed-booking-blocker"), 201).body

    shared_key = "failed-move-key-remains-free"
    impossible = {"moves": [
        {"reference": first["reference"], "table_id": "t_2"},
        {"reference": second["reference"], "table_id": "t_3"},
    ]}
    expect(call(base, "/reservation-moves", "POST", impossible,
                token=ada_token, key=shared_key), 409, "table_unavailable")
    after_failure = [expect(call(base, f"/reservations/{ref}", token=ada_token), 200).body
                     for ref in (first["reference"], second["reference"])]
    assert [item["table_id"] for item in after_failure] == ["t_1", "t_2"]
    assert blocker["table_id"] == "t_3"

    swap = {"moves": [
        {"reference": first["reference"], "table_id": "t_2"},
        {"reference": second["reference"], "table_id": "t_1"},
    ]}
    moved = expect(call(base, "/reservation-moves", "POST", swap,
                        token=ada_token, key=shared_key), 201).body
    assert [item["table_id"] for item in moved["reservations"]] == ["t_2", "t_1"]

    expect(call(base, f"/reservations/{first['reference']}/cancel", "POST",
                token=ada_token), 200)
    replay = expect(call(base, "/reservation-moves", "POST", swap,
                         token=ada_token, key=shared_key), 200).body
    assert replay == moved


def check_patch_cases(base: str) -> None:
    ada, bob = user(0), user(1)
    reset(base, fixture(users=[ada, bob],
                        restaurants=[restaurant(cancellation_cutoff_minutes=0)]))
    ada_token, bob_token = login(base, ada), login(base, bob)
    date = local_date()

    created = expect(call(base, "/reservations", "POST",
                          booking_body(date, "t_1", "19:00", 2),
                          token=ada_token, key="patch-base"), 201).body
    reference = created["reference"]
    expect(call(base, f"/reservations/{reference}", token=bob_token),
           404, "not_found")
    expect(call(base, f"/reservations/{reference}", "PATCH", {"party_size": 1},
                token=bob_token), 404, "not_found")
    assert expect(call(base, f"/reservations/{reference}", token=ada_token), 200).body == created

    no_op = expect(call(base, f"/reservations/{reference}", "PATCH", {},
                        token=ada_token), 200).body
    assert no_op == created, "an empty patch is a value-preserving no-op"

    table_change = expect(call(base, f"/reservations/{reference}", "PATCH",
                               {"table_id": "t_2"}, token=ada_token), 200).body
    assert table_change["table_id"] == "t_2"
    assert (table_change["reference"], table_change["reservation_id"]) == (
        created["reference"], created["reservation_id"])
    freed = expect(call(base, "/reservations", "POST",
                        booking_body(date, "t_1", "19:00", 2),
                        token=bob_token, key="patch-old-slot-freed"), 201).body
    blocker = expect(call(base, "/reservations", "POST",
                          booking_body(date, "t_3", "19:00", 2),
                          token=bob_token, key="patch-target-blocker"), 201).body

    expect(call(base, f"/reservations/{reference}", "PATCH",
                {"table_id": "t_3"}, token=ada_token), 409, "table_unavailable")
    assert expect(call(base, f"/reservations/{reference}", token=ada_token),
                  200).body == table_change, "failed patch must leave the old record intact"
    expect(call(base, "/reservations", "POST", booking_body(date, "t_2", "19:00", 2),
                token=bob_token, key="patch-old-occupancy-retained"),
           409, "table_unavailable")
    assert freed["table_id"] == "t_1" and blocker["table_id"] == "t_3"

    time_change = expect(call(base, f"/reservations/{reference}", "PATCH",
                              {"starts_at_local": f"{date}T20:30"},
                              token=ada_token), 200).body
    assert time_change["table_id"] == "t_2" and time_change["party_size"] == 2
    party_change = expect(call(base, f"/reservations/{reference}", "PATCH",
                               {"party_size": 3}, token=ada_token), 200).body
    assert party_change["starts_at_local"] == f"{date}T20:30"
    assert party_change["table_id"] == "t_2" and party_change["party_size"] == 3
    assert (party_change["reference"], party_change["reservation_id"]) == (
        created["reference"], created["reservation_id"])

    cancelled_date = local_date(1)
    cancelled = expect(call(base, "/reservations", "POST",
                            booking_body(cancelled_date, "t_1", "19:00", 2),
                            token=ada_token, key="patch-cancelled"), 201).body
    expect(call(base, f"/reservations/{cancelled['reference']}/cancel", "POST",
                token=ada_token), 200)
    expect(call(base, f"/reservations/{cancelled['reference']}", "PATCH",
                {"party_size": 1}, token=ada_token), 409, "reservation_cancelled")
    assert expect(call(base, f"/reservations/{cancelled['reference']}",
                       token=ada_token), 200).body["status"] == "cancelled"

    wide_cutoff = restaurant(opens="00:00", closes="23:30",
                             tables=[{"id": "t_1", "label": "1", "capacity": 4}],
                             )
    wide_cutoff["cancellation_cutoff_minutes"] = 2 * 24 * 60
    reset(base, fixture(users=[ada], restaurants=[wide_cutoff]))
    ada_token = login(base, ada)
    near = local_date(1)
    far = local_date(5)
    near_booking = expect(call(base, "/reservations", "POST",
                               booking_body(near, "t_1", "19:00", 2),
                               token=ada_token, key="patch-current-start-near"), 201).body
    expect(call(base, f"/reservations/{near_booking['reference']}", "PATCH",
                {"starts_at_local": f"{far}T19:00"}, token=ada_token),
           409, "cutoff_passed")
    far_booking = expect(call(base, "/reservations", "POST",
                              booking_body(far, "t_1", "20:30", 2),
                              token=ada_token, key="patch-current-start-far"), 201).body
    moved_earlier = expect(call(base, f"/reservations/{far_booking['reference']}",
                                "PATCH", {"starts_at_local": f"{near}T20:30"},
                                token=ada_token), 200).body
    assert moved_earlier["starts_at_local"] == f"{near}T20:30"


def check_move_boundaries_and_precedence(base: str) -> None:
    ada = user(0)
    reset(base, fixture(users=[ada],
                        restaurants=[restaurant(cancellation_cutoff_minutes=0)]))
    token = login(base, ada)
    date = local_date(14)
    one = expect(call(base, "/reservations", "POST",
                      booking_body(date, "t_1", "19:00", 2), token=token,
                      key="move-one-seed"), 201).body
    one_move = {"moves": [{"reference": one["reference"], "table_id": "t_2"}]}
    expect(call(base, "/reservation-moves", "POST", one_move,
                key="unauthenticated-move"), 401, "unauthenticated")
    moved_one = expect(call(base, "/reservation-moves", "POST", one_move,
                            token=token, key="move-one-boundary"), 201).body
    assert [row["table_id"] for row in moved_one["reservations"]] == ["t_2"]
    expect(call(base, "/reservation-moves", "POST",
                {"moves": [{"reference": one["reference"], "party_size": 99}]},
                token=token, key="move-one-boundary"),
           409, "idempotency_key_reuse")
    for index, invalid_batch in enumerate(({"moves": []}, {"moves": [{}]},
                                           {"moves": "not-a-list"})):
        expect(call(base, "/reservation-moves", "POST", invalid_batch,
                    token=token, key=f"move-shape-{index}"),
               422, "validation_failed")
    expect(call(base, "/reservation-moves", "POST", one_move, token=token),
           400, "missing_idempotency_key")
    expect(call(base, "/reservation-moves", "POST", one_move,
                token=token, key=""), 400, "missing_idempotency_key")
    expect(call(base, "/reservation-moves", "POST", one_move,
                token=token, key="m" * 256), 422, "validation_failed")
    short_key = expect(call(base, "/reservation-moves", "POST", one_move,
                            token=token, key="m"), 201).body
    assert expect(call(base, "/reservation-moves", "POST",
                       {"moves": [{"table_id": "t_2", "reference": one["reference"]}]},
                       token=token, key="m"), 200).body == short_key
    max_key_body = {"moves": [{"reference": one["reference"]}]}
    max_key_response = expect(call(base, "/reservation-moves", "POST", max_key_body,
                                   token=token, key="M" * 255), 201).body
    assert expect(call(base, "/reservation-moves", "POST",
                       {"moves": [{"reference": one["reference"]}]},
                       token=token, key="M" * 255), 200).body == max_key_response
    changed_time = expect(call(base, "/reservation-moves", "POST",
                               {"moves": [{"reference": one["reference"],
                                           "starts_at_local": f"{date}T20:30"}]},
                               token=token, key="move-time-subset"), 201).body["reservations"][0]
    assert (changed_time["starts_at_local"], changed_time["table_id"],
            changed_time["party_size"]) == (f"{date}T20:30", "t_2", 2)
    changed_party = expect(call(base, "/reservation-moves", "POST",
                                {"moves": [{"reference": one["reference"],
                                            "party_size": 3,
                                            "ignored": "unknown field"}]},
                                token=token, key="move-party-subset"), 201).body["reservations"][0]
    assert (changed_party["starts_at_local"], changed_party["table_id"],
            changed_party["party_size"]) == (f"{date}T20:30", "t_2", 3)
    assert (changed_party["reference"], changed_party["reservation_id"],
            changed_party["created_at"]) == (one["reference"], one["reservation_id"],
                                               one["created_at"])
    expect(call(base, "/reservation-moves", "POST",
                {"moves": [{"reference": "UNKNOWN9", "table_id": "t_2"}]},
                token=token, key="move-unknown-reference"), 404, "not_found")
    expect(call(base, f"/reservations/{one['reference']}/cancel", "POST",
                token=token), 200)
    expect(call(base, "/reservation-moves", "POST", one_move,
                token=token, key="move-cancelled-reference"),
           409, "reservation_cancelled")
    assert expect(call(base, "/reservation-moves", "POST", one_move,
                       token=token, key="move-one-boundary"), 200).body == moved_one

    rows = []
    for index in range(8):
        day = local_date(16 + index)
        rows.append(expect(call(base, "/reservations", "POST",
                                booking_body(day, "t_1", "19:00", 2),
                                token=token, key=f"move-eight-seed-{index}"), 201).body)
    reverse_refs = [row["reference"] for row in reversed(rows)]
    batch = {"moves": [{"reference": ref, "table_id": "t_2"}
                       for ref in reverse_refs]}
    moved_eight = expect(call(base, "/reservation-moves", "POST", batch,
                              token=token, key="move-eight-boundary"), 201).body["reservations"]
    assert [row["reference"] for row in moved_eight] == reverse_refs
    assert all(row["table_id"] == "t_2" for row in moved_eight)
    assert all(row["reservation_id"] == next(
        original["reservation_id"] for original in rows
        if original["reference"] == row["reference"]) for row in moved_eight)

    no_op = {"moves": [{"reference": ref} for ref in reverse_refs]}
    no_op_result = expect(call(base, "/reservation-moves", "POST", no_op,
                               token=token, key="move-eight-no-op"), 201).body["reservations"]
    assert no_op_result == moved_eight
    before_invalid = [expect(call(base, f"/reservations/{ref}", token=token), 200).body
                      for ref in reverse_refs]
    expect(call(base, "/reservation-moves", "POST",
                {"moves": [{"reference": ref, "table_id": "t_3"}
                           for ref in reverse_refs] + [{"reference": "MISSING9"}]},
                token=token, key="move-nine-invalid"), 422, "validation_failed")
    expect(call(base, "/reservation-moves", "POST",
                {"moves": [{"reference": reverse_refs[0]},
                           {"reference": reverse_refs[0]}]},
                token=token, key="move-duplicate-invalid"), 422, "validation_failed")
    after_invalid = [expect(call(base, f"/reservations/{ref}", token=token), 200).body
                     for ref in reverse_refs]
    assert after_invalid == before_invalid

    ada, bob = user(0), user(1)
    first_restaurant = restaurant("r_qa", cancellation_cutoff_minutes=0)
    second_restaurant = restaurant("r_second", cancellation_cutoff_minutes=0)
    reset(base, fixture(users=[ada, bob], restaurants=[first_restaurant, second_restaurant]))
    ada_token, bob_token = login(base, ada), login(base, bob)
    owned = expect(call(base, "/reservations", "POST",
                        booking_body(date, "t_1", "19:00", 2), token=ada_token,
                        key="move-owner-ada"), 201).body
    other_owner = expect(call(base, "/reservations", "POST",
                              booking_body(date, "t_2", "19:00", 2), token=bob_token,
                              key="move-owner-bob"), 201).body
    mixed_owner = {"moves": [{"reference": owned["reference"], "table_id": "t_3"},
                             {"reference": other_owner["reference"], "table_id": "t_1"}]}
    expect(call(base, "/reservation-moves", "POST", mixed_owner,
                token=ada_token, key="move-mixed-owner"), 404, "not_found")
    assert expect(call(base, f"/reservations/{owned['reference']}",
                       token=ada_token), 200).body == owned
    assert expect(call(base, f"/reservations/{other_owner['reference']}",
                       token=bob_token), 200).body == other_owner
    ada_no_op = {"moves": [{"reference": owned["reference"]}]}
    bob_no_op = {"moves": [{"reference": other_owner["reference"]}]}
    expect(call(base, "/reservation-moves", "POST", ada_no_op,
                token=ada_token, key="move-key-scope-by-user"), 201)
    expect(call(base, "/reservation-moves", "POST", bob_no_op,
                token=bob_token, key="move-key-scope-by-user"), 201)

    second_location = expect(call(base, "/reservations", "POST",
                                  booking_body(date, "t_1", "20:30", 2,
                                               restaurant_id="r_second"),
                                  token=ada_token, key="move-second-restaurant"), 201).body
    mixed_restaurant = {"moves": [
        {"reference": owned["reference"], "table_id": "t_3"},
        {"reference": second_location["reference"], "table_id": "t_2"},
    ]}
    expect(call(base, "/reservation-moves", "POST", mixed_restaurant,
                token=ada_token, key="move-mixed-restaurant"),
           422, "validation_failed")
    assert expect(call(base, f"/reservations/{owned['reference']}",
                       token=ada_token), 200).body == owned
    assert expect(call(base, f"/reservations/{second_location['reference']}",
                       token=ada_token), 200).body == second_location

    reset(base, fixture(users=[ada, bob],
                        restaurants=[restaurant(cancellation_cutoff_minutes=0)]))
    ada_token, bob_token = login(base, ada), login(base, bob)
    first = expect(call(base, "/reservations", "POST",
                        booking_body(date, "t_1", "19:00", 2), token=ada_token,
                        key="move-precedence-first"), 201).body
    second = expect(call(base, "/reservations", "POST",
                         booking_body(date, "t_2", "19:00", 2), token=ada_token,
                         key="move-precedence-second"), 201).body
    blocker = expect(call(base, "/reservations", "POST",
                          booking_body(date, "t_3", "19:00", 2), token=bob_token,
                          key="move-precedence-blocker"), 201).body
    occupancy_then_404 = {"moves": [
        {"reference": first["reference"], "table_id": "t_3"},
        {"reference": second["reference"], "table_id": "missing-table"},
    ]}
    expect(call(base, "/reservation-moves", "POST", occupancy_then_404,
                token=ada_token, key="move-non-occupancy-before-conflict"),
           404, "not_found")
    first_error_order = {"moves": [
        {"reference": first["reference"], "table_id": "missing-table"},
        {"reference": second["reference"], "party_size": 99},
    ]}
    expect(call(base, "/reservation-moves", "POST", first_error_order,
                token=ada_token, key="move-input-error-order-one"),
           404, "not_found")
    reverse_error_order = {"moves": [
        {"reference": second["reference"], "party_size": 99},
        {"reference": first["reference"], "table_id": "missing-table"},
    ]}
    expect(call(base, "/reservation-moves", "POST", reverse_error_order,
                token=ada_token, key="move-input-error-order-two"),
           422, "party_exceeds_capacity")
    for row, owner_token in ((first, ada_token), (second, ada_token),
                             (blocker, bob_token)):
        assert expect(call(base, f"/reservations/{row['reference']}",
                           token=owner_token), 200).body == row

    wide_cutoff = restaurant(cancellation_cutoff_minutes=60 * 24 * 3650)
    reset(base, fixture(users=[ada], restaurants=[wide_cutoff]))
    ada_token = login(base, ada)
    near_booking = expect(call(base, "/reservations", "POST",
                               booking_body(local_date(14), "t_1", "19:00", 2),
                               token=ada_token, key="move-cutoff-precedence"), 201).body
    expect(call(base, "/reservation-moves", "POST",
                {"moves": [{"reference": near_booking["reference"],
                            "table_id": "missing-table"}]},
                token=ada_token, key="move-cutoff-before-validation"),
           409, "cutoff_passed")


def check_dst_and_zones(base: str) -> None:
    berlin = restaurant("r_berlin", timezone="Europe/Berlin",
                        opens="00:00", closes="23:30")
    new_york = restaurant("r_new_york", timezone="America/New_York",
                          opens="00:00", closes="23:30")
    account = user(0)
    reset(base, fixture(users=[account], restaurants=[berlin, new_york]))
    token = login(base, account)

    def availability(rid: str, date: str) -> list[dict]:
        query = urlencode({"restaurant_id": rid, "date": date, "party_size": 4})
        return expect(call(base, "/availability?" + query), 200).body["slots"]

    def reserve(rid: str, date: str, at: str, table: str, key: str) -> dict:
        body = booking_body(date, table=table, at=at, restaurant_id=rid)
        return expect(call(base, "/reservations", "POST", body, token=token,
                           key=key), 201).body

    for rid, spring in (("r_berlin", "2026-03-29"),
                        ("r_new_york", "2026-03-08")):
        times = [slot["starts_at_local"].split("T")[1]
                 for slot in availability(rid, spring)]
        assert "02:00" not in times and "02:30" not in times
        expect(call(base, "/reservations", "POST",
                    booking_body(spring, restaurant_id=rid, at="02:30"),
                    token=token, key=f"skip-{rid}"), 422, "invalid_local_time")

    berlin_fall = "2026-10-25"
    times = [slot["starts_at_local"].split("T")[1]
             for slot in availability("r_berlin", berlin_fall)]
    assert times.count("02:00") == 1 and times.count("02:30") == 1
    fold = reserve("r_berlin", berlin_fall, "02:30", "t_2", "berlin-fold")
    assert fold["starts_at"].endswith("+02:00")
    across_fallback = reserve("r_berlin", berlin_fall, "01:30", "t_3",
                              "berlin-absolute-duration")
    start = dt.datetime.fromisoformat(across_fallback["starts_at"])
    end = dt.datetime.fromisoformat(across_fallback["ends_at"])
    assert end.astimezone(dt.timezone.utc) - start.astimezone(dt.timezone.utc) \
        == dt.timedelta(minutes=90)
    assert end.strftime("%H:%M") == "02:00"

    ny_fall = "2026-11-01"
    ny_times = [slot["starts_at_local"].split("T")[1]
                for slot in availability("r_new_york", ny_fall)]
    assert ny_times.count("01:30") == 1
    ny_fold = reserve("r_new_york", ny_fall, "01:30", "t_2", "ny-fold")
    assert ny_fold["starts_at"].endswith("-04:00")

    berlin_instant = reserve("r_berlin", "2026-12-01", "18:00", "t_2",
                             "berlin-zone-instant")
    ny_instant = reserve("r_new_york", "2026-12-01", "12:00", "t_2",
                         "ny-zone-instant")
    assert dt.datetime.fromisoformat(berlin_instant["starts_at"]) \
        == dt.datetime.fromisoformat(ny_instant["starts_at"])


def check_import_preserves_receipts(source: str, target: str) -> None:
    account = user(0)
    reset(source, fixture(users=[account]))
    token = login(source, account)
    date = local_date()
    booking = booking_body(date, table="t_2", party=4)
    original = expect(call(source, "/reservations", "POST", booking,
                           token=token, key="receipt-before-export"), 201).body
    move = {"moves": [{"reference": original["reference"], "table_id": "t_2"}]}
    moved = expect(call(source, "/reservation-moves", "POST", move,
                        token=token, key="move-receipt-before-export"), 201).body
    expect(call(source, f"/reservations/{original['reference']}/cancel", "POST",
                token=token), 200)
    assert expect(call(source, "/reservations", "POST", booking, token=token,
                       key="receipt-before-export"), 200).body == original
    failed_body = booking_body(date, table="missing-table", at="20:30")
    expect(call(source, "/reservations", "POST", failed_body, token=token,
                key="failed-key-before-export"), 404, "not_found")
    exported = expect(call(source, "/_test/export"), 200).body
    assert exported.get("track") == "tablekeeper" and exported.get("format_version") == 1
    later_body = booking_body(local_date(2), table="t_3", at="20:30")
    expect(call(source, "/reservations", "POST", later_body, token=token,
                key="source-write-after-snapshot"), 201)

    destination_fixture = fixture(users=[user(7)], restaurants=[restaurant("r_discarded")])
    reset(target, destination_fixture)
    expect(call(target, "/_test/import", "POST", exported, timeout=10), 204)
    assert expect(call(target, "/_test/export"), 200).body["state"] == exported["state"]

    current = expect(call(target, f"/reservations/{original['reference']}",
                          token=token), 200).body
    assert current["status"] == "cancelled"
    assert current["reservation_id"] == original["reservation_id"]
    assert current["created_at"] == original["created_at"]
    imported_login_token = login(target, account)
    assert len(expect(call(target, "/reservations", token=imported_login_token),
                      200).body["reservations"]) == 1
    assert expect(call(target, "/reservations", "POST", booking, token=token,
                       key="receipt-before-export"), 200).body == original
    assert expect(call(target, "/reservation-moves", "POST", move, token=token,
                       key="move-receipt-before-export"), 200).body == moved
    retry_body = booking_body(date, table="t_3", at="20:30")
    retried = expect(call(target, "/reservations", "POST", retry_body,
                          token=token, key="failed-key-before-export"), 201).body
    assert retried["table_id"] == "t_3"
    restaurants = expect(call(target, "/restaurants"), 200).body["restaurants"]
    assert [entry["id"] for entry in restaurants] == ["r_qa"]

    expect(call(target, "/_test/import", "POST", exported, timeout=10), 204)
    assert expect(call(target, "/_test/export"), 200).body["state"] == exported["state"]
    expect(call(target, f"/reservations/{retried['reference']}", token=token),
           404, "not_found")

    before_bad_import = expect(call(target, "/_test/export"), 200).body

    def reject_without_replacement(reply: Reply, status: int, code: str) -> None:
        expect(reply, status, code)
        assert expect(call(target, "/_test/export"), 200).body == before_bad_import

    reject_without_replacement(
        call(target, "/_test/import", "POST", raw_body="{"),
        400, "malformed_request")
    reject_without_replacement(
        call(target, "/_test/import", "POST", raw_body="[]"),
        400, "malformed_request")
    missing_track = {key: value for key, value in exported.items() if key != "track"}
    reject_without_replacement(
        call(target, "/_test/import", "POST", missing_track, timeout=10),
        422, "validation_failed")
    missing_version = {key: value for key, value in exported.items()
                       if key != "format_version"}
    reject_without_replacement(
        call(target, "/_test/import", "POST", missing_version, timeout=10),
        422, "validation_failed")
    wrong_version_type = {**exported, "format_version": True}
    reject_without_replacement(
        call(target, "/_test/import", "POST", wrong_version_type, timeout=10),
        422, "validation_failed")
    wrong_track = {**exported, "track": "wrong-track"}
    reject_without_replacement(
        call(target, "/_test/import", "POST", wrong_track, timeout=10),
        422, "validation_failed")
    missing_state = {key: value for key, value in exported.items() if key != "state"}
    reject_without_replacement(
        call(target, "/_test/import", "POST", missing_state, timeout=10),
        422, "validation_failed")
    invalid_state = json.loads(json.dumps(exported))
    invalid_state["state"]["version"] = True
    reject_without_replacement(
        call(target, "/_test/import", "POST", invalid_state, timeout=10),
        422, "validation_failed")

    reset(target, fixture(users=[user(9)], restaurants=[restaurant("r_cleared")]))
    expect(call(target, "/reservations", token=token), 401, "unauthenticated")
    assert [entry["id"] for entry in
            expect(call(target, "/restaurants"), 200).body["restaurants"]] == ["r_cleared"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True,
                        help="service under test (usually a locally run stage image)")
    parser.add_argument("--source-url",
                        help="earlier-stage source for export/import; defaults to --base-url")
    args = parser.parse_args()

    checks = [
        ("50 overlapping writes", lambda: check_fifty_overlapping_writes(args.base_url)),
        ("50 identical-key retries", lambda: check_identical_key_race(args.base_url)),
        ("50 identical move-key retries",
         lambda: check_identical_move_key_race(args.base_url)),
        ("strict types and idempotency precedence",
         lambda: check_validation_precedence(args.base_url)),
        ("key length boundaries and parsed JSON equality",
         lambda: check_key_boundaries_and_json_equality(args.base_url)),
        ("single-reservation PATCH semantics and cutoff", lambda: check_patch_cases(args.base_url)),
        ("atomic swap, rollback, failed-key reuse and receipt replay",
         lambda: check_move_swap_and_rollback(args.base_url)),
        ("move boundaries, input order, ownership and precedence",
         lambda: check_move_boundaries_and_precedence(args.base_url)),
        ("Berlin/New York DST and absolute durations",
         lambda: check_dst_and_zones(args.base_url)),
        ("populated import, retained token and original receipts",
         lambda: check_import_preserves_receipts(args.source_url or args.base_url,
                                                  args.base_url)),
    ]
    for name, run in checks:
        run()
        print(f"PASS {name}")
    max_request = max(REQUEST_TIMINGS, default=0.0)
    max_control = max(CONTROL_TIMINGS, default=0.0)
    assert max_request < 5 and max_control < 10, (
        f"request/control limit exceeded: {max_request:.3f}s/{max_control:.3f}s")
    print(f"TIMING requests={len(REQUEST_TIMINGS)} max_request_ms={max_request * 1000:.1f} "
          f"controls={len(CONTROL_TIMINGS)} max_control_ms={max_control * 1000:.1f}")
    print("PASS all independent Stage 1 checks")


if __name__ == "__main__":
    main()
