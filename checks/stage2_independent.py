#!/usr/bin/env python3
"""Independent Stage 2 pair, occupancy, move, and upgrade checks."""
from __future__ import annotations

import argparse
import copy
import concurrent.futures
from collections import Counter
import json
from urllib.parse import urlencode
import uuid

import stage1_independent as s1


def pair_fixture() -> dict:
    restaurant = s1.restaurant("r_combo", tables=[
        {"id": "t_a", "label": "A", "capacity": 2},
        {"id": "t_b", "label": "B", "capacity": 4},
        {"id": "t_c", "label": "C", "capacity": 3},
        {"id": "t_d", "label": "D", "capacity": 5},
    ])
    restaurant["combinable"] = [["t_c", "t_a"], ["t_a", "t_b"], ["t_b", "t_d"]]
    return s1.fixture(restaurants=[restaurant])


def key(label: str) -> str:
    return f"s2-{label}-{uuid.uuid4().hex}"


def token_for(base: str) -> str:
    return s1.login(base, s1.user(0))


def post_booking(base: str, token: str, *, date: str, at: str = "19:00",
                 party: int = 5, table_id: str | None = None,
                 table_ids: list[str] | None = None, idem: str | None = None):
    body = {"restaurant_id": "r_combo", "starts_at_local": f"{date}T{at}",
            "party_size": party}
    if table_id is not None:
        body["table_id"] = table_id
    if table_ids is not None:
        body["table_ids"] = table_ids
    return s1.call(base, "/reservations", "POST", body, token=token,
                   key=idem or key("booking"))


def availability(base: str, date: str, *, at: str = "19:00", party: int = 5):
    query = urlencode({"restaurant_id": "r_combo", "date": date,
                       "party_size": party})
    reply = s1.expect(s1.call(base, f"/availability?{query}"), 200)
    return next(slot for slot in reply.body["slots"]
                if slot["starts_at_local"] == f"{date}T{at}")


def check_pair_options_and_post_rules(base: str) -> None:
    s1.reset(base, pair_fixture())
    token = token_for(base)
    date = s1.local_date()

    slot = availability(base, date)
    assert slot["available_table_ids"] == ["t_d"], slot
    assert slot["available_options"] == [
        {"table_ids": ["t_d"], "capacity": 5},
        {"table_ids": ["t_c", "t_a"], "capacity": 5},
        {"table_ids": ["t_a", "t_b"], "capacity": 6},
        {"table_ids": ["t_b", "t_d"], "capacity": 9},
    ], slot["available_options"]
    too_large = availability(base, date, party=6)
    assert too_large["available_table_ids"] == []
    assert too_large["available_options"] == [
        {"table_ids": ["t_a", "t_b"], "capacity": 6},
        {"table_ids": ["t_b", "t_d"], "capacity": 9},
    ]

    pair = s1.expect(post_booking(base, token, date=date, table_ids=["t_a", "t_c"]),
                     201).body
    assert pair["table_ids"] == ["t_c", "t_a"] and "table_id" not in pair, pair
    single = s1.expect(post_booking(base, token, date=date, at="20:30", party=4,
                                    table_id="t_d"), 201).body
    assert single["table_ids"] == ["t_d"] and single["table_id"] == "t_d", single
    single_set = s1.expect(post_booking(base, token, date=date, at="21:00", party=2,
                                        table_ids=["t_a"]), 201).body
    assert single_set["table_ids"] == ["t_a"] and single_set["table_id"] == "t_a", single_set

    cases = [
        ({"table_ids": ["t_c", "t_b"]}, 422, "combination_not_allowed"),
        ({"table_ids": ["t_a", "t_b", "t_d"]}, 422, "combination_not_allowed"),
        ({"table_ids": ["t_a", "t_a"]}, 422, "validation_failed"),
        ({"table_ids": "t_a"}, 400, "malformed_request"),
        ({"table_ids": [7, "t_a"]}, 400, "malformed_request"),
        ({"table_ids": ["t_c", "t_a"], "party_size": 6},
         422, "party_exceeds_capacity"),
        ({"table_id": "t_d", "table_ids": ["t_d"]}, 422, "validation_failed"),
    ]
    for index, (fields, status, code) in enumerate(cases):
        body = {"restaurant_id": "r_combo", "starts_at_local": f"{date}T21:00",
                "party_size": 5, **fields}
        s1.expect(s1.call(base, "/reservations", "POST", body, token=token,
                          key=key(f"invalid-{index}")), status, code)
    print("PASS pair ordering, capacities, non-transitivity, response shape, and POST rules")


