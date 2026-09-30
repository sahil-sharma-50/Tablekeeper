from __future__ import annotations

import copy
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
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
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
STAGE1_ROOT = ROOT.parent / "stage-1"
JSON_CONTENT_TYPE = "application/json; charset=utf-8"
COMBINABLE = [["t_1", "t_2"], ["t_2", "t_3"]]


def call(base, method, path, body=None, token=None, key=None):
    headers = {}
    if body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if key is not None:
        headers["Idempotency-Key"] = key
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        response = urllib.request.urlopen(req, timeout=4)
    except urllib.error.HTTPError as exc:
        response = exc
    except urllib.error.URLError as exc:
        raise AssertionError(f"{method} {path} transport error: {exc.reason}") from exc
    raw = response.read()
    content_type = response.headers.get("Content-Type", "")
    payload = json.loads(raw) if raw and content_type.startswith("application/json") else raw
    return response.status, payload, response.headers


def json_call(base, method, path, expected, body=None, token=None, key=None):
    status, payload, headers = call(base, method, path, body, token, key)
    assert status == expected, f"{method} {path}: expected {expected}, got {status}: {payload}"
    assert headers.get("Content-Type") == JSON_CONTENT_TYPE, headers
    return payload


def empty_call(base, method, path, body=None, token=None):
    status, payload, headers = call(base, method, path, body, token)
    assert status == 204 and payload == b"", (status, payload)
    assert headers.get("Content-Type") is None, headers


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_server(root, port, db_path, static_dir=None):
    env = os.environ.copy()
    env["TABLEKEEPER_DB"] = str(db_path)
    env["PYTHONTZPATH"] = ""
    if static_dir is not None:
        env["TABLEKEEPER_STATIC"] = str(static_dir)
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1",
         "--port", str(port), "--no-access-log"],
        cwd=root, env=env, stdout=sys.stderr, stderr=sys.stderr)


def wait_ready(base, process):
    for _ in range(100):
        if process.poll() is not None:
            raise AssertionError("Uvicorn exited before becoming healthy")
        try:
            status, payload, headers = call(base, "GET", "/health")
            if (status == 200 and payload == {"status": "ok"} and
                    headers.get("Content-Type") == JSON_CONTENT_TYPE):
                return
        except (OSError, urllib.error.URLError, AssertionError):
            pass
        time.sleep(0.1)
    raise AssertionError("service did not become healthy")


