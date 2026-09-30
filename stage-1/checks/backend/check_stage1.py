from __future__ import annotations

import concurrent.futures
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATE = "2027-01-04"


def call(base: str, method: str, path: str, body=None, token=None, key=None):
    headers = {}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if key is not None:
        headers["Idempotency-Key"] = key
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        response = urllib.request.urlopen(req, timeout=4)
    except urllib.error.HTTPError as exc:
        response = exc
    except urllib.error.URLError as exc:
        raise AssertionError(f"{method} {path} transport error: {exc.reason}") from exc
    raw = response.read()
    return response.status, None if not raw else json.loads(raw)


def fixture(timezone="Europe/Berlin", name="Zum Anker"):
    return {
        "users": [{"id": "u_ada", "email": "ada@example.com",
                   "password": "correct horse", "display_name": "Ada"}],
        "restaurants": [{
            "id": "r_anker", "name": name, "timezone": timezone,
            "slot_minutes": 30, "reservation_duration_minutes": 90,
            "cancellation_cutoff_minutes": 120,
            "opening_hours": [{"weekday": day, "opens": "18:00" if timezone != "UTC" else "00:00",
                               "closes": "23:00" if timezone != "UTC" else "23:30"}
                              for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")],
            "tables": [{"id": "t_1", "label": "1", "capacity": 2},
                       {"id": "t_2", "label": "2", "capacity": 4},
                       {"id": "t_3", "label": "3", "capacity": 6}],
        }],
        "reservations": [],
    }


def require(status, wanted, body=None):
    assert status == wanted, f"expected {wanted}, got {status}: {body}"


def main():
    with tempfile.TemporaryDirectory(prefix="tablekeeper-check-") as temporary:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        env = os.environ.copy()
        env["TABLEKEEPER_DB"] = str(Path(temporary) / "state.sqlite3")
        env["PYTHONTZPATH"] = ""
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1",
             "--port", str(port), "--no-access-log"],
            cwd=ROOT, env=env, stdout=sys.stderr, stderr=sys.stderr)
        try:
            for _ in range(100):
                if server.poll() is not None:
                    raise AssertionError("Uvicorn exited before becoming healthy")
                try:
                    status, body = call(base, "GET", "/health")
                    if status == 200 and body == {"status": "ok"}:
                        break
                except (OSError, urllib.error.URLError, AssertionError):
                    time.sleep(0.1)
            else:
                raise AssertionError("service did not become healthy")

            require(call(base, "POST", "/_test/reset", fixture())[0], 204)
            status, login = call(base, "POST", "/auth/login", {
                "email": "ada@example.com", "password": "correct horse"})
            require(status, 200, login)
            token = login["token"]

            body = {"restaurant_id": "r_anker", "table_id": "t_2",
                    "starts_at_local": f"{DATE}T19:00", "party_size": 4}
            status, original = call(base, "POST", "/reservations", body, token, "receipt-1")
            require(status, 201, original)
            reordered = {"party_size": 4, "starts_at_local": body["starts_at_local"],
                         "table_id": "t_2", "restaurant_id": "r_anker"}
            status, replayed = call(base, "POST", "/reservations", reordered, token, "receipt-1")
            require(status, 200, replayed)
            assert replayed == original
            adjacent = {**body, "starts_at_local": f"{DATE}T20:30"}
            require(call(base, "POST", "/reservations", adjacent, token, "adjacent")[0], 201)
            require(call(base, "POST", f"/reservations/{original['reference']}/cancel",
                         token=token)[0], 200)
            status, replayed = call(base, "POST", "/reservations", body, token, "receipt-1")
            require(status, 200, replayed)
            assert replayed == original and replayed["status"] == "confirmed"

            swaps = []
            for day, table in (("2027-01-05", "t_2"), ("2027-01-05", "t_3")):
                request_body = {"restaurant_id": "r_anker", "table_id": table,
                                "starts_at_local": f"{day}T19:00", "party_size": 4}
                status, reservation = call(base, "POST", "/reservations", request_body,
                                           token, f"booking-{table}")
                require(status, 201, reservation)
                swaps.append(reservation)
            swap_body = {"moves": [
                {"reference": swaps[0]["reference"], "table_id": "t_3"},
                {"reference": swaps[1]["reference"], "table_id": "t_2"}]}
            status, moved = call(base, "POST", "/reservation-moves", swap_body, token, "swap-1")
            require(status, 201, moved)
            assert [row["table_id"] for row in moved["reservations"]] == ["t_3", "t_2"]
            require(call(base, "POST", "/reservations/" + swaps[0]["reference"] + "/cancel",
                         token=token)[0], 200)
            status, replayed_move = call(base, "POST", "/reservation-moves",
                                         {"moves": list(swap_body["moves"])}, token, "swap-1")
            require(status, 200, replayed_move)
            assert replayed_move == moved

            rollback = []
            for table, party in (("t_1", 2), ("t_2", 4)):
                request_body = {"restaurant_id": "r_anker", "table_id": table,
                                "starts_at_local": "2027-01-06T19:00", "party_size": party}
                status, reservation = call(base, "POST", "/reservations", request_body,
                                           token, f"rollback-{table}")
                require(status, 201, reservation)
                rollback.append(reservation)
            conflict = {"moves": [
                {"reference": rollback[0]["reference"], "table_id": "t_2"},
                {"reference": rollback[1]["reference"], "table_id": "t_2"}]}
            status, error = call(base, "POST", "/reservation-moves", conflict, token, "rollback")
            require(status, 409, error)
            assert error["error"]["code"] == "table_unavailable"
            for reservation, expected in zip(rollback, ("t_1", "t_2")):
                status, current = call(base, "GET", "/reservations/" + reservation["reference"],
                                       token=token)
                require(status, 200, current)
                assert current["table_id"] == expected

            race_body = {"restaurant_id": "r_anker", "table_id": "t_1",
                         "starts_at_local": "2027-01-07T19:00", "party_size": 2}
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
                statuses = list(pool.map(
                    lambda i: call(base, "POST", "/reservations", race_body, token,
                                   f"race-{i}")[0], range(10)))
            assert statuses.count(201) == 1 and statuses.count(409) == 9, statuses

            reset = fixture(timezone="Europe/Berlin")
            reset["restaurants"][0]["opening_hours"] = [
                {"weekday": day, "opens": "00:00", "closes": "23:30"}
                for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")]
            require(call(base, "POST", "/_test/reset", reset)[0], 204)
            status, login = call(base, "POST", "/auth/login", {
                "email": "ada@example.com", "password": "correct horse"})
            require(status, 200, login)
            token = login["token"]
            params = "restaurant_id=r_anker&date=2026-10-25&party_size=4"
            status, availability = call(base, "GET", "/availability?" + params)
            require(status, 200, availability)
            times = [slot["starts_at_local"][-5:] for slot in availability["slots"]]
            assert times.count("02:00") == 1 and times.count("02:30") == 1
            fall_body = {"restaurant_id": "r_anker", "table_id": "t_2",
                         "starts_at_local": "2026-10-25T02:00", "party_size": 4}
            status, fall_booking = call(base, "POST", "/reservations", fall_body,
                                        token, "fall-back")
            require(status, 201, fall_booking)
            assert fall_booking["starts_at"].endswith("+02:00")
            spring = {"restaurant_id": "r_anker", "table_id": "t_2",
                      "starts_at_local": "2026-03-29T02:30", "party_size": 4}
            status, spring_error = call(base, "POST", "/reservations", spring,
                                        token, "spring-gap")
            require(status, 422, spring_error)
            assert spring_error["error"]["code"] == "invalid_local_time"

            status, snapshot = call(base, "GET", "/_test/export")
            require(status, 200, snapshot)
            assert "correct horse" not in json.dumps(snapshot)
            require(call(base, "POST", "/_test/reset", fixture(timezone="UTC", name="Other"))[0], 204)
            require(call(base, "POST", "/_test/import", snapshot)[0], 204)
            status, resumed = call(base, "GET", "/reservations/" + fall_booking["reference"],
                                   token=token)
            require(status, 200, resumed)
            assert resumed == fall_booking
            status, receipt = call(base, "POST", "/reservations", fall_body, token, "fall-back")
            require(status, 200, receipt)
            assert receipt == fall_booking
            invalid_snapshot = {**snapshot, "track": "wrong"}
            status, failure = call(base, "POST", "/_test/import", invalid_snapshot)
            require(status, 422, failure)
            assert call(base, "GET", "/restaurants")[1]["restaurants"][0]["name"] == "Zum Anker"
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()

    print("Stage 1 backend checks passed: auth, replay, interval, atomic moves, concurrency, DST, export/import.")


if __name__ == "__main__":
    main()