def check_pair_occupancy_and_cancel(base: str) -> None:
    s1.reset(base, pair_fixture())
    token = token_for(base)
    date = s1.local_date()
    created = s1.expect(post_booking(base, token, date=date,
                                     table_ids=["t_c", "t_a"]), 201).body

    during = availability(base, date, at="20:00")
    assert ["t_c", "t_a"] not in [option["table_ids"]
                                    for option in during["available_options"]]
    at_end = availability(base, date, at="20:30")
    assert ["t_c", "t_a"] in [option["table_ids"]
                                for option in at_end["available_options"]]

    held = s1.expect(post_booking(base, token, date=date, at="20:30", party=4,
                                  table_id="t_b"), 201).body
    occupied_pair = availability(base, date, at="20:30")
    assert ["t_b", "t_d"] not in [option["table_ids"]
                                    for option in occupied_pair["available_options"]]

    s1.expect(s1.call(base, f"/reservations/{created['reference']}/cancel", "POST",
                      token=token), 200)
    freed = availability(base, date)
    assert ["t_c", "t_a"] in [option["table_ids"] for option in freed["available_options"]]
    assert ["t_a", "t_c"] not in [option["table_ids"]
                                    for option in freed["available_options"]]
    assert held["table_id"] == "t_b"
    print("PASS pair occupancy on any member, half-open adjacency, and cancellation release")


def check_patch_and_moves(base: str) -> None:
    s1.reset(base, pair_fixture())
    token = token_for(base)
    date = s1.local_date()
    original = s1.expect(post_booking(base, token, date=date, party=4,
                                      table_id="t_d"), 201).body
    patched = s1.expect(s1.call(base, f"/reservations/{original['reference']}",
                               "PATCH", {"table_ids": ["t_a", "t_c"]},
                               token=token), 200).body
    assert patched["table_ids"] == ["t_c", "t_a"] and "table_id" not in patched
    detail = s1.expect(s1.call(base, f"/reservations/{original['reference']}",
                               token=token), 200).body
    assert detail == patched
    s1.expect(s1.call(base, f"/reservations/{original['reference']}", "PATCH",
                      {"table_ids": ["t_a", "t_d"]}, token=token),
              422, "combination_not_allowed")
    assert s1.expect(s1.call(base, f"/reservations/{original['reference']}",
                             token=token), 200).body == patched
    s1.expect(s1.call(base, f"/reservations/{original['reference']}/cancel", "POST",
                      token=token), 200)
    free = availability(base, date)
    assert free["available_table_ids"] == ["t_d"]
    assert ["t_c", "t_a"] in [option["table_ids"]
                                for option in free["available_options"]]

    moved_from = s1.expect(post_booking(base, token, date=date, at="20:30", party=4,
                                        table_id="t_d"), 201).body
    moved = s1.expect(s1.call(base, "/reservation-moves", "POST", {
        "moves": [{"reference": moved_from["reference"],
                   "table_ids": ["t_a", "t_c"]}]},
        token=token, key=key("pair-move")), 201).body
    moved_row = moved["reservations"][0]
    assert moved_row["table_ids"] == ["t_c", "t_a"] and "table_id" not in moved_row
    assert s1.expect(s1.call(base, f"/reservations/{moved_from['reference']}",
                             token=token), 200).body == moved_row
    print("PASS PATCH pair normalization/rollback and pair moves")


