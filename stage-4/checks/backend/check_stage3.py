from __future__ import annotations

import datetime as dt
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
PARENT = ROOT.parent
JSON_TYPE = "application/json; charset=utf-8"
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def call(base, method, path, body=None, token=None, key=None):
    headers = {}
    if body is not None:
        headers["Content-Type"] = JSON_TYPE
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if key is not None:
        headers["Idempotency-Key"] = key
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        response = urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc
    except urllib.error.URLError as exc:
        raise AssertionError(f"{method} {path} transport error: {exc.reason}") from exc
    raw = response.read()
    content_type = response.headers.get("Content-Type")
    payload = json.loads(raw) if raw and content_type and content_type.startswith(
        "application/json") else raw
    return response.status, payload, response.headers


def expect(base, method, path, status, body=None, token=None, key=None):
    actual, payload, headers = call(base, method, path, body, token, key)
    assert actual == status, f"{method} {path}: expected {status}, got {actual}: {payload}"
    assert headers.get("Content-Type") == JSON_TYPE, headers
    return payload


def expect_empty(base, method, path, body=None):
    status, payload, headers = call(base, method, path, body)
    assert status == 204 and payload == b"", (status, payload)
    assert headers.get("Content-Type") is None, headers


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_server(root, db_path, port, static_dir):
    env = os.environ.copy()
    env.update(TABLEKEEPER_DB=str(db_path), TABLEKEEPER_STATIC=str(static_dir),
               PYTHONTZPATH="")
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1",
         "--port", str(port), "--no-access-log"], cwd=root, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_ready(base, process):
    for _ in range(100):
        if process.poll() is not None:
            raise AssertionError("service exited before becoming healthy")
        try:
            if expect(base, "GET", "/health", 200) == {"status": "ok"}:
                return
        except (OSError, urllib.error.URLError, AssertionError):
            time.sleep(0.1)
    raise AssertionError("service did not become healthy")


def fixture(managed=True):
    restaurant = {
        "id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin",
        "slot_minutes": 30, "reservation_duration_minutes": 90,
        "cancellation_cutoff_minutes": 120,
        "opening_hours": [{"weekday": day, "opens": "18:00", "closes": "23:00"}
                          for day in WEEKDAYS],
        "tables": [{"id": "t_1", "label": "1", "capacity": 2},
                   {"id": "t_2", "label": "2", "capacity": 4},
                   {"id": "t_3", "label": "3", "capacity": 6}],
    }
    if managed:
        restaurant["manager_user_ids"] = ["u_ada"]
    return {"users": [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada"},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob"}], "restaurants": [restaurant], "reservations": []}


def login(base, email="ada@example.com"):
    return expect(base, "POST", "/auth/login", 200,
                  {"email": email, "password": "correct horse"})["token"]


def date_after(days):
    return (dt.datetime.now(ZoneInfo("Europe/Berlin")).date() +
            dt.timedelta(days=days)).isoformat()


def all_week():
    return [{"weekday": day, "opens": "18:00", "closes": "23:00"} for day in WEEKDAYS]


def policy(effective_from, *, slot=30, duration=90, cutoff=120, capacities=None):
    return {"effective_from": effective_from, "slot_minutes": slot,
            "reservation_duration_minutes": duration,
            "cancellation_cutoff_minutes": cutoff, "opening_hours": all_week(),
            "capacities": capacities or {"t_1": 2, "t_2": 4, "t_3": 6}}


def make_booking(base, token, date, table="t_2", at="19:00", party=4, key=None):
    body = {"restaurant_id": "r_anker", "table_id": table,
            "starts_at_local": f"{date}T{at}", "party_size": party}
    return body, expect(base, "POST", "/reservations", 201, body, token,
                        key or f"book-{date}-{table}-{at}")


def next_weekly_dst_pair():
    zone = ZoneInfo("Europe/Berlin")
    today = dt.datetime.now(zone).date()
    for delta in range(1, 740):
        anchor = today + dt.timedelta(days=delta)
        if anchor.weekday() != 6:
            continue
        following = anchor + dt.timedelta(days=7)
        start = dt.datetime.combine(anchor, dt.time(19), zone)
        next_start = dt.datetime.combine(following, dt.time(19), zone)
        if start.utcoffset() != next_start.utcoffset():
            return anchor.isoformat(), following.isoformat()
    raise AssertionError("could not find a weekly DST transition")


