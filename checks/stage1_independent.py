#!/usr/bin/env python3
"""Independent HTTP checks for Tablekeeper concurrency, transactions, and time."""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
from collections import Counter
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
PASSWORD = "correct horse"


@dataclass(frozen=True)
class Reply:
    status: int
    body: dict


def call(base: str, path: str, method: str = "GET", body=None, *,
         token: str | None = None, key: str | None = None, timeout: float = 5) -> Reply:
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if key is not None:
        headers["Idempotency-Key"] = key
    request = Request(base.rstrip("/") + path, data=data,
                      headers=headers, method=method)
    try:
        response = urlopen(request, timeout=timeout)
    except HTTPError as error:
        response = error
    raw = response.read()
    parsed = json.loads(raw) if raw else {}
    return Reply(response.code, parsed)


def expect(reply: Reply, status: int, code: str | None = None) -> Reply:
    got_code = reply.body.get("error", {}).get("code")
    assert reply.status == status and (code is None or got_code == code), (
        f"expected HTTP {status}{' '+code if code else ''}; "
        f"got HTTP {reply.status}{' '+str(got_code) if got_code else ''}")
    return reply


def user(index: int, email: str | None = None) -> dict:
    return {"id": f"u_qa_{index}", "email": email or f"qa{index}@example.com",
            "password": PASSWORD, "display_name": f"QA {index}"}


def restaurant(rid: str = "r_qa", *, timezone: str = "Europe/Berlin",
               opens: str = "18:00", closes: str = "23:00",
               tables: list[dict] | None = None) -> dict:
    return {
        "id": rid, "name": "QA Restaurant", "timezone": timezone,
        "slot_minutes": 30, "reservation_duration_minutes": 90,
        "cancellation_cutoff_minutes": 120,
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
    failed_body = booking_body(date, table="missing-table", at="20:30")
    expect(call(source, "/reservations", "POST", failed_body, token=token,
                key="failed-key-before-export"), 404, "not_found")
    exported = expect(call(source, "/_test/export"), 200).body
    assert exported.get("track") == "tablekeeper" and exported.get("format_version") == 1

    destination_fixture = fixture(users=[user(7)], restaurants=[restaurant("r_discarded")])
    reset(target, destination_fixture)
    expect(call(target, "/_test/import", "POST", exported, timeout=10), 204)

    assert expect(call(target, "/reservations", token=token), 200).body["reservations"] \
        == [original]
    assert expect(call(target, f"/reservations/{original['reference']}", token=token),
                  200).body == original
    imported_login_token = login(target, account)
    assert expect(call(target, "/reservations", token=imported_login_token), 200).body["reservations"] \
        == [original]
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

    before_bad_import = expect(call(target, "/reservations", token=token), 200).body
    invalid = {**exported, "track": "wrong-track"}
    expect(call(target, "/_test/import", "POST", invalid, timeout=10),
           422, "validation_failed")
    after_bad_import = expect(call(target, "/reservations", token=token), 200).body
    assert after_bad_import == before_bad_import

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
        ("strict types and idempotency precedence",
         lambda: check_validation_precedence(args.base_url)),
        ("atomic swap, rollback, failed-key reuse and receipt replay",
         lambda: check_move_swap_and_rollback(args.base_url)),
        ("Berlin/New York DST and absolute durations",
         lambda: check_dst_and_zones(args.base_url)),
        ("populated import, retained token and original receipts",
         lambda: check_import_preserves_receipts(args.source_url or args.base_url,
                                                  args.base_url)),
    ]
    for name, run in checks:
        run()
        print(f"PASS {name}")
    print("PASS all independent Stage 1 checks")


if __name__ == "__main__":
    main()