def check_move_conflict_rollback(base: str) -> None:
    s1.reset(base, pair_fixture())
    token = token_for(base)
    date = s1.local_date()
    held = s1.expect(post_booking(base, token, date=date, party=2,
                                  table_id="t_a"), 201).body
    moving = s1.expect(post_booking(base, token, date=date, party=4,
                                    table_id="t_d"), 201).body
    before = [held, moving]
    reply = s1.call(base, "/reservation-moves", "POST", {
        "moves": [{"reference": moving["reference"],
                   "table_ids": ["t_a", "t_c"]}]},
        token=token, key=key("conflicting-pair-move"))
    s1.expect(reply, 409, "table_unavailable")
    after = [s1.expect(s1.call(base, f"/reservations/{row['reference']}",
                              token=token), 200).body for row in before]
    assert after == before, after
    print("PASS failed pair move leaves all reservations unchanged")


def check_concurrent_pair_occupancy(base: str) -> None:
    s1.reset(base, pair_fixture())
    token = token_for(base)
    date = s1.local_date()

    def submit(index: int):
        return post_booking(base, token, date=date, table_ids=["t_a", "t_c"],
                            idem=key(f"pair-race-{index}"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as pool:
        replies = list(pool.map(submit, range(50)))
    counts = Counter(reply.status for reply in replies)
    assert counts == Counter({201: 1, 409: 49}), counts
    assert all(reply.body.get("error", {}).get("code") == "table_unavailable"
               for reply in replies if reply.status == 409)
    print("PASS 50 concurrent bookings sharing a combined-table member")


def check_stage1_export_upgrade(source: str, target: str) -> None:
    account = s1.user(72)
    restaurant = s1.restaurant("r_upgrade")
    s1.reset(source, s1.fixture(users=[account], restaurants=[restaurant]))
    token = s1.login(source, account)
    date = s1.local_date()
    body = {"restaurant_id": "r_upgrade", "table_id": "t_2",
            "starts_at_local": f"{date}T19:00", "party_size": 4}
    request_key = key("stage1-receipt")
    original = s1.expect(s1.call(source, "/reservations", "POST", body,
                                token=token, key=request_key), 201).body
    snapshot = s1.expect(s1.call(source, "/_test/export"), 200).body

    destination = s1.fixture(users=[s1.user(73)],
                             restaurants=[s1.restaurant("r_replaced")])
    s1.reset(target, destination)
    s1.expect(s1.call(target, "/_test/import", "POST", snapshot, timeout=10), 204)
    retained = s1.expect(s1.call(target, "/reservations", token=token), 200).body
    assert [row["reference"] for row in retained["reservations"]] == [original["reference"]]
    replay = s1.expect(s1.call(target, "/reservations", "POST", body,
                               token=token, key=request_key), 200).body
    differences = {field: (original.get(field), replay.get(field))
                   for field in original.keys() | replay.keys()
                   if original.get(field) != replay.get(field)}
    assert not differences, f"imported receipt response changed: {differences!r}"
    print("PASS populated Stage 1 export import retains token, reservation, and original receipt")


def check_stage1_receipts_after_pair_upgrade(source: str, target: str) -> dict:
    """Compare original create/move receipt JSON after cancellation and pair upgrade."""
    account = s1.user(82)
    s1.reset(source, s1.fixture(users=[account],
                                restaurants=[s1.restaurant("r_upgrade")]))
    token = s1.login(source, account)
    date = s1.local_date(14)
    body = s1.booking_body(date, table="t_2", party=4,
                           restaurant_id="r_upgrade")
    create_key = key("receipt-upgrade-create")
    created = s1.expect(s1.call(source, "/reservations", "POST", body,
                                token=token, key=create_key), 201).body

    moves = [
        {"moves": [{"reference": created["reference"], "table_id": "t_3"}]},
        {"moves": [{"reference": created["reference"], "table_id": "t_2"}]},
    ]
    move_keys = [key("receipt-upgrade-move-out"), key("receipt-upgrade-move-back")]
    originals = [
        s1.expect(s1.call(source, "/reservation-moves", "POST", move,
                          token=token, key=move_key), 201).body
        for move, move_key in zip(moves, move_keys)
    ]
    cancelled = s1.expect(s1.call(
        source, f"/reservations/{created['reference']}/cancel", "POST",
        token=token), 200)
    create_after_cancel = s1.expect(s1.call(
        source, "/reservations", "POST", body, token=token, key=create_key), 200).body
    move_after_cancel = [
        s1.expect(s1.call(source, "/reservation-moves", "POST", move,
                          token=token, key=move_key), 200).body
        for move, move_key in zip(moves, move_keys)
    ]
    assert create_after_cancel == created
    assert move_after_cancel == originals

    snapshot = s1.expect(s1.call(source, "/_test/export"), 200).body
    upgraded = copy.deepcopy(snapshot)
    upgraded["state"]["restaurants"][0]["combinable"] = [
        ["t_1", "t_2"], ["t_2", "t_3"]]
    s1.reset(target, s1.fixture(users=[s1.user(83)],
                               restaurants=[s1.restaurant("r_discarded")]))
    imported = s1.expect(s1.call(target, "/_test/import", "POST", upgraded,
                                 timeout=10), 204)
    current = s1.expect(s1.call(
        target, f"/reservations/{created['reference']}", token=token), 200).body
    assert current["status"] == "cancelled"
    assert current["table_ids"] == ["t_2"]
    assert s1.expect(s1.call(target, "/restaurants/r_upgrade"), 200).body[
        "combinable"] == [["t_1", "t_2"], ["t_2", "t_3"]]

    later = s1.booking_body(date, table="t_1", at="19:00", party=2,
                            restaurant_id="r_upgrade")
    later_write = s1.expect(s1.call(target, "/reservations", "POST", later,
                                    token=token, key=key("later-resource-write")),
                            201)
    replay_create = s1.expect(s1.call(target, "/reservations", "POST", body,
                                      token=token, key=create_key), 200).body
    replay_moves = [
        s1.expect(s1.call(target, "/reservation-moves", "POST", move,
                          token=token, key=move_key), 200).body
        for move, move_key in zip(moves, move_keys)
    ]
    assert replay_create == created
    assert replay_moves == originals
    assert "table_ids" not in replay_create
    assert all("table_ids" not in row
               for receipt in replay_moves for row in receipt["reservations"])
    result = {
        "source_stage1_create_status": 201,
        "source_stage1_move_statuses": [201, 201],
        "source_cancel_status": cancelled.status,
        "source_replays_after_cancel_equal": True,
        "stage2_pair_upgrade_import_status": imported.status,
        "stage2_current_read_status": current["status"],
        "stage2_current_read_table_ids": current["table_ids"],
        "stage2_resource_change_status": later_write.status,
        "stage2_replay_statuses": [200, 200, 200],
        "stage2_create_receipt_json_equal": replay_create == created,
        "stage2_move_receipt_json_equal": [a == b for a, b in zip(replay_moves, originals)],
        "stage2_replays_preserve_stage1_response_shape": True,
    }
    print("PASS Stage 1 create and move receipts remain exact after cancellation, "
          "later moves, populated import, Stage 2 pair upgrade, and a later write")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Stage 2 service under test")
    parser.add_argument("--stage1-url", help="Stage 1 export source for upgrade coverage")
    parser.add_argument("--receipt-result",
                        help="write redacted create/move receipt recheck results as JSON")
    args = parser.parse_args()

    check_pair_options_and_post_rules(args.base_url)
    check_pair_occupancy_and_cancel(args.base_url)
    check_patch_and_moves(args.base_url)
    check_move_conflict_rollback(args.base_url)
    check_concurrent_pair_occupancy(args.base_url)
    if args.stage1_url:
        check_stage1_export_upgrade(args.stage1_url, args.base_url)
        receipt_result = check_stage1_receipts_after_pair_upgrade(
            args.stage1_url, args.base_url)
        if args.receipt_result:
            with open(args.receipt_result, "w", encoding="utf-8", newline="\n") as result_file:
                json.dump(receipt_result, result_file, indent=2, ensure_ascii=False)
                result_file.write("\n")
    print("PASS independent Stage 2 API checks")


if __name__ == "__main__":
    main()