def fixture(combinable=None):
    restaurant = {
        "id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin",
        "slot_minutes": 30, "reservation_duration_minutes": 90,
        "cancellation_cutoff_minutes": 120,
        "opening_hours": [{"weekday": day, "opens": "18:00", "closes": "23:00"}
                          for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")],
        "tables": [{"id": "t_1", "label": "1", "capacity": 2},
                   {"id": "t_2", "label": "2", "capacity": 4},
                   {"id": "t_3", "label": "3", "capacity": 6}],
    }
    if combinable is not None:
        restaurant["combinable"] = combinable
    return {
        "users": [{"id": "u_ada", "email": "ada@example.com",
                   "password": "correct horse", "display_name": "Ada"}],
        "restaurants": [restaurant], "reservations": [],
    }


def future_date(offset=8):
    today = dt.datetime.now(ZoneInfo("Europe/Berlin")).date()
    return (today + dt.timedelta(days=offset)).isoformat()


def main():
    with tempfile.TemporaryDirectory(prefix="tablekeeper-stage2-check-") as temporary:
        temp = Path(temporary)
        static_dir = temp / "static"
        assets_dir = static_dir / "assets"
        assets_dir.mkdir(parents=True)
        html = ("<!doctype html><html><head><title>Stage 2 check</title></head>"
                "<body><main id=app></main><script src='/assets/app.js'></script></body></html>")
        (static_dir / "index.html").write_text(html, encoding="utf-8")
        (assets_dir / "app.js").write_text("window.stage2Check = true;", encoding="utf-8")

        stage1_port, stage2_port = free_port(), free_port()
        stage1_base = f"http://127.0.0.1:{stage1_port}"
        stage2_base = f"http://127.0.0.1:{stage2_port}"
        stage1 = start_server(STAGE1_ROOT, stage1_port, temp / "stage1.sqlite3")
        stage2 = start_server(ROOT, stage2_port, temp / "stage2.sqlite3", static_dir)
        try:
            wait_ready(stage1_base, stage1)
            wait_ready(stage2_base, stage2)
            day = future_date()

            empty_call(stage1_base, "POST", "/_test/reset", fixture())
            login = json_call(stage1_base, "POST", "/auth/login", 200,
                              {"email": "ada@example.com", "password": "correct horse"})
            token = login["token"]
            old_body = {"restaurant_id": "r_anker", "table_id": "t_1",
                        "starts_at_local": f"{day}T19:00", "party_size": 2}
            original = json_call(stage1_base, "POST", "/reservations", 201,
                                 old_body, token, "stage1-original")
            move_body = {"moves": [{"reference": original["reference"], "table_id": "t_2"}]}
            original_move = json_call(stage1_base, "POST", "/reservation-moves", 201,
                                      move_body, token, "stage1-move")
            snapshot = json_call(stage1_base, "GET", "/_test/export", 200)
            assert "table_ids" not in original
            assert "table_ids" not in original_move["reservations"][0]

            empty_call(stage2_base, "POST", "/_test/import", snapshot)
            imported = json_call(stage2_base, "GET", "/reservations", 200, token=token)
            old_row = imported["reservations"][0]
            assert old_row["reference"] == original["reference"]
            assert old_row["reservation_id"] == original["reservation_id"]
            assert old_row["table_ids"] == ["t_2"] and old_row["table_id"] == "t_2"
            old_replay = json_call(stage2_base, "POST", "/reservations", 200,
                                   old_body, token, "stage1-original")
            assert old_replay == original
            old_move_replay = json_call(stage2_base, "POST", "/reservation-moves", 200,
                                        move_body, token, "stage1-move")
            assert old_move_replay == original_move

            upgraded = copy.deepcopy(snapshot)
            upgraded["state"]["restaurants"][0]["combinable"] = COMBINABLE
            empty_call(stage2_base, "POST", "/_test/import", upgraded)
            imported = json_call(stage2_base, "GET", "/reservations", 200, token=token)
            assert imported["reservations"][0]["reference"] == original["reference"]
            assert imported["reservations"][0]["table_ids"] == ["t_2"]
            assert json_call(stage2_base, "GET", "/restaurants/r_anker", 200)["combinable"] == COMBINABLE
            old_replay = json_call(stage2_base, "POST", "/reservations", 200,
                                   old_body, token, "stage1-original")
            assert old_replay == original
            old_move_replay = json_call(stage2_base, "POST", "/reservation-moves", 200,
                                        move_body, token, "stage1-move")
            assert old_move_replay == original_move

            query = urllib.parse.urlencode({"restaurant_id": "r_anker", "date": day,
                                            "party_size": 6})
            availability = json_call(stage2_base, "GET", f"/availability?{query}", 200)
            at_nine = next(slot for slot in availability["slots"]
                           if slot["starts_at_local"].endswith("T21:00"))
            assert at_nine["available_table_ids"] == ["t_3"]
            assert at_nine["available_options"] == [
                {"table_ids": ["t_3"], "capacity": 6},
                {"table_ids": ["t_1", "t_2"], "capacity": 6},
                {"table_ids": ["t_2", "t_3"], "capacity": 10},
            ]

            pair_body = {"restaurant_id": "r_anker", "table_ids": ["t_2", "t_1"],
                         "starts_at_local": f"{day}T21:00", "party_size": 6}
            pair = json_call(stage2_base, "POST", "/reservations", 201,
                             pair_body, token, "pair-create")
            assert pair["table_ids"] == ["t_1", "t_2"] and "table_id" not in pair
            assert json_call(stage2_base, "POST", "/reservations", 200,
                             pair_body, token, "pair-create") == pair
            query = urllib.parse.urlencode({"restaurant_id": "r_anker", "date": day,
                                            "party_size": 2})
            availability = json_call(stage2_base, "GET", f"/availability?{query}", 200)
            at_nine = next(slot for slot in availability["slots"]
                           if slot["starts_at_local"].endswith("T21:00"))
            assert at_nine["available_table_ids"] == ["t_3"]
            assert at_nine["available_options"] == [{"table_ids": ["t_3"], "capacity": 6}]

            bad_cases = [
                ({"table_ids": ["t_1", "t_3"]}, "combination_not_allowed"),
                ({"table_ids": ["t_1", "t_2", "t_3"]}, "combination_not_allowed"),
                ({"table_ids": ["t_1", "t_1"]}, "validation_failed"),
                ({"table_id": "t_1", "table_ids": ["t_1"]}, "validation_failed"),
                ({"table_ids": ["t_1", "t_2"], "party_size": 7}, "party_exceeds_capacity"),
            ]
            for index, (selection, code) in enumerate(bad_cases):
                body = {"restaurant_id": "r_anker", "starts_at_local": f"{day}T21:00",
                        "party_size": 2, **selection}
                if "party_size" in selection:
                    body["party_size"] = selection["party_size"]
                result = json_call(stage2_base, "POST", "/reservations", 422,
                                   body, token, f"invalid-pair-{index}")
                assert result["error"]["code"] == code, result
            unavailable = json_call(stage2_base, "POST", "/reservations", 409,
                                    {"restaurant_id": "r_anker", "table_id": "t_1",
                                     "starts_at_local": f"{day}T21:00", "party_size": 2},
                                    token, "pair-blocks-single")
            assert unavailable["error"]["code"] == "table_unavailable"
            cancelled_pair = json_call(stage2_base, "POST",
                                       f"/reservations/{pair['reference']}/cancel", 200,
                                       token=token)
            assert cancelled_pair["table_ids"] == ["t_1", "t_2"]

            patch_source = json_call(stage2_base, "POST", "/reservations", 201,
                                     {"restaurant_id": "r_anker", "table_id": "t_3",
                                      "starts_at_local": f"{day}T20:30", "party_size": 4},
                                     token, "patch-source")
            patched = json_call(stage2_base, "PATCH",
                                f"/reservations/{patch_source['reference']}", 200,
                                {"table_ids": ["t_2", "t_1"]}, token)
            assert patched["table_ids"] == ["t_1", "t_2"] and "table_id" not in patched
            patched = json_call(stage2_base, "PATCH",
                                f"/reservations/{patch_source['reference']}", 200,
                                {"table_ids": ["t_3"]}, token)
            assert patched["table_ids"] == ["t_3"] and patched["table_id"] == "t_3"

            other_day = future_date(9)
            first = json_call(stage2_base, "POST", "/reservations", 201,
                              {"restaurant_id": "r_anker", "table_id": "t_1",
                               "starts_at_local": f"{other_day}T19:00", "party_size": 2},
                              token, "move-first")
            second = json_call(stage2_base, "POST", "/reservations", 201,
                               {"restaurant_id": "r_anker", "table_id": "t_3",
                                "starts_at_local": f"{other_day}T19:00", "party_size": 2},
                               token, "move-second")
            conflict = json_call(stage2_base, "POST", "/reservation-moves", 409,
                                 {"moves": [
                                     {"reference": first["reference"],
                                      "table_ids": ["t_1", "t_2"]},
                                     {"reference": second["reference"], "table_id": "t_2"},
                                 ]}, token, "pair-move-conflict")
            assert conflict["error"]["code"] == "table_unavailable"
            unchanged_first = json_call(stage2_base, "GET",
                                        f"/reservations/{first['reference']}", 200, token=token)
            unchanged_second = json_call(stage2_base, "GET",
                                         f"/reservations/{second['reference']}", 200, token=token)
            assert unchanged_first["table_ids"] == ["t_1"]
            assert unchanged_second["table_ids"] == ["t_3"]
            move_body = {"moves": [{"reference": first["reference"],
                                     "table_ids": ["t_2", "t_1"]}]}
            moved = json_call(stage2_base, "POST", "/reservation-moves", 201,
                              move_body, token, "pair-move-success")
            assert moved["reservations"][0]["table_ids"] == ["t_1", "t_2"]
            assert "table_id" not in moved["reservations"][0]
            assert json_call(stage2_base, "POST", "/reservation-moves", 200,
                             move_body, token, "pair-move-success") == moved

            concurrent_body = {"restaurant_id": "r_anker", "table_ids": ["t_1", "t_2"],
                               "starts_at_local": f"{future_date(10)}T19:00", "party_size": 6}
            def concurrent_create(_):
                return call(stage2_base, "POST", "/reservations", concurrent_body, token,
                            "pair-concurrent-key")
            with ThreadPoolExecutor(max_workers=8) as pool:
                concurrent_results = list(pool.map(concurrent_create, range(16)))
            assert [status for status, _, _ in concurrent_results].count(201) == 1
            assert [status for status, _, _ in concurrent_results].count(200) == 15
            assert all(payload == concurrent_results[0][1]
                       for _, payload, _ in concurrent_results)
            changed_replay = json_call(stage2_base, "POST", "/reservations", 409,
                                       {**concurrent_body, "party_size": 5}, token,
                                       "pair-concurrent-key")
            assert changed_replay["error"]["code"] == "idempotency_key_reuse"

            for route in ("/", "/signup", "/login", "/lookup"):
                status, payload, headers = call(stage2_base, "GET", route)
                assert status == 200 and payload.decode("utf-8") == html
                assert headers.get("Content-Type") == "text/html; charset=utf-8", headers
            status, asset, headers = call(stage2_base, "GET", "/assets/app.js")
            assert status == 200 and asset == b"window.stage2Check = true;"
            assert headers.get("Content-Type", "").startswith("text/")
            status, missing, headers = call(stage2_base, "GET", "/no-such-path")
            assert status == 404 and headers.get("Content-Type") == JSON_CONTENT_TYPE
            assert missing["error"]["code"] == "not_found"
            status, _, headers = call(stage2_base, "GET", "/docs")
            assert status == 200 and headers.get("Content-Type") == "text/html; charset=utf-8"
        finally:
            for process in (stage2, stage1):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

    print("Stage 2 checks passed: populated Stage 1 import, pairs, availability, PATCH, moves, SPA routes/assets.")


if __name__ == "__main__":
    main()