def run_stage3(base):
    expect_empty(base, "POST", "/_test/reset", fixture())
    ada, bob = login(base), login(base, "bob@example.com")
    anonymous_detail = expect(base, "GET", "/restaurants/r_anker", 200)
    ada_detail = expect(base, "GET", "/restaurants/r_anker", 200, token=ada)
    bob_detail = expect(base, "GET", "/restaurants/r_anker", 200, token=bob)
    invalid_token_detail = expect(base, "GET", "/restaurants/r_anker", 200,
                                  token="expired-token")
    assert anonymous_detail["can_manage_policies"] is False
    assert ada_detail["can_manage_policies"] is True
    assert bob_detail["can_manage_policies"] is False
    assert invalid_token_detail["can_manage_policies"] is False
    assert all("manager_user_ids" not in item for item in
               (anonymous_detail, ada_detail, bob_detail, invalid_token_detail))

    # Concurrent publications allocate consecutive immutable versions; a racing replay
    # on one new key stores only one receipt and returns the original response.
    effective = date_after(24)
    policy_path = "/restaurants/r_anker/policies"
    versions = [policy(effective, slot=30), policy(effective, slot=60)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        published = list(pool.map(lambda args: call(
            base, "POST", policy_path, args[0], ada, args[1]),
            [(versions[0], "policy-race-a"), (versions[1], "policy-race-b")]))
    assert sorted(row[1]["policy_version"] for row in published) == [1, 2], published
    selected_version = next(row[1] for row in published if row[1]["policy_version"] == 2)
    tie_query = urllib.parse.urlencode({"restaurant_id": "r_anker", "date": effective,
                                        "party_size": 1, "explain": "true"})
    tie_slots = expect(base, "GET", "/availability?" + tie_query, 200)["slots"]
    assert tie_slots[0]["explain"][0]["policy_version"] == 2
    assert all(row["policy_version"] == 2 for row in tie_slots[0]["explain"])
    assert tie_slots[1]["starts_at_local"][-5:] == (
        dt.datetime.strptime(tie_slots[0]["starts_at_local"][-5:], "%H:%M") +
        dt.timedelta(minutes=selected_version["slot_minutes"])).strftime("%H:%M")
    replay_body, replay_key = policy(date_after(25)), "policy-same-key-race"
    with ThreadPoolExecutor(max_workers=2) as pool:
        raced = list(pool.map(lambda _: call(
            base, "POST", policy_path, replay_body, ada, replay_key), range(2)))
    assert sorted(row[0] for row in raced) == [200, 201], raced
    assert raced[0][1] == raced[1][1]
    assert [item["policy_version"] for item in
            expect(base, "GET", policy_path, 200)["policies"]] == [1, 2, 3]
    before = len(expect(base, "GET", policy_path, 200)["policies"])
    invalid = dict(policy(date_after(26)), capacities={"t_1": 2, "t_2": 4})
    expect(base, "POST", policy_path, 422, invalid, ada, "policy-invalid")
    assert len(expect(base, "GET", policy_path, 200)["policies"]) == before
    expect(base, "POST", policy_path, 403, policy(date_after(27)), bob, "not-manager")
    expect(base, "POST", "/restaurants/missing/policies", 404,
           policy(date_after(27)), ada, "unknown-restaurant")
    expect(base, "POST", policy_path, 401, policy(date_after(27)), key="no-token")

    booking_date = date_after(32)
    expected_policy = expect(base, "POST", policy_path, 201,
                             policy(booking_date, capacities={"t_1": 2, "t_2": 4, "t_3": 6}),
                             ada, "booking-policy")
    body, booking = make_booking(base, ada, booking_date)
    assert booking["revision"] == 1
    assert booking["accepted_terms"]["policy_version"] == expected_policy["policy_version"]
    reference = booking["reference"]

    query = urllib.parse.urlencode({"restaurant_id": "r_anker", "date": booking_date,
                                    "party_size": 4, "explain": "true"})
    available = expect(base, "GET", "/availability?" + query, 200)
    slot = next(item for item in available["slots"] if item["starts_at_local"].endswith("T19:00"))
    assert [item["table_id"] for item in slot["explain"]] == ["t_1", "t_2", "t_3"]
    assert slot["explain"][0]["rules"] == [
        {"rule": "capacity", "holds": False}, {"rule": "no_overlap", "holds": True}]
    assert slot["explain"][1]["rules"] == [
        {"rule": "capacity", "holds": True}, {"rule": "no_overlap", "holds": False}]
    assert slot["explain"][2]["available"] is True
    no_explain = urllib.parse.urlencode({"restaurant_id": "r_anker", "date": booking_date,
                                         "party_size": 4})
    assert all("explain" not in row for row in
               expect(base, "GET", "/availability?" + no_explain, 200)["slots"])
    invalid_explain = urllib.parse.urlencode({"restaurant_id": "r_anker", "date": booking_date,
                                              "party_size": 4, "explain": "false"})
    expect(base, "GET", "/availability?" + invalid_explain, 422)

    expect(base, "GET", f"/reservations/{reference}/history", 404)
    expect(base, "GET", f"/reservations/{reference}/history", 404, token=bob)
    created_history = expect(base, "GET", f"/reservations/{reference}/history", 200, token=ada)
    assert created_history["entries"][0]["event"] == "created"
    assert created_history["entries"][0]["accepted_terms"] == booking["accepted_terms"]
    expect(base, "GET", f"/reservations/{reference}/decision", 404)
    decision = expect(base, "GET", f"/reservations/{reference}/decision", 200, token=ada)
    assert decision == {"reference": reference, "revision": 1,
                        "accepted_terms": booking["accepted_terms"]}
    expect(base, "PATCH", f"/reservations/{reference}", 422,
           {"expected_revision": 0}, ada)

    # Exactly one concurrent edit may consume revision 1.
    edits = [{"expected_revision": 1, "table_id": "t_3"},
             {"expected_revision": 1, "starts_at_local": f"{booking_date}T20:30"}]
    with ThreadPoolExecutor(max_workers=2) as pool:
        edit_results = list(pool.map(lambda item: call(
            base, "PATCH", f"/reservations/{reference}", item, ada), edits))
    assert sorted(row[0] for row in edit_results) == [200, 409], edit_results
    stale = next(row[1] for row in edit_results if row[0] == 409)
    assert stale["error"]["code"] == "stale_revision"
    current = expect(base, "GET", f"/reservations/{reference}", 200, token=ada)
    assert current["revision"] == 2
    expect(base, "PATCH", f"/reservations/{reference}", 409,
           {"expected_revision": 1, "starts_at_local": "bad", "party_size": "bad"}, ada)
    same = {"expected_revision": 2,
            "table_ids" if len(current["table_ids"]) > 1 else "table_id":
                current["table_ids"] if len(current["table_ids"]) > 1 else current["table_id"],
            "starts_at_local": current["starts_at_local"],
            "party_size": current["party_size"]}
    expect(base, "PATCH", f"/reservations/{reference}", 200, same, ada)
    history = expect(base, "GET", f"/reservations/{reference}/history", 200, token=ada)
    assert [item["seq"] for item in history["entries"]] == [1, 2]
    assert history["entries"][1]["accepted_terms"] == current["accepted_terms"]
    amended_date = (dt.date.fromisoformat(booking_date) + dt.timedelta(days=1)).isoformat()
    next_policy = expect(base, "POST", policy_path, 201,
                         policy(amended_date, duration=60), ada, "next-date-policy")
    unchanged = expect(base, "GET", f"/reservations/{reference}", 200, token=ada)
    assert unchanged["accepted_terms"] == current["accepted_terms"]
    assert unchanged["ends_at"] == current["ends_at"]
    amended = expect(base, "PATCH", f"/reservations/{reference}", 200,
                     {"expected_revision": 2, "starts_at_local": f"{amended_date}T19:00"}, ada)
    assert amended["revision"] == 3
    assert amended["accepted_terms"]["policy_version"] == next_policy["policy_version"]
    assert (dt.datetime.fromisoformat(amended["ends_at"]) -
            dt.datetime.fromisoformat(amended["starts_at"])).total_seconds() == 3600
    cancelled = expect(base, "POST", f"/reservations/{reference}/cancel", 200, token=ada)
    assert cancelled["revision"] == 4
    expect(base, "POST", f"/reservations/{reference}/cancel", 200, token=ada)
    history = expect(base, "GET", f"/reservations/{reference}/history", 200, token=ada)
    assert [item["event"] for item in history["entries"]] == [
        "created", "changed", "changed", "cancelled"]
    assert history["entries"][-1]["changes"] == []

    # Cross the next Europe/Berlin DST change while preserving the local wall clock;
    # select a new policy independently for the generated date.
    anchor_date, occurrence_date = next_weekly_dst_pair()
    occurrence_policy = policy(occurrence_date, duration=60)
    dst_policy = expect(base, "POST", policy_path, 201, occurrence_policy, ada, "dst-policy")
    _, anchor = make_booking(base, ada, anchor_date, key="dst-anchor")
    series_body = {"anchor_reference": anchor["reference"], "count": 2,
                   "interval_weeks": 1}
    with ThreadPoolExecutor(max_workers=2) as pool:
        series_results = list(pool.map(lambda _: call(
            base, "POST", "/series", series_body, ada, "dst-series-race"), range(2)))
    assert sorted(row[0] for row in series_results) == [200, 201], series_results
    assert series_results[0][1] == series_results[1][1]
    series = series_results[0][1]
    assert series["occurrences"][0]["reservation"] == anchor
    generated = series["occurrences"][1]["reservation"]
    assert generated["starts_at_local"] == f"{occurrence_date}T19:00"
    anchor_instant = dt.datetime.fromisoformat(anchor["starts_at"])
    occurrence_instant = dt.datetime.fromisoformat(generated["starts_at"])
    assert occurrence_instant.utcoffset() != anchor_instant.utcoffset()
    assert occurrence_instant.hour == anchor_instant.hour == 19
    assert generated["accepted_terms"]["policy_version"] == dst_policy["policy_version"]
    assert generated["accepted_terms"]["reservation_duration_minutes"] == 60
    series_id = series["series_id"]
    series_url = f"/series/{series_id}"
    expect(base, "GET", series_url, 404)
    expect(base, "GET", series_url, 404, token=bob)
    changed = expect(base, "PATCH", f"/reservations/{generated['reference']}", 200,
                     {"expected_revision": 1, "table_id": "t_3"}, ada)
    assert changed["revision"] == 2
    moved = expect(base, "POST", "/reservation-moves", 201,
                   {"moves": [{"reference": generated["reference"],
                               "expected_revision": 2,
                               "starts_at_local": f"{occurrence_date}T20:30"}]},
                   ada, "series-member-move")
    assert moved["reservations"][0]["revision"] == 3
    current_series = expect(base, "GET", series_url, 200, token=ada)
    assert current_series["revision"] == 3
    assert current_series["occurrences"][1]["exception"] is True
    assert expect(base, "POST", "/series", 200, series_body, ada,
                  "dst-series-race") == series
    expect(base, "POST", f"/reservations/{anchor['reference']}/cancel", 200, token=ada)
    expect(base, "POST", f"/reservations/{anchor['reference']}/cancel", 200, token=ada)
    series_before_roundtrip = expect(base, "GET", series_url, 200, token=ada)
    assert series_before_roundtrip["revision"] == 4
    assert series_before_roundtrip["occurrences"][1][
        "reservation"]["status"] == "confirmed"
    stage3_snapshot = expect(base, "GET", "/_test/export", 200)
    expect_empty(base, "POST", "/_test/import", stage3_snapshot)
    assert expect(base, "GET", series_url, 200, token=ada) == series_before_roundtrip

    # A failed recurring operation leaves no rows, revision bump, or key receipt.
    start = date_after(70)
    _, recurring_anchor = make_booking(base, ada, start, key="atomic-anchor")
    blocked_day = (dt.date.fromisoformat(start) + dt.timedelta(days=14)).isoformat()
    _, blocker = make_booking(base, ada, blocked_day, key="series-blocker")
    failed_body = {"anchor_reference": recurring_anchor["reference"], "count": 3,
                   "interval_weeks": 1}
    before_failure = expect(base, "GET", "/_test/export", 200)["state"]
    failed = expect(base, "POST", "/series", 409, failed_body, ada, "retry-series-after-failure")
    assert failed["error"]["code"] == "table_unavailable"
    after_failure = expect(base, "GET", "/_test/export", 200)["state"]
    assert after_failure == before_failure
    expect(base, "POST", f"/reservations/{blocker['reference']}/cancel", 200, token=ada)
    success = expect(base, "POST", "/series", 201, failed_body, ada,
                     "retry-series-after-failure")
    assert len(success["occurrences"]) == 3
    cancelled_occurrence = success["occurrences"][2]["reference"]
    expect(base, "POST", f"/reservations/{cancelled_occurrence}/cancel", 200, token=ada)
    after_cancel = expect(base, "GET", f"/series/{success['series_id']}", 200, token=ada)
    assert after_cancel["revision"] == 2
    assert after_cancel["occurrences"][2]["exception"] is False
    assert after_cancel["occurrences"][2]["reservation"]["status"] == "cancelled"

    # A failed two-reservation move is all-or-nothing and does not consume its key.
    move_day = date_after(42)
    _, first = make_booking(base, ada, move_day, "t_1", party=2, key="move-a")
    _, second = make_booking(base, ada, move_day, "t_3", party=2, key="move-b")
    _, move_blocker = make_booking(base, ada, move_day, "t_2", party=4, key="move-blocker")
    move_body = {"moves": [
        {"reference": first["reference"], "table_id": "t_2", "expected_revision": 1},
        {"reference": second["reference"], "table_id": "t_1", "expected_revision": 1}]}
    before_move = expect(base, "GET", "/_test/export", 200)["state"]
    failure = expect(base, "POST", "/reservation-moves", 409, move_body, ada,
                     "retry-move-after-failure")
    assert failure["error"]["code"] == "table_unavailable"
    assert expect(base, "GET", "/_test/export", 200)["state"] == before_move
    expect(base, "POST", f"/reservations/{move_blocker['reference']}/cancel", 200, token=ada)
    moved = expect(base, "POST", "/reservation-moves", 201, move_body, ada,
                   "retry-move-after-failure")
    assert [row["revision"] for row in moved["reservations"]] == [2, 2]
    assert [row["table_id"] for row in moved["reservations"]] == ["t_2", "t_1"]


def check_pair_order_noops(base):
    data = fixture()
    data["restaurants"][0]["combinable"] = [["t_1", "t_2"]]
    expect_empty(base, "POST", "/_test/reset", data)
    ada = login(base)
    date = date_after(35)
    _, original = make_booking(base, ada, date, table="t_3", party=6,
                               key="pair-order-original")
    paired = expect(base, "PATCH", f"/reservations/{original['reference']}",
                    200, {"expected_revision": 1, "table_ids": ["t_2", "t_1"]}, ada)
    assert paired["revision"] == 2 and paired["table_ids"] == ["t_1", "t_2"]
    history_path = f"/reservations/{original['reference']}/history"
    history_before = expect(base, "GET", history_path, 200, token=ada)
    series = expect(base, "POST", "/series", 201,
                    {"anchor_reference": original["reference"], "count": 2,
                     "interval_weeks": 1}, ada, "pair-order-series")
    series_path = f"/series/{series['series_id']}"
    series_before = expect(base, "GET", series_path, 200, token=ada)
    state_before = expect(base, "GET", "/_test/export", 200)["state"]

    reversed_noop = expect(base, "PATCH", f"/reservations/{original['reference']}",
                           200, {"expected_revision": 2,
                                 "table_ids": ["t_2", "t_1"]}, ada)
    assert reversed_noop == paired
    assert expect(base, "GET", history_path, 200, token=ada) == history_before
    assert expect(base, "GET", series_path, 200, token=ada) == series_before
    assert expect(base, "GET", "/_test/export", 200)["state"] == state_before

    moved = expect(base, "POST", "/reservation-moves", 201,
                   {"moves": [{"reference": original["reference"],
                               "expected_revision": 2,
                               "table_ids": ["t_2", "t_1"]}]},
                   ada, "pair-order-move-noop")
    assert moved["reservations"] == [paired]
    state_after_move = expect(base, "GET", "/_test/export", 200)["state"]
    assert state_after_move["reservations"] == state_before["reservations"]
    assert state_after_move["restaurants"] == state_before["restaurants"]
    assert expect(base, "GET", history_path, 200, token=ada) == history_before
    assert expect(base, "GET", series_path, 200, token=ada) == series_before

    data = fixture()
    data["restaurants"][0]["cancellation_cutoff_minutes"] = 10080
    expect_empty(base, "POST", "/_test/reset", data)
    ada = login(base)
    _, booking = make_booking(base, ada, date_after(1), table="t_3", party=6,
                             key="pair-order-cutoff")
    path = f"/reservations/{booking['reference']}"
    invalid_pair = {"table_ids": ["t_1", "t_3"]}
    stale = expect(base, "PATCH", path, 409,
                   {**invalid_pair, "expected_revision": 2}, ada)
    assert stale["error"]["code"] == "stale_revision"
    cutoff = expect(base, "PATCH", path, 409,
                    {**invalid_pair, "expected_revision": 1}, ada)
    assert cutoff["error"]["code"] == "cutoff_passed"


def run_populated_upgrade(stage1, stage2, stage3):
    legacy = fixture(managed=False)
    expect_empty(stage1, "POST", "/_test/reset", legacy)
    token = login(stage1)
    old_body = {"restaurant_id": "r_anker", "table_id": "t_2",
                "starts_at_local": f"{date_after(28)}T19:00", "party_size": 4}
    original = expect(stage1, "POST", "/reservations", 201, old_body, token,
                      "stage1-original-receipt")
    stage1_export = expect(stage1, "GET", "/_test/export", 200)
    expect_empty(stage2, "POST", "/_test/import", stage1_export)
    stage2_export = expect(stage2, "GET", "/_test/export", 200)
    expect_empty(stage3, "POST", "/_test/import", stage2_export)
    imported = expect(stage3, "GET", "/reservations", 200, token=token)["reservations"]
    assert len(imported) == 1 and imported[0]["reference"] == original["reference"]
    assert imported[0]["reservation_id"] == original["reservation_id"]
    replayed = expect(stage3, "POST", "/reservations", 200, old_body, token,
                      "stage1-original-receipt")
    assert replayed == original
    history = expect(stage3, "GET", f"/reservations/{original['reference']}/history",
                      200, token=token)["entries"]
    assert len(history) == 1 and history[0]["revision"] == 1
    adopted = expect(stage3, "POST", "/series", 201,
                     {"anchor_reference": original["reference"], "count": 2,
                      "interval_weeks": 1}, token, "upgrade-adoption")
    assert adopted["occurrences"][0]["reservation"]["reference"] == original["reference"]

    # A populated Stage 2 pair and its response receipt also upgrade without changing
    # the old response shape or the user's stored identity.
    pair_fixture = fixture(managed=False)
    pair_fixture["restaurants"][0]["combinable"] = [["t_1", "t_2"]]
    expect_empty(stage2, "POST", "/_test/reset", pair_fixture)
    stage2_token = login(stage2)
    pair_body = {"restaurant_id": "r_anker", "table_ids": ["t_1", "t_2"],
                 "starts_at_local": f"{date_after(35)}T19:00", "party_size": 6}
    pair_original = expect(stage2, "POST", "/reservations", 201, pair_body,
                           stage2_token, "stage2-pair-original")
    pair_export = expect(stage2, "GET", "/_test/export", 200)
    expect_empty(stage3, "POST", "/_test/import", pair_export)
    pair_rows = expect(stage3, "GET", "/reservations", 200,
                       token=stage2_token)["reservations"]
    assert len(pair_rows) == 1 and pair_rows[0]["table_ids"] == ["t_1", "t_2"]
    assert pair_rows[0]["revision"] == 1 and pair_rows[0]["accepted_terms"]["policy_version"] == 0
    pair_replay = expect(stage3, "POST", "/reservations", 200, pair_body,
                         stage2_token, "stage2-pair-original")
    assert pair_replay == pair_original


def main():
    with tempfile.TemporaryDirectory(prefix="tablekeeper-stage3-") as temporary:
        temp = Path(temporary)
        static = temp / "static"
        (static / "assets").mkdir(parents=True)
        (static / "index.html").write_text("<!doctype html><title>check</title>",
                                            encoding="utf-8")
        roots = {"stage1": PARENT / "stage-1", "stage2": PARENT / "stage-2",
                 "stage3": ROOT}
        ports = {name: free_port() for name in roots}
        bases = {name: f"http://127.0.0.1:{port}" for name, port in ports.items()}
        processes = {name: start_server(root, temp / f"{name}.sqlite3", ports[name], static)
                     for name, root in roots.items()}
        try:
            for name, process in processes.items():
                wait_ready(bases[name], process)
            run_stage3(bases["stage3"])
            check_pair_order_noops(bases["stage3"])
            run_populated_upgrade(bases["stage1"], bases["stage2"], bases["stage3"])
        finally:
            for process in processes.values():
                process.terminate()
            for process in processes.values():
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    print("Stage 3 focused backend checks passed: policies/replay races, explain/history/revision,")
    print("atomic series and moves, DST policy recurrence, and populated Stage 1-to-2-to-3 import.")


if __name__ == "__main__":
    main()
