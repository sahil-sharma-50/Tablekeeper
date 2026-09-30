from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException


class ApiJSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


UTC = dt.timezone.utc
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
LOCAL_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}$")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
TIME_RE = re.compile(r"^[0-9]{2}:[0-9]{2}$")
REFERENCE_RE = re.compile(r"^[A-Z0-9]{6,12}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+$")
SALT_BYTES, HASH_BYTES = 16, 32
SCRYPT_N, SCRYPT_R, SCRYPT_P = 1 << 14, 8, 1


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def error(status: int, code: str, message: str) -> None:
    raise ApiError(status, code, message)


def invalid() -> None:
    error(422, "validation_failed", "The request does not satisfy the required fields.")


def malformed() -> None:
    error(400, "malformed_request", "The request body is malformed.")


def _reject_constant(value: str) -> None:
    raise ValueError(value)


def _finite_json(value: Any) -> bool:
    if isinstance(value, float):
        return value == value and abs(value) != float("inf")
    if isinstance(value, list):
        return all(_finite_json(item) for item in value)
    if isinstance(value, dict):
        return all(_finite_json(item) for item in value.values())
    return True


async def body_object(request: Request) -> dict[str, Any]:
    try:
        value = json.loads((await request.body()).decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        malformed()
    if not isinstance(value, dict) or not _finite_json(value):
        malformed()
    return value


def required(obj: dict[str, Any], key: str) -> Any:
    if key not in obj:
        invalid()
    return obj[key]


def string_value(value: Any) -> str:
    if not isinstance(value, str):
        malformed()
    return value


def identifier(value: Any) -> str:
    value = string_value(value)
    if not value or len(value) > 64:
        invalid()
    return value


def integer_value(value: Any, minimum: int, maximum: int | None = None) -> int:
    if type(value) is not int:
        malformed()
    if value < minimum or (maximum is not None and value > maximum):
        invalid()
    return value


def party_size_value(value: Any) -> int:
    if type(value) is not int or value < 1:
        invalid()
    return value


def email_value(value: Any) -> str:
    value = string_value(value)
    if not EMAIL_RE.fullmatch(value):
        invalid()
    return value


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N,
                            r=SCRYPT_R, p=SCRYPT_P, dklen=HASH_BYTES)
    return "$".join(("scrypt", str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P),
                     salt.hex(), digest.hex()))


def _password_matches(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = encoded.split("$")
        if scheme != "scrypt":
            return False
        salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n),
                                r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, OverflowError):
        return False


def _valid_password_hash(encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = encoded.split("$")
        return (scheme == "scrypt" and int(n) == SCRYPT_N and int(r) == SCRYPT_R and
                int(p) == SCRYPT_P and len(bytes.fromhex(salt_hex)) == SALT_BYTES and
                len(bytes.fromhex(digest_hex)) == HASH_BYTES)
    except (ValueError, TypeError):
        return False


def _empty_state() -> dict[str, Any]:
    return {"version": 1, "users": [], "tokens": {}, "restaurants": [],
            "reservations": [], "receipts": [], "series": [], "plans": []}


_DB_PATH = os.environ.get("TABLEKEEPER_DB", "/tmp/tablekeeper.sqlite3")
os.makedirs(os.path.dirname(os.path.abspath(_DB_PATH)), mode=0o700, exist_ok=True)
# ponytail: global lock; per-account locks only if throughput demands it.
_LOCK = threading.RLock()
_DB = sqlite3.connect(_DB_PATH, timeout=10, check_same_thread=False,
                      isolation_level=None)
_DB.execute("CREATE TABLE IF NOT EXISTS service_state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)")
if _DB.execute("SELECT 1 FROM service_state WHERE id=1").fetchone() is None:
    _DB.execute("INSERT INTO service_state(id, body) VALUES(1, ?)",
                (json.dumps(_empty_state(), separators=(",", ":")),))
try:
    os.chmod(_DB_PATH, 0o600)
except OSError:
    pass


def _load_state() -> dict[str, Any]:
    row = _DB.execute("SELECT body FROM service_state WHERE id=1").fetchone()
    if row is None:
        raise RuntimeError("state row missing")
    return json.loads(row[0])


def read_state() -> dict[str, Any]:
    with _LOCK:
        return _load_state()


def transaction(change: Callable[[dict[str, Any]], Any]) -> Any:
    with _LOCK:
        _DB.execute("BEGIN IMMEDIATE")
        try:
            state = _load_state()
            result = change(state)
            payload = json.dumps(state, ensure_ascii=False, separators=(",", ":"),
                                 allow_nan=False)
            _DB.execute("UPDATE service_state SET body=? WHERE id=1", (payload,))
            _DB.commit()
            return result
        except BaseException:
            _DB.rollback()
            raise


def authorization_token(request: Request) -> str:
    parts = request.headers.get("authorization", "").split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        error(401, "unauthenticated", "A valid bearer token is required.")
    return parts[1]


def user_id_for(state: dict[str, Any], request: Request) -> str:
    uid = state["tokens"].get(authorization_token(request))
    if uid is None:
        error(401, "unauthenticated", "A valid bearer token is required.")
    return uid


def idempotency_key(request: Request) -> str:
    key = request.headers.get("idempotency-key")
    if key is None or key == "":
        error(400, "missing_idempotency_key", "Idempotency-Key is required.")
    if not 1 <= len(key) <= 255:
        invalid()
    return key


def same_json_value(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            same_json_value(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(
            same_json_value(a, b) for a, b in zip(left, right))
    return left == right


def replay(state: dict[str, Any], uid: str, path: str, key: str,
           body: dict[str, Any]) -> dict[str, Any] | None:
    for receipt in state["receipts"]:
        if (receipt["user_id"], receipt["path"], receipt["key"]) == (uid, path, key):
            if not same_json_value(receipt["body"], body):
                error(409, "idempotency_key_reuse", "This key belongs to a different request.")
            return receipt["response"]
    return None


def record_receipt(state: dict[str, Any], uid: str, path: str, key: str,
                   body: dict[str, Any], response: dict[str, Any]) -> None:
    state["receipts"].append({"user_id": uid, "method": "POST", "path": path,
                              "key": key, "body": body, "response": response})


def _parse_date(value: str) -> dt.date:
    if not DATE_RE.fullmatch(value):
        invalid()
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        invalid()


def _parse_local(value: Any) -> dt.datetime:
    if not isinstance(value, str):
        malformed()
    if not LOCAL_RE.fullmatch(value):
        invalid()
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except ValueError:
        invalid()


def _minute(value: Any) -> int:
    if not isinstance(value, str):
        malformed()
    if not TIME_RE.fullmatch(value):
        invalid()
    hour, minute = (int(part) for part in value.split(":"))
    if hour > 23 or minute > 59:
        invalid()
    return hour * 60 + minute


def _hours(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        malformed()
    result, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            malformed()
        weekday = string_value(required(item, "weekday"))
        opens = string_value(required(item, "opens"))
        closes = string_value(required(item, "closes"))
        if weekday not in WEEKDAYS or weekday in seen:
            invalid()
        if _minute(closes) <= _minute(opens):
            invalid()
        seen.add(weekday)
        result.append({"weekday": weekday, "opens": opens, "closes": closes})
    return result


def _restaurant(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        malformed()
    rid = identifier(required(raw, "id"))
    name = string_value(required(raw, "name"))
    timezone = string_value(required(raw, "timezone"))
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        invalid()
    slot = integer_value(required(raw, "slot_minutes"), 1, 1440)
    duration = integer_value(required(raw, "reservation_duration_minutes"), 1, 1440)
    cutoff = integer_value(required(raw, "cancellation_cutoff_minutes"), 0)
    opening_hours = _hours(required(raw, "opening_hours"))
    raw_tables = required(raw, "tables")
    if not isinstance(raw_tables, list):
        malformed()
    tables, seen = [], set()
    for raw_table in raw_tables:
        if not isinstance(raw_table, dict):
            malformed()
        tid = identifier(required(raw_table, "id"))
        label = string_value(required(raw_table, "label"))
        capacity = integer_value(required(raw_table, "capacity"), 1)
        if tid in seen:
            invalid()
        seen.add(tid)
        tables.append({"id": tid, "label": label, "capacity": capacity})
    raw_pairs = raw.get("combinable", [])
    if not isinstance(raw_pairs, list):
        malformed()
    combinable, pair_keys = [], set()
    for raw_pair in raw_pairs:
        if not isinstance(raw_pair, list):
            malformed()
        if len(raw_pair) != 2:
            invalid()
        pair = [identifier(value) for value in raw_pair]
        pair_key = frozenset(pair)
        if len(pair_key) != 2 or not pair_key.issubset(seen) or pair_key in pair_keys:
            invalid()
        pair_keys.add(pair_key)
        combinable.append(pair)
    managers = raw.get("manager_user_ids", [])
    if not isinstance(managers, list):
        malformed()
    managers = [identifier(value) for value in managers]
    if len(set(managers)) != len(managers):
        invalid()
    result = {"id": rid, "name": name, "timezone": timezone,
              "slot_minutes": slot, "reservation_duration_minutes": duration,
              "cancellation_cutoff_minutes": cutoff,
              "opening_hours": opening_hours, "tables": tables,
              "combinable": combinable}
    if "manager_user_ids" in raw:
        result["manager_user_ids"] = managers
    return result


def _fixture(root: dict[str, Any]) -> dict[str, Any]:
    users_raw = required(root, "users")
    restaurants_raw = required(root, "restaurants")
    reservations_raw = required(root, "reservations")
    if not all(isinstance(value, list)
               for value in (users_raw, restaurants_raw, reservations_raw)):
        malformed()

    users, user_ids, emails = [], set(), set()
    for item in users_raw:
        if not isinstance(item, dict):
            malformed()
        uid = identifier(required(item, "id"))
        email = email_value(required(item, "email"))
        password = string_value(required(item, "password"))
        display_name = string_value(required(item, "display_name"))
        if uid in user_ids or email in emails:
            invalid()
        user_ids.add(uid)
        emails.add(email)
        users.append({"id": uid, "email": email, "password_hash": _hash_password(password),
                      "display_name": display_name})

    restaurants = [_restaurant(item) for item in restaurants_raw]
    if len({item["id"] for item in restaurants}) != len(restaurants):
        invalid()
    for restaurant in restaurants:
        if not set(restaurant.get("manager_user_ids", [])).issubset(user_ids):
            invalid()
        restaurant.update({"policies": [], "restaurant_revision": 0, "closures": []})
    state = {"version": 1, "users": users, "tokens": {}, "restaurants": restaurants,
             "reservations": [], "receipts": [], "series": [], "plans": []}
    for item in reservations_raw:
        if not isinstance(item, dict):
            malformed()
        res_id = identifier(required(item, "id"))
        reference = string_value(required(item, "reference"))
        uid = identifier(required(item, "user_id"))
        rid = identifier(required(item, "restaurant_id"))
        raw_table_ids = _requested_table_ids(item)
        start_local = string_value(required(item, "starts_at_local"))
        party = party_size_value(required(item, "party_size"))
        if not REFERENCE_RE.fullmatch(reference) or uid not in user_ids:
            invalid()
        try:
            fields = booking_fields(state, rid, raw_table_ids, start_local, party)
        except ApiError:
            invalid()
        status = item.get("status", "confirmed")
        if status not in ("confirmed", "cancelled"):
            invalid()
        reservation = {"reservation_id": res_id, "reference": reference, "user_id": uid,
                       "restaurant_id": rid, "party_size": party,
                       "status": status, **fields, "created_at": utc_now()}
        _set_reservation_tables(reservation, fields["table_ids"])
        reservation["revision"] = 1
        reservation["history"] = []
        _record_history(reservation, "created", _creation_changes(reservation),
                        reservation["created_at"])
        if any(row["reservation_id"] == res_id or row["reference"] == reference
               for row in state["reservations"]):
            invalid()
        if status == "confirmed" and not free_for(state, reservation):
            invalid()
        state["reservations"].append(reservation)
    return state


def restaurant_by_id(state: dict[str, Any], rid: str) -> dict[str, Any]:
    for restaurant in state["restaurants"]:
        if restaurant["id"] == rid:
            return restaurant if "combinable" in restaurant else {
                **restaurant, "combinable": []}
    error(404, "not_found", "Restaurant not found.")


def table_by_id(restaurant: dict[str, Any], tid: str) -> dict[str, Any]:
    for table in restaurant["tables"]:
        if table["id"] == tid:
            return table
    error(404, "not_found", "Table not found.")


def _requested_table_ids(obj: dict[str, Any], fallback: list[str] | None = None) -> Any:
    if "table_id" in obj and "table_ids" in obj:
        invalid()
    if "table_ids" in obj:
        if not isinstance(obj["table_ids"], list):
            malformed()
        return obj["table_ids"]
    if "table_id" in obj:
        return [obj["table_id"]]
    if fallback is not None:
        return list(fallback)
    return [required(obj, "table_id")]


def _canonical_table_ids(restaurant: dict[str, Any], raw_ids: Any) -> list[str]:
    if not isinstance(raw_ids, list):
        malformed()
    if not 1 <= len(raw_ids) <= 2:
        error(422, "combination_not_allowed", "Only one table or a declared pair can be selected.")
    table_ids = [identifier(value) for value in raw_ids]
    if len(set(table_ids)) != len(table_ids):
        invalid()
    for table_id in table_ids:
        table_by_id(restaurant, table_id)
    if len(table_ids) == 1:
        return table_ids
    for pair in restaurant.get("combinable", []):
        if set(pair) == set(table_ids):
            return list(pair)
    error(422, "combination_not_allowed", "Those tables are not a declared pair.")


def _reservation_table_ids(reservation: dict[str, Any]) -> list[str]:
    if "table_ids" in reservation:
        return reservation["table_ids"]
    return [reservation["table_id"]]


def _table_fields(table_ids: list[str]) -> dict[str, Any]:
    fields: dict[str, Any] = {"table_ids": list(table_ids)}
    if len(table_ids) == 1:
        fields["table_id"] = table_ids[0]
    return fields


def _set_reservation_tables(reservation: dict[str, Any], table_ids: list[str]) -> None:
    reservation.pop("table_id", None)
    reservation.update(_table_fields(table_ids))


def _policy0(restaurant: dict[str, Any]) -> dict[str, Any]:
    return {"policy_version": 0, "slot_minutes": restaurant["slot_minutes"],
            "reservation_duration_minutes": restaurant["reservation_duration_minutes"],
            "cancellation_cutoff_minutes": restaurant["cancellation_cutoff_minutes"],
            "opening_hours": restaurant["opening_hours"],
            "capacities": {table["id"]: table["capacity"]
                           for table in restaurant["tables"]}}


def _policy_terms(policy: dict[str, Any]) -> dict[str, Any]:
    return {"policy_version": policy["policy_version"],
            "slot_minutes": policy["slot_minutes"],
            "reservation_duration_minutes": policy["reservation_duration_minutes"],
            "cancellation_cutoff_minutes": policy["cancellation_cutoff_minutes"],
            "opening_hours": [dict(item) for item in policy["opening_hours"]],
            "capacities": dict(policy["capacities"])}


def _policy_for_date(restaurant: dict[str, Any], date: dt.date) -> dict[str, Any]:
    applicable = [policy for policy in restaurant.get("policies", [])
                  if policy["effective_from"] <= date.isoformat()]
    return max(applicable, key=lambda policy: (policy["effective_from"],
                                                policy["policy_version"])) \
        if applicable else _policy0(restaurant)


def _policy_payload(body: dict[str, Any], restaurant: dict[str, Any]) -> dict[str, Any]:
    effective = body.get("effective_from")
    if not isinstance(effective, str):
        invalid()
    try:
        _parse_date(effective)
    except ApiError:
        invalid()
    values = {}
    for name, minimum, maximum in (
            ("slot_minutes", 1, 1440),
            ("reservation_duration_minutes", 1, 1440),
            ("cancellation_cutoff_minutes", 0, 10080)):
        value = body.get(name)
        if type(value) is not int or not minimum <= value <= maximum:
            invalid()
        values[name] = value
    try:
        hours = _hours(body.get("opening_hours"))
    except ApiError:
        invalid()
    capacities = body.get("capacities")
    table_ids = {table["id"] for table in restaurant["tables"]}
    if (not isinstance(capacities, dict) or set(capacities) != table_ids or
            any(type(value) is not int or not 1 <= value <= 100
                for value in capacities.values())):
        invalid()
    return {"effective_from": effective, **values, "opening_hours": hours,
            "capacities": dict(capacities)}


def _valid_terms(terms: Any, restaurant: dict[str, Any]) -> bool:
    if not isinstance(terms, dict) or set(terms) != {
            "policy_version", "slot_minutes", "reservation_duration_minutes",
            "cancellation_cutoff_minutes", "opening_hours", "capacities"}:
        return False
    version = terms.get("policy_version")
    if type(version) is not int or version < 0:
        return False
    maximum_cutoff = 10080 if version else None
    if (type(terms.get("slot_minutes")) is not int or
            not 1 <= terms["slot_minutes"] <= 1440 or
            type(terms.get("reservation_duration_minutes")) is not int or
            not 1 <= terms["reservation_duration_minutes"] <= 1440 or
            type(terms.get("cancellation_cutoff_minutes")) is not int or
            terms["cancellation_cutoff_minutes"] < 0 or
            (maximum_cutoff is not None and
             terms["cancellation_cutoff_minutes"] > maximum_cutoff)):
        return False
    try:
        if _hours(terms["opening_hours"]) != terms["opening_hours"]:
            return False
    except (ApiError, TypeError):
        return False
    capacities = terms["capacities"]
    table_ids = {table["id"] for table in restaurant["tables"]}
    if (not isinstance(capacities, dict) or set(capacities) != table_ids or
            any(type(value) is not int or value < 1 or
                (version > 0 and value > 100) for value in capacities.values())):
        return False
    return True


def _resolve_local(value: dt.datetime, timezone: str) -> dt.datetime:
    zone = ZoneInfo(timezone)
    candidate = value.replace(tzinfo=zone, fold=0)
    if candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != value:
        error(422, "invalid_local_time", "That local time does not exist.")
    return candidate


def _iso(value: dt.datetime) -> str:
    return value.isoformat(timespec="seconds")


def utc_now() -> str:
    return _iso(dt.datetime.now(UTC))


def booking_fields(state: dict[str, Any], rid: str, table_ids: Any,
                   starts_at_local: str, party: int) -> dict[str, Any]:
    restaurant = restaurant_by_id(state, rid)
    table_ids = _canonical_table_ids(restaurant, table_ids)
    local = _parse_local(starts_at_local)
    start = _resolve_local(local, restaurant["timezone"])
    policy = _policy_for_date(restaurant, local.date())
    weekday = WEEKDAYS[local.weekday()]
    hours = next((item for item in policy["opening_hours"]
                  if item["weekday"] == weekday), None)
    minute = local.hour * 60 + local.minute
    duration = policy["reservation_duration_minutes"]
    if hours is None:
        error(422, "outside_opening_hours", "The restaurant is closed then.")
    opening, closing = _minute(hours["opens"]), _minute(hours["closes"])
    if minute < opening or minute + duration > closing:
        error(422, "outside_opening_hours", "The reservation does not fit opening hours.")
    if (minute - opening) % policy["slot_minutes"]:
        error(422, "not_on_slot_grid", "The start is not on the reservation grid.")
    capacity = sum(policy["capacities"][table_id] for table_id in table_ids)
    if party > capacity:
        error(422, "party_exceeds_capacity", "The party is larger than the selected tables' capacity.")
    end = (start.astimezone(UTC) + dt.timedelta(minutes=duration)).astimezone(
        ZoneInfo(restaurant["timezone"]))
    return {"table_ids": table_ids, "starts_at_local": starts_at_local,
            "starts_at": _iso(start), "ends_at": _iso(end),
            "accepted_terms": _policy_terms(policy)}


def _instant(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must have an offset")
    return parsed.astimezone(UTC)


def overlaps(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (_instant(left["starts_at"]) < _instant(right["ends_at"]) and
            _instant(right["starts_at"]) < _instant(left["ends_at"]))


def free_for(state: dict[str, Any], candidate: dict[str, Any],
             ignored_references: set[str] | None = None) -> bool:
    ignored_references = ignored_references or set()
    candidate_tables = set(_reservation_table_ids(candidate))
    if any(
        current["status"] == "confirmed" and current["reference"] not in ignored_references and
        current["restaurant_id"] == candidate["restaurant_id"] and
        candidate_tables.intersection(_reservation_table_ids(current)) and overlaps(candidate, current)
        for current in state["reservations"]):
        return False
    restaurant = restaurant_by_id(state, candidate["restaurant_id"])
    return not any(
        candidate_tables.intersection({closure["table_id"]}) and
        _instant(candidate["starts_at"]) < _instant(closure["to"]) and
        _instant(closure["from"]) < _instant(candidate["ends_at"])
        for closure in restaurant.get("closures", []))


def public_reservation(reservation: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in reservation.items()
              if key not in ("user_id", "table_id", "table_ids", "history")}
    result.update(_table_fields(_reservation_table_ids(reservation)))
    return result


def _creation_changes(reservation: dict[str, Any]) -> list[dict[str, Any]]:
    table_ids = _reservation_table_ids(reservation)
    field = "table_ids" if len(table_ids) > 1 else "table_id"
    value: Any = table_ids if len(table_ids) > 1 else table_ids[0]
    return ([{"field": field, "from": None, "to": value},
             {"field": "starts_at_local", "from": None,
              "to": reservation["starts_at_local"]},
             {"field": "party_size", "from": None, "to": reservation["party_size"]}])


def _changed_fields(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    before_ids, after_ids = _reservation_table_ids(before), _reservation_table_ids(after)
    changes = []
    if before_ids != after_ids:
        if len(before_ids) > 1 or len(after_ids) > 1:
            field, old, new = "table_ids", before_ids, after_ids
        else:
            field, old, new = "table_id", before_ids[0], after_ids[0]
        changes.append({"field": field, "from": old, "to": new})
    for field in ("starts_at_local", "party_size"):
        if before[field] != after[field]:
            changes.append({"field": field, "from": before[field], "to": after[field]})
    return changes


def _record_history(reservation: dict[str, Any], event: str,
                    changes: list[dict[str, Any]], at: str | None = None,
                    plan_id: str | None = None) -> None:
    entry = {
        "seq": len(reservation.get("history", [])) + 1,
        "at": at or utc_now(), "event": event, "changes": changes,
        "revision": reservation["revision"],
        "accepted_terms": _policy_terms(reservation["accepted_terms"]),
    }
    if plan_id is not None:
        entry["plan_id"] = plan_id
    reservation.setdefault("history", []).append(entry)


def _check_expected_revision(body: dict[str, Any], current: dict[str, Any]) -> None:
    if "expected_revision" not in body:
        return
    expected = body["expected_revision"]
    if type(expected) is not int or expected < 1:
        invalid()
    if expected != current["revision"]:
        error(409, "stale_revision", "The reservation revision has changed.")


def _upgrade_import_state(state: dict[str, Any]) -> dict[str, Any]:
    state.setdefault("series", [])
    state.setdefault("plans", [])
    for restaurant in state["restaurants"]:
        restaurant.setdefault("combinable", [])
        restaurant.setdefault("policies", [])
        restaurant.setdefault("restaurant_revision", 0)
        restaurant.setdefault("closures", [])
    restaurants = {item["id"]: item for item in state["restaurants"]}
    for reservation in state["reservations"]:
        if "revision" not in reservation:
            reservation["revision"] = 1
            reservation["accepted_terms"] = _policy_terms(
                _policy0(restaurants[reservation["restaurant_id"]]))
            reservation["history"] = []
            _record_history(reservation, "created", _creation_changes(reservation),
                            reservation["created_at"])
    for series in state.get("series", []):
        if not isinstance(series, dict) or not isinstance(series.get("occurrences"), list):
            continue
        for index, occurrence in enumerate(series["occurrences"]):
            if not isinstance(occurrence, dict) or "scheduled_starts_at_local" in occurrence:
                continue
            try:
                occurrence["scheduled_starts_at_local"] = _series_scheduled_local(
                    state, series, index).strftime("%Y-%m-%dT%H:%M")
            except (ApiError, KeyError, IndexError, TypeError, ValueError, OverflowError):
                pass
    return state


def _private_owner_id(state: dict[str, Any], request: Request) -> str | None:
    parts = request.headers.get("authorization", "").split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return state["tokens"].get(parts[1])


def reservation_for_private_owner(state: dict[str, Any], reference: str,
                                  request: Request) -> dict[str, Any]:
    reservation = next((item for item in state["reservations"]
                        if item["reference"] == reference), None)
    if reservation is None or _private_owner_id(state, request) != reservation["user_id"]:
        error(404, "not_found", "Reservation not found.")
    return reservation


def _series_for_reference(state: dict[str, Any], reference: str):
    for series in state.get("series", []):
        for occurrence in series["occurrences"]:
            if occurrence["reference"] == reference:
                return series, occurrence
    return None


def _public_series(state: dict[str, Any], series: dict[str, Any]) -> dict[str, Any]:
    rows = {item["reference"]: item for item in state["reservations"]}
    return {"series_id": series["series_id"], "revision": series["revision"],
            "interval_weeks": series["interval_weeks"],
            "occurrences": [{"index": item["index"], "reference": item["reference"],
                             "exception": item["exception"],
                             "reservation": public_reservation(rows[item["reference"]])}
                            for item in series["occurrences"]]}


def _new_id(state: dict[str, Any], prefix: str, field: str) -> str:
    rows = state["users"] if field == "id" else state["reservations"]
    while True:
        value = prefix + secrets.token_hex(8)
        if not any(row.get(field) == value for row in rows):
            return value


def _new_reference(state: dict[str, Any]) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(8))
        if not any(row["reference"] == value for row in state["reservations"]):
            return value


def _new_series_id(state: dict[str, Any]) -> str:
    while True:
        value = "ser_" + secrets.token_urlsafe(12)
        if not any(row["series_id"] == value for row in state.get("series", [])):
            return value


def _new_plan_id(state: dict[str, Any]) -> str:
    while True:
        value = "plan_" + secrets.token_urlsafe(12)
        if not any(row["plan_id"] == value for row in state.get("plans", [])):
            return value


def _original_starts_at_local(reservation: dict[str, Any]) -> str:
    for entry in reservation.get("history", []):
        if entry.get("event") == "created":
            for change in entry.get("changes", []):
                if change.get("field") == "starts_at_local" and isinstance(change.get("to"), str):
                    return change["to"]
    return reservation["starts_at_local"]


def _series_origin_local(state: dict[str, Any], series: dict[str, Any]) -> dt.datetime:
    rows = {item["reference"]: item for item in state["reservations"]}
    first_generated = rows[series["occurrences"][1]["reference"]]
    generated_local = _parse_local(_original_starts_at_local(first_generated))
    return generated_local - dt.timedelta(weeks=series["interval_weeks"])


def _series_scheduled_local(state: dict[str, Any], series: dict[str, Any],
                            index: int) -> dt.datetime:
    occurrence = series["occurrences"][index]
    if isinstance(occurrence.get("scheduled_starts_at_local"), str):
        return _parse_local(occurrence["scheduled_starts_at_local"])
    rows = {item["reference"]: item for item in state["reservations"]}
    if index == 0:
        return _series_origin_local(state, series)
    return _parse_local(_original_starts_at_local(
        rows[occurrence["reference"]]))


def reservation_for_owner(state: dict[str, Any], reference: str, uid: str) -> dict[str, Any]:
    for reservation in state["reservations"]:
        if reservation["reference"] == reference:
            if reservation["user_id"] == uid:
                return reservation
            break
    error(404, "not_found", "Reservation not found.")


def _cutoff_passed(reservation: dict[str, Any], restaurant: dict[str, Any]) -> bool:
    delta = _instant(reservation["starts_at"]) - dt.datetime.now(UTC)
    delta_us = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
    cutoff = reservation.get("accepted_terms", {}).get(
        "cancellation_cutoff_minutes", restaurant["cancellation_cutoff_minutes"])
    return delta_us <= cutoff * 60 * 1_000_000


def _patch_inputs(body: dict[str, Any], current: dict[str, Any],
                  restaurant: dict[str, Any]) -> tuple[list[str], str, int]:
    table_ids = _canonical_table_ids(
        restaurant, _requested_table_ids(body, _reservation_table_ids(current)))
    start_local, party = current["starts_at_local"], current["party_size"]
    if "starts_at_local" in body:
        start_local = body["starts_at_local"]
        if not isinstance(start_local, str):
            malformed()
        _parse_local(start_local)
    if "party_size" in body:
        party = party_size_value(body["party_size"])
    return table_ids, start_local, party


def _validate_internal_state(state: Any) -> bool:
    if not isinstance(state, dict) or type(state.get("version")) is not int or state["version"] != 1:
        return False
    if any(not isinstance(state.get(key), list)
           for key in ("users", "restaurants", "reservations", "receipts")):
        return False
    if any(key in state and not isinstance(state[key], list)
           for key in ("series", "plans")):
        return False
    if not isinstance(state.get("tokens"), dict):
        return False
    users = state["users"]
    if any(not isinstance(user, dict) or not all(isinstance(user.get(key), str)
               for key in ("id", "email", "password_hash", "display_name"))
           for user in users):
        return False
    if any(not _valid_password_hash(user["password_hash"]) for user in users):
        return False
    user_ids = [user["id"] for user in users]
    if len(set(user_ids)) != len(user_ids) or len({
            user["email"] for user in users}) != len(users):
        return False
    user_ids = set(user_ids)
    for token, uid in state["tokens"].items():
        if not isinstance(token, str) or not token or not isinstance(uid, str) or uid not in user_ids:
            return False
    try:
        checked = [_restaurant(item) for item in state["restaurants"]]
    except (ApiError, TypeError, ValueError, ZoneInfoNotFoundError):
        return False
    if len({item["id"] for item in checked}) != len(checked):
        return False
    raw_restaurants = {item["id"]: item for item in state["restaurants"]}
    restaurants = {item["id"]: item for item in checked}
    for restaurant in restaurants.values():
        raw = raw_restaurants[restaurant["id"]]
        restaurant.update({key: raw[key] for key in
                           ("policies", "restaurant_revision", "closures") if key in raw})
        manager_ids = restaurant.get("manager_user_ids", [])
        if not set(manager_ids).issubset(user_ids):
            return False
        revision = raw.get("restaurant_revision", 0)
        if type(revision) is not int or revision < 0:
            return False
        policies = raw.get("policies", [])
        if not isinstance(policies, list):
            return False
        for index, policy in enumerate(policies, 1):
            if not isinstance(policy, dict) or type(policy.get("policy_version")) is not int or \
                    policy["policy_version"] != index:
                return False
            try:
                normalized = _policy_payload(policy, restaurant)
            except (ApiError, TypeError, ValueError):
                return False
            if any(policy.get(key) != value for key, value in normalized.items()):
                return False
            policy["opening_hours"] = normalized["opening_hours"]
        restaurant["policies"] = policies
        closures = raw.get("closures", [])
        if not isinstance(closures, list):
            return False
        for closure in closures:
            if (not isinstance(closure, dict) or
                    not isinstance(closure.get("table_id"), str) or
                    closure["table_id"] not in {table["id"] for table in restaurant["tables"]} or
                    not isinstance(closure.get("from"), str) or
                    not isinstance(closure.get("to"), str) or
                    not isinstance(closure.get("plan_id"), str) or not closure["plan_id"]):
                return False
            try:
                if _instant(closure["from"]) >= _instant(closure["to"]):
                    return False
            except (TypeError, ValueError):
                return False
        restaurant["closures"] = closures
    refs, ids = set(), set()
    for reservation in state["reservations"]:
        if not isinstance(reservation, dict) or not all(
                isinstance(reservation.get(key), str) for key in (
                    "reservation_id", "reference", "user_id", "restaurant_id",
                    "starts_at_local", "starts_at", "ends_at",
                    "created_at", "status")):
            return False
        if "table_ids" in reservation:
            table_ids = reservation["table_ids"]
            if not isinstance(table_ids, list) or not 1 <= len(table_ids) <= 2:
                return False
            if "table_id" in reservation and (
                    len(table_ids) != 1 or reservation["table_id"] != table_ids[0]):
                return False
        elif isinstance(reservation.get("table_id"), str):
            table_ids = [reservation["table_id"]]
        else:
            return False
        if (reservation["user_id"] not in user_ids or
                reservation["restaurant_id"] not in restaurants or
                not REFERENCE_RE.fullmatch(reservation["reference"]) or
                reservation["status"] not in ("confirmed", "cancelled") or
                type(reservation.get("party_size")) is not int or reservation["party_size"] < 1):
            return False
        if reservation["reference"] in refs or reservation["reservation_id"] in ids:
            return False
        refs.add(reservation["reference"])
        ids.add(reservation["reservation_id"])
        try:
            restaurant = restaurants[reservation["restaurant_id"]]
            local = _parse_local(reservation["starts_at_local"])
            if _canonical_table_ids(restaurant, table_ids) != table_ids:
                return False
            terms = reservation.get("accepted_terms")
            if "revision" in reservation:
                if (type(reservation["revision"]) is not int or reservation["revision"] < 1 or
                        not _valid_terms(terms, restaurant) or
                        not isinstance(reservation.get("history"), list)):
                    return False
                known_terms = [_policy_terms(_policy0(restaurant))] + [
                    _policy_terms(policy) for policy in restaurant.get("policies", [])]
                if not any(terms == known for known in known_terms):
                    return False
                if len(reservation["history"]) != reservation["revision"]:
                    return False
                for seq, entry in enumerate(reservation["history"], 1):
                    if (not isinstance(entry, dict) or type(entry.get("seq")) is not int or
                            entry["seq"] != seq or type(entry.get("revision")) is not int or
                            entry["revision"] != seq or
                            entry.get("event") not in ("created", "changed", "cancelled", "reassigned") or
                            not isinstance(entry.get("changes"), list) or
                            entry.get("accepted_terms") not in known_terms):
                        return False
                    if ((entry["event"] == "reassigned") !=
                            (isinstance(entry.get("plan_id"), str) and bool(entry["plan_id"]))):
                        return False
                    fields = []
                    for change in entry["changes"]:
                        if (not isinstance(change, dict) or
                                set(change) != {"field", "from", "to"} or
                                change["field"] not in
                                ("table_id", "table_ids", "starts_at_local", "party_size")):
                            return False
                        fields.append(change["field"])
                    if len(set(fields)) != len(fields):
                        return False
                    if (entry["event"] == "created" and fields not in
                            (["table_id", "starts_at_local", "party_size"],
                             ["table_ids", "starts_at_local", "party_size"])):
                        return False
                    if entry["event"] == "changed" and not fields:
                        return False
                    if entry["event"] == "reassigned" and fields != ["table_ids"]:
                        return False
                    if entry["event"] == "cancelled" and entry["changes"]:
                        return False
                    try:
                        _instant(entry["at"])
                    except (KeyError, TypeError, ValueError):
                        return False
                if (reservation["history"][0]["event"] != "created" or
                        reservation["history"][-1]["accepted_terms"] != terms):
                    return False
                capacity_source = terms["capacities"]
                expected_end = (_resolve_local(local, restaurant["timezone"]).astimezone(UTC) +
                                dt.timedelta(minutes=terms["reservation_duration_minutes"]))
                if _instant(reservation["ends_at"]) != expected_end:
                    return False
            else:
                capacity_source = _policy0(restaurant)["capacities"]
            capacity = sum(capacity_source[table_id] for table_id in table_ids)
            if reservation["party_size"] > capacity:
                return False
            if _instant(reservation["starts_at"]) != _resolve_local(
                    local, restaurant["timezone"]).astimezone(UTC):
                return False
            if _instant(reservation["ends_at"]) <= _instant(reservation["starts_at"]):
                return False
            _instant(reservation["created_at"])
        except (ApiError, TypeError, ValueError, KeyError, IndexError,
                OverflowError, ZoneInfoNotFoundError):
            return False
    rows = state["reservations"]
    for index, reservation in enumerate(rows):
        if reservation["status"] == "confirmed" and any(
                other["status"] == "confirmed" and
                other["restaurant_id"] == reservation["restaurant_id"] and
                set(_reservation_table_ids(reservation)).intersection(
                    _reservation_table_ids(other)) and overlaps(reservation, other)
                for other in rows[index + 1:]):
            return False
    scopes = set()
    for receipt in state["receipts"]:
        if not isinstance(receipt, dict):
            return False
        path, key = receipt.get("path"), receipt.get("key")
        if (not isinstance(receipt.get("user_id"), str) or
                receipt["user_id"] not in user_ids or
                not isinstance(receipt.get("method"), str) or receipt["method"] != "POST" or
                not isinstance(path, str) or
                (path not in ("/reservations", "/reservation-moves", "/series") and
                 not re.fullmatch(r"/restaurants/[^/]+/(?:policies|replans)", path) and
                 not re.fullmatch(r"/restaurants/[^/]+/replans/[^/]+/apply", path) and
                 not re.fullmatch(r"/series/[^/]+/amend", path)) or
                not isinstance(key, str) or not 1 <= len(key) <= 255 or
                not isinstance(receipt.get("body"), dict) or
                not isinstance(receipt.get("response"), dict)):
            return False
        scope = (receipt["user_id"], receipt["method"], receipt["path"], receipt["key"])
        if scope in scopes:
            return False
        scopes.add(scope)
    series_ids, series_refs = set(), set()
    reservation_by_reference = {item["reference"]: item for item in state["reservations"]}
    for series in state.get("series", []):
        if (not isinstance(series, dict) or not isinstance(series.get("series_id"), str) or
                not series["series_id"] or series["series_id"] in series_ids or
                not isinstance(series.get("user_id"), str) or
                series["user_id"] not in user_ids or
                not isinstance(series.get("restaurant_id"), str) or
                series["restaurant_id"] not in restaurants or
                type(series.get("revision")) is not int or series["revision"] < 1 or
                type(series.get("interval_weeks")) is not int or
                not 1 <= series["interval_weeks"] <= 4 or
                not isinstance(series.get("occurrences"), list) or
                not 2 <= len(series["occurrences"]) <= 12):
            return False
        series_ids.add(series["series_id"])
        try:
            origin_local = _series_origin_local(state, series)
        except (ApiError, KeyError, IndexError, TypeError, ValueError, OverflowError):
            return False
        for index, occurrence in enumerate(series["occurrences"]):
            if (not isinstance(occurrence, dict) or type(occurrence.get("index")) is not int or
                    occurrence["index"] != index or
                    not isinstance(occurrence.get("reference"), str) or
                    type(occurrence.get("exception")) is not bool or
                    occurrence["reference"] not in reservation_by_reference or
                    occurrence["reference"] in series_refs):
                return False
            reservation = reservation_by_reference[occurrence["reference"]]
            if (reservation["user_id"] != series["user_id"] or
                    reservation["restaurant_id"] != series["restaurant_id"]):
                return False
            try:
                scheduled_local = _parse_local(occurrence["scheduled_starts_at_local"])
                occurrence_local = _parse_local(reservation["starts_at_local"])
            except (ApiError, KeyError, TypeError, ValueError):
                return False
            if scheduled_local.date() != origin_local.date() + dt.timedelta(
                    weeks=index * series["interval_weeks"]):
                return False
            if not occurrence["exception"] and occurrence_local != scheduled_local:
                return False
            series_refs.add(occurrence["reference"])
    plans = state.get("plans", [])
    plan_ids = set()
    for plan in plans:
        if (not isinstance(plan, dict) or not isinstance(plan.get("plan_id"), str) or
                not plan["plan_id"] or plan["plan_id"] in plan_ids or
                not isinstance(plan.get("restaurant_id"), str) or
                plan["restaurant_id"] not in restaurants or
                type(plan.get("restaurant_revision")) is not int or
                plan["restaurant_revision"] < 0 or type(plan.get("applied")) is not bool or
                not isinstance(plan.get("closure"), dict) or
                not isinstance(plan.get("assignments"), list) or
                type(plan.get("moved_count")) is not int or plan["moved_count"] < 0 or
                type(plan.get("unused_seats")) is not int or plan["unused_seats"] < 0):
            return False
        plan_ids.add(plan["plan_id"])
        restaurant = restaurants[plan["restaurant_id"]]
        closure = plan["closure"]
        if (not isinstance(closure.get("table_id"), str) or
                closure["table_id"] not in {table["id"] for table in restaurant["tables"]} or
                not isinstance(closure.get("from"), str) or
                not isinstance(closure.get("to"), str)):
            return False
        try:
            if _instant(closure["from"]) >= _instant(closure["to"]):
                return False
        except (TypeError, ValueError):
            return False
        refs_in_plan = []
        for assignment in plan["assignments"]:
            if (not isinstance(assignment, dict) or
                    not isinstance(assignment.get("reference"), str) or
                    assignment["reference"] not in reservation_by_reference or
                    not isinstance(assignment.get("table_ids"), list) or
                    type(assignment.get("changed")) is not bool):
                return False
            reservation = reservation_by_reference[assignment["reference"]]
            if reservation["restaurant_id"] != plan["restaurant_id"]:
                return False
            try:
                if _canonical_table_ids(restaurant, assignment["table_ids"]) != assignment["table_ids"]:
                    return False
            except ApiError:
                return False
            refs_in_plan.append(assignment["reference"])
        if refs_in_plan != sorted(refs_in_plan) or len(set(refs_in_plan)) != len(refs_in_plan):
            return False
        if plan["moved_count"] != sum(row["changed"] for row in plan["assignments"]):
            return False
        if plan["applied"] and not any(
                stored.get("plan_id") == plan["plan_id"] and
                all(stored.get(key) == closure.get(key) for key in ("table_id", "from", "to"))
                for stored in raw_restaurants[plan["restaurant_id"]].get("closures", [])):
            return False
    plans_by_id = {plan["plan_id"]: plan for plan in plans}
    for raw_restaurant in state["restaurants"]:
        for closure in raw_restaurant.get("closures", []):
            plan = plans_by_id.get(closure["plan_id"])
            if (plan is None or not plan["applied"] or
                    plan["restaurant_id"] != raw_restaurant["id"] or
                    any(closure.get(key) != plan["closure"].get(key)
                        for key in ("table_id", "from", "to"))):
                return False
    for reservation in rows:
        for entry in reservation.get("history", []):
            if entry.get("event") == "reassigned":
                plan = plans_by_id.get(entry["plan_id"])
                if (plan is None or not plan["applied"] or
                        plan["restaurant_id"] != reservation["restaurant_id"]):
                    return False
    for restaurant in state["restaurants"]:
        for reservation in rows:
            if (reservation["status"] == "confirmed" and
                    reservation["restaurant_id"] == restaurant["id"] and
                    any(reservation_table == closure["table_id"] and
                        _instant(reservation["starts_at"]) < _instant(closure["to"]) and
                        _instant(closure["from"]) < _instant(reservation["ends_at"])
                        for reservation_table in _reservation_table_ids(reservation)
                        for closure in restaurant.get("closures", []))):
                return False
    return True


app = FastAPI(default_response_class=ApiJSONResponse)
_STATIC_DIR = Path(os.environ.get("TABLEKEEPER_STATIC", "/app/static"))
app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets", check_dir=False),
          name="assets")


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError) -> ApiJSONResponse:
    return ApiJSONResponse(status_code=exc.status,
                            content={"error": {"code": exc.code, "message": str(exc)}})


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException) -> ApiJSONResponse:
    code = "not_found" if exc.status_code == 404 else "method_not_allowed"
    return ApiJSONResponse(status_code=exc.status_code,
                           content={"error": {"code": code, "message": "The route was not found."}})


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> ApiJSONResponse:
    return ApiJSONResponse(status_code=500, content={
        "error": {"code": "internal_error", "message": "The service could not complete the request."}})


@app.get("/", include_in_schema=False)
@app.get("/signup", include_in_schema=False)
@app.get("/login", include_in_schema=False)
@app.get("/lookup", include_in_schema=False)
def spa_entry() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html", media_type="text/html; charset=utf-8")


@app.get("/health")
def health() -> dict[str, str]:
    read_state()
    return {"status": "ok"}


@app.post("/_test/reset", status_code=204)
async def reset(request: Request) -> Response:
    replacement = _fixture(await body_object(request))
    transaction(lambda state: state.update(replacement))
    return Response(status_code=204)


@app.get("/_test/export")
def export_state() -> dict[str, Any]:
    return {"track": "tablekeeper", "format_version": 1, "state": read_state()}


@app.post("/_test/import", status_code=204)
async def import_state(request: Request) -> Response:
    value = await body_object(request)
    if (value.get("track") != "tablekeeper" or type(value.get("format_version")) is not int or
            value["format_version"] != 1 or not isinstance(value.get("state"), dict)):
        invalid()
    try:
        replacement = json.loads(json.dumps(value["state"], allow_nan=False))
        _upgrade_import_state(replacement)
    except (TypeError, ValueError, KeyError):
        invalid()
    if not _validate_internal_state(replacement):
        invalid()
    transaction(lambda state: state.update(replacement))
    return Response(status_code=204)


@app.post("/auth/signup", status_code=201)
async def signup(request: Request) -> ApiJSONResponse:
    body = await body_object(request)
    email = email_value(required(body, "email"))
    password = string_value(required(body, "password"))
    display_name = string_value(required(body, "display_name"))
    if len(password) < 8:
        invalid()
    password_hash = _hash_password(password)

    def change(state: dict[str, Any]) -> dict[str, str]:
        if any(user["email"] == email for user in state["users"]):
            error(409, "email_taken", "That email is already registered.")
        uid, token = _new_id(state, "u_", "id"), secrets.token_urlsafe(32)
        while token in state["tokens"]:
            token = secrets.token_urlsafe(32)
        state["users"].append({"id": uid, "email": email,
                               "password_hash": password_hash, "display_name": display_name})
        state["tokens"][token] = uid
        return {"user_id": uid, "display_name": display_name, "token": token}

    return ApiJSONResponse(status_code=201, content=transaction(change))


@app.post("/auth/login")
async def login(request: Request) -> dict[str, str]:
    body = await body_object(request)
    email = email_value(required(body, "email"))
    password = string_value(required(body, "password"))

    def change(state: dict[str, Any]) -> dict[str, str]:
        user = next((item for item in state["users"] if item["email"] == email), None)
        if user is None or not _password_matches(password, user["password_hash"]):
            error(401, "unauthenticated", "Email or password is incorrect.")
        token = secrets.token_urlsafe(32)
        while token in state["tokens"]:
            token = secrets.token_urlsafe(32)
        state["tokens"][token] = user["id"]
        return {"user_id": user["id"], "display_name": user["display_name"], "token": token}

    return transaction(change)


@app.get("/restaurants")
def restaurants() -> dict[str, Any]:
    state = read_state()
    return {"restaurants": [{"id": item["id"], "name": item["name"],
                             "timezone": item["timezone"]}
                            for item in state["restaurants"]]}


@app.get("/restaurants/{restaurant_id}")
def restaurant_detail(restaurant_id: str, request: Request) -> dict[str, Any]:
    state = read_state()
    restaurant = restaurant_by_id(state, restaurant_id)
    uid = _private_owner_id(state, request)
    detail = {key: value for key, value in restaurant.items()
              if key not in ("manager_user_ids", "policies", "restaurant_revision")}
    detail["can_manage_policies"] = uid is not None and uid in restaurant.get(
        "manager_user_ids", [])
    return detail


@app.get("/restaurants/{restaurant_id}/policies")
def list_policies(restaurant_id: str) -> dict[str, Any]:
    restaurant = restaurant_by_id(read_state(), restaurant_id)
    return {"policies": [dict(policy) for policy in restaurant.get("policies", [])]}


@app.post("/restaurants/{restaurant_id}/policies", status_code=201)
async def publish_policy(restaurant_id: str, request: Request) -> ApiJSONResponse:
    body = await body_object(request)

    def change(state: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        restaurant = restaurant_by_id(state, restaurant_id)
        uid = user_id_for(state, request)
        if uid not in restaurant.get("manager_user_ids", []):
            error(403, "forbidden", "Only a restaurant manager can publish policies.")
        key = idempotency_key(request)
        path = f"/restaurants/{restaurant_id}/policies"
        previous = replay(state, uid, path, key, body)
        if previous is not None:
            return 200, previous
        normalized = _policy_payload(body, restaurant)
        policy = {"policy_version": len(restaurant.get("policies", [])) + 1,
                  **normalized}
        restaurant.setdefault("policies", []).append(policy)
        restaurant["restaurant_revision"] = restaurant.get("restaurant_revision", 0) + 1
        record_receipt(state, uid, path, key, body, policy)
        return 201, policy

    status, response = transaction(change)
    return ApiJSONResponse(status_code=status, content=response)


@app.get("/reservations/{reference}/history")
def reservation_history(reference: str, request: Request) -> dict[str, Any]:
    reservation = reservation_for_private_owner(read_state(), reference, request)
    return {"reference": reference,
            "entries": [dict(entry) for entry in reservation.get("history", [])]}


@app.get("/reservations/{reference}/decision")
def reservation_decision(reference: str, request: Request) -> dict[str, Any]:
    reservation = reservation_for_private_owner(read_state(), reference, request)
    return {"reference": reference, "revision": reservation["revision"],
            "accepted_terms": reservation["accepted_terms"]}


@app.post("/series", status_code=201)
async def create_series(request: Request) -> ApiJSONResponse:
    body = await body_object(request)

    def change(state: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        uid = user_id_for(state, request)
        key = idempotency_key(request)
        previous = replay(state, uid, "/series", key, body)
        if previous is not None:
            return 200, previous
        anchor_reference = required(body, "anchor_reference")
        if not isinstance(anchor_reference, str):
            malformed()
        anchor = reservation_for_owner(state, anchor_reference, uid)
        if anchor["status"] != "confirmed":
            error(409, "reservation_cancelled", "The anchor reservation is cancelled.")
        if _series_for_reference(state, anchor_reference) is not None:
            error(409, "already_in_series", "The reservation already belongs to a series.")
        restaurant = restaurant_by_id(state, anchor["restaurant_id"])
        if _cutoff_passed(anchor, restaurant):
            error(409, "cutoff_passed", "The cancellation cutoff has passed.")
        count = required(body, "count")
        interval_weeks = required(body, "interval_weeks")
        if type(count) is not int or not 2 <= count <= 12 or \
                type(interval_weeks) is not int or not 1 <= interval_weeks <= 4:
            invalid()
        anchor_local = _parse_local(anchor["starts_at_local"])
        occurrences = [{"index": 0, "reference": anchor_reference, "exception": False,
                        "scheduled_starts_at_local": anchor["starts_at_local"]}]
        for index in range(1, count):
            date = anchor_local.date() + dt.timedelta(weeks=index * interval_weeks)
            starts_at_local = f"{date.isoformat()}T{anchor_local:%H:%M}"
            fields = booking_fields(state, anchor["restaurant_id"],
                                    _reservation_table_ids(anchor), starts_at_local,
                                    anchor["party_size"])
            reservation = {"reservation_id": _new_id(state, "res_", "reservation_id"),
                           "reference": _new_reference(state), "user_id": uid,
                           "restaurant_id": anchor["restaurant_id"],
                           "party_size": anchor["party_size"], "status": "confirmed",
                           **fields, "created_at": utc_now(), "revision": 1, "history": []}
            _set_reservation_tables(reservation, fields["table_ids"])
            if not free_for(state, reservation):
                error(409, "table_unavailable", "A recurring table is already reserved.")
            _record_history(reservation, "created", _creation_changes(reservation),
                            reservation["created_at"])
            state["reservations"].append(reservation)
            occurrences.append({"index": index, "reference": reservation["reference"],
                                "exception": False,
                                "scheduled_starts_at_local": starts_at_local})
        series = {"series_id": _new_series_id(state), "user_id": uid,
                  "restaurant_id": anchor["restaurant_id"], "revision": 1,
                  "interval_weeks": interval_weeks, "occurrences": occurrences}
        state.setdefault("series", []).append(series)
        restaurant["restaurant_revision"] = restaurant.get("restaurant_revision", 0) + 1
        response = _public_series(state, series)
        record_receipt(state, uid, "/series", key, body, response)
        return 201, response

    status, response = transaction(change)
    return ApiJSONResponse(status_code=status, content=response)


@app.get("/series/{series_id}")
def get_series(series_id: str, request: Request) -> dict[str, Any]:
    state = read_state()
    uid = _private_owner_id(state, request)
    series = next((item for item in state.get("series", [])
                   if item["series_id"] == series_id and item["user_id"] == uid), None)
    if series is None:
        error(404, "not_found", "Series not found.")
    return _public_series(state, series)


def _manager_id(state: dict[str, Any], request: Request,
                restaurant: dict[str, Any]) -> str:
    uid = user_id_for(state, request)
    if uid not in restaurant.get("manager_user_ids", []):
        error(403, "forbidden", "Only a restaurant manager can perform this action.")
    return uid


def _closure_overlap(reservation: dict[str, Any], closure: dict[str, Any]) -> bool:
    return (_instant(reservation["starts_at"]) < _instant(closure["to"]) and
            _instant(closure["from"]) < _instant(reservation["ends_at"]))


def _replan_assignments(state: dict[str, Any], restaurant: dict[str, Any],
                        closure: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    rid = restaurant["id"]
    considered = sorted((row for row in state["reservations"]
                         if row["restaurant_id"] == rid and row["status"] == "confirmed" and
                         _closure_overlap(row, closure)), key=lambda row: row["reference"])
    if (len(restaurant["tables"]) > 6 or len(restaurant.get("combinable", [])) > 4 or
            len(considered) > 6):
        error(422, "planning_limit", "The restaurant exceeds the bounded planning limits.")
    ignored = {row["reference"] for row in considered}
    singles = [([table["id"]], table["capacity"], index)
               for index, table in enumerate(restaurant["tables"])]
    # Rank declared pairs after every single, preserving pair declaration order.
    pair_offset = len(restaurant["tables"])
    pair_options = []
    for index, pair in enumerate(restaurant.get("combinable", [])):
        canonical = [table["id"] for table in restaurant["tables"] if table["id"] in pair]
        pair_options.append((canonical, index, pair_offset + index))
    option_rows = []
    for reservation in considered:
        capacities = reservation["accepted_terms"]["capacities"]
        eligible = []
        for ids, _, rank in singles:
            capacity = capacities[ids[0]]
            if capacity >= reservation["party_size"]:
                eligible.append((ids, capacity, rank))
        for ids, _, rank in pair_options:
            capacity = sum(capacities[table_id] for table_id in ids)
            if capacity >= reservation["party_size"]:
                eligible.append((ids, capacity, rank))
        feasible = []
        for ids, capacity, rank in eligible:
            candidate = {**reservation, "table_ids": ids}
            _set_reservation_tables(candidate, ids)
            if (ids and closure["table_id"] in ids and _closure_overlap(candidate, closure)):
                continue
            if not free_for(state, candidate, ignored):
                continue
            feasible.append((ids, capacity, rank))
        if not feasible:
            error(409, "no_feasible_plan", "No seating assignment satisfies the closure.")
        option_rows.append(feasible)

    best_score = None
    best_choice = None
    chosen: list[tuple[list[str], int, int]] = []
    min_changes = [int(not any(ids == _reservation_table_ids(row)
                               for ids, _, _ in choices))
                   for row, choices in zip(considered, option_rows)]
    min_unused = [min(capacity - row["party_size"] for _, capacity, _ in choices)
                  for row, choices in zip(considered, option_rows)]
    change_suffix = [0] * (len(considered) + 1)
    unused_suffix = [0] * (len(considered) + 1)
    for index in range(len(considered) - 1, -1, -1):
        change_suffix[index] = change_suffix[index + 1] + min_changes[index]
        unused_suffix[index] = unused_suffix[index + 1] + min_unused[index]

    def search(index: int, moved: int, unused: int) -> None:
        nonlocal best_score, best_choice
        if best_score is not None:
            min_moved_total = moved + change_suffix[index]
            min_unused_total = unused + unused_suffix[index]
            if min_moved_total > best_score[0] or (
                    min_moved_total == best_score[0] and min_unused_total > best_score[1]):
                return
            if (min_moved_total == best_score[0] and
                    min_unused_total == best_score[1] and
                    tuple(item[2] for item in chosen) > best_score[2][:index]):
                return
        if index == len(considered):
            score = (moved, unused, tuple(item[2] for item in chosen))
            if best_score is None or score < best_score:
                best_score, best_choice = score, tuple(chosen)
            return
        reservation = considered[index]
        old_ids = _reservation_table_ids(reservation)
        for ids, capacity, rank in option_rows[index]:
            if any(set(ids).intersection(other_ids) and overlaps(reservation, other)
                   for other, (other_ids, _, _) in zip(considered[:index], chosen)):
                continue
            chosen.append((ids, capacity, rank))
            search(index + 1, moved + (ids != old_ids), unused + capacity - reservation["party_size"])
            chosen.pop()

    search(0, 0, 0)
    if best_choice is None:
        error(409, "no_feasible_plan", "No seating assignment satisfies the closure.")
    assignments = [{"reference": reservation["reference"], "table_ids": list(choice[0]),
                    "changed": choice[0] != _reservation_table_ids(reservation)}
                   for reservation, choice in zip(considered, best_choice)]
    return assignments, best_score[1]


@app.post("/restaurants/{restaurant_id}/replans", status_code=201)
async def create_replan(restaurant_id: str, request: Request) -> ApiJSONResponse:
    body = await body_object(request)

    def change(state: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        restaurant = restaurant_by_id(state, restaurant_id)
        uid = _manager_id(state, request, restaurant)
        key = idempotency_key(request)
        path = f"/restaurants/{restaurant_id}/replans"
        previous = replay(state, uid, path, key, body)
        if previous is not None:
            return 200, previous
        table_id = identifier(required(body, "table_id"))
        table_by_id(restaurant, table_id)
        start, end = required(body, "from"), required(body, "to")
        if not isinstance(start, str) or not isinstance(end, str):
            malformed()
        try:
            if _instant(start) >= _instant(end):
                invalid()
        except (TypeError, ValueError):
            invalid()
        closure = {"table_id": table_id, "from": start, "to": end}
        assignments, unused_seats = _replan_assignments(state, restaurant, closure)
        moved_count = sum(item["changed"] for item in assignments)
        plan = {"plan_id": _new_plan_id(state), "restaurant_id": restaurant_id,
                "restaurant_revision": restaurant.get("restaurant_revision", 0),
                "closure": closure, "assignments": assignments,
                "moved_count": moved_count, "unused_seats": unused_seats,
                "applied": False}
        state.setdefault("plans", []).append(plan)
        response = {key: value for key, value in plan.items()
                    if key not in ("restaurant_id", "applied")}
        record_receipt(state, uid, path, key, body, response)
        return 201, response

    status, response = transaction(change)
    return ApiJSONResponse(status_code=status, content=response)


@app.post("/restaurants/{restaurant_id}/replans/{plan_id}/apply", status_code=201)
async def apply_replan(restaurant_id: str, plan_id: str,
                       request: Request) -> ApiJSONResponse:
    body = await body_object(request)

    def change(state: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        restaurant = restaurant_by_id(state, restaurant_id)
        uid = _manager_id(state, request, restaurant)
        key = idempotency_key(request)
        path = f"/restaurants/{restaurant_id}/replans/{plan_id}/apply"
        previous = replay(state, uid, path, key, body)
        if previous is not None:
            return 200, previous
        plan = next((item for item in state.get("plans", [])
                     if item["plan_id"] == plan_id and
                     item["restaurant_id"] == restaurant_id), None)
        if plan is None:
            error(404, "not_found", "Plan not found.")
        if plan["applied"]:
            error(409, "plan_already_applied", "The seating plan has already been applied.")
        if restaurant.get("restaurant_revision", 0) != plan["restaurant_revision"]:
            error(409, "stale_plan", "The restaurant changed after this plan was previewed.")
        by_reference = {item["reference"]: item for item in state["reservations"]}
        affected_series = {}
        result = []
        for assignment in plan["assignments"]:
            reservation = by_reference[assignment["reference"]]
            if assignment["changed"]:
                before = _reservation_table_ids(reservation)
                _set_reservation_tables(reservation, assignment["table_ids"])
                reservation["revision"] += 1
                _record_history(reservation, "reassigned", [{
                    "field": "table_ids", "from": before,
                    "to": list(assignment["table_ids"])}], plan_id=plan_id)
                series_member = _series_for_reference(state, reservation["reference"])
                if series_member is not None:
                    affected_series[series_member[0]["series_id"]] = series_member[0]
            result.append(public_reservation(reservation))
        closure = {**plan["closure"], "plan_id": plan_id}
        restaurant.setdefault("closures", []).append(closure)
        restaurant["restaurant_revision"] = restaurant.get("restaurant_revision", 0) + 1
        for series in affected_series.values():
            series["revision"] += 1
        plan["applied"] = True
        response = {"plan_id": plan_id,
                    "restaurant_revision": restaurant["restaurant_revision"],
                    "reservations": result}
        record_receipt(state, uid, path, key, body, response)
        return 201, response

    status, response = transaction(change)
    return ApiJSONResponse(status_code=status, content=response)


@app.post("/series/{series_id}/amend", status_code=201)
async def amend_series(series_id: str, request: Request) -> ApiJSONResponse:
    body = await body_object(request)

    def change(state: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        uid = user_id_for(state, request)
        series = next((item for item in state.get("series", [])
                       if item["series_id"] == series_id and item["user_id"] == uid), None)
        if series is None:
            error(404, "not_found", "Series not found.")
        key = idempotency_key(request)
        path = f"/series/{series_id}/amend"
        previous = replay(state, uid, path, key, body)
        if previous is not None:
            return 200, previous
        expected = required(body, "expected_revision")
        from_index = required(body, "from_index")
        local_time = required(body, "local_time")
        if (type(expected) is not int or expected < 1 or
                type(from_index) is not int or not 0 <= from_index < len(series["occurrences"]) or
                not isinstance(local_time, str) or not TIME_RE.fullmatch(local_time) or
                int(local_time[:2]) > 23 or int(local_time[3:]) > 59):
            invalid()
        if expected != series["revision"]:
            error(409, "stale_revision", "The series revision has changed.")
        rows = {item["reference"]: item for item in state["reservations"]}
        restaurant = restaurant_by_id(state, series["restaurant_id"])
        candidates = []
        for occurrence in series["occurrences"][from_index:]:
            reservation = rows[occurrence["reference"]]
            if occurrence["exception"] or reservation["status"] == "cancelled":
                continue
            scheduled = _series_scheduled_local(state, series, occurrence["index"])
            starts_at_local = f"{scheduled.date().isoformat()}T{local_time}"
            if starts_at_local == reservation["starts_at_local"]:
                continue
            if _cutoff_passed(reservation, restaurant):
                error(409, "cutoff_passed", "The cancellation cutoff has passed.")
            fields = booking_fields(state, reservation["restaurant_id"],
                                    _reservation_table_ids(reservation), starts_at_local,
                                    reservation["party_size"])
            candidate = {**reservation, **fields}
            _set_reservation_tables(candidate, fields["table_ids"])
            candidates.append((reservation, candidate))

        changed_refs = {reservation["reference"] for reservation, _ in candidates}
        ignored = set(changed_refs)
        if any(not free_for(state, candidate, ignored) for _, candidate in candidates):
            error(409, "table_unavailable", "A resulting table is already reserved.")
        for index, (_, candidate) in enumerate(candidates):
            for _, other in candidates[index + 1:]:
                if (set(_reservation_table_ids(candidate)).intersection(
                        _reservation_table_ids(other)) and overlaps(candidate, other)):
                    error(409, "table_unavailable", "The amended series contains overlapping reservations.")
        for reservation, candidate in candidates:
            changes = _changed_fields(reservation, candidate)
            reservation.update({name: candidate[name] for name in (
                "starts_at_local", "starts_at", "ends_at", "accepted_terms")})
            reservation["revision"] += 1
            _record_history(reservation, "changed", changes)
            _series_for_reference(state, reservation["reference"])[1][
                "scheduled_starts_at_local"] = candidate["starts_at_local"]
        if candidates:
            series["revision"] += 1
            restaurant["restaurant_revision"] = restaurant.get("restaurant_revision", 0) + 1
        response = _public_series(state, series)
        record_receipt(state, uid, path, key, body, response)
        return 201, response

    status, response = transaction(change)
    return ApiJSONResponse(status_code=status, content=response)


@app.get("/availability")
def availability(request: Request) -> dict[str, Any]:
    query = request.query_params
    rid, date_value, party_value = (
        query.get("restaurant_id"), query.get("date"), query.get("party_size"))
    if rid is None or date_value is None or party_value is None:
        invalid()
    date = _parse_date(date_value)
    if not re.fullmatch(r"[0-9]+", party_value):
        invalid()
    party = int(party_value)
    if party < 1:
        invalid()
    explain_value = query.get("explain")
    if explain_value is not None and explain_value != "true":
        invalid()
    explain = explain_value == "true"
    state = read_state()
    restaurant = restaurant_by_id(state, rid)
    policy = _policy_for_date(restaurant, date)
    weekday = WEEKDAYS[date.weekday()]
    hours = next((item for item in policy["opening_hours"]
                  if item["weekday"] == weekday), None)
    slots = []
    if hours is not None:
        opening, closing = _minute(hours["opens"]), _minute(hours["closes"])
        duration, step = policy["reservation_duration_minutes"], policy["slot_minutes"]
        minute = opening
        while minute + duration <= closing:
            local = dt.datetime.combine(date, dt.time(minute // 60, minute % 60))
            try:
                start = _resolve_local(local, restaurant["timezone"])
            except ApiError as exc:
                if exc.code != "invalid_local_time":
                    raise
                minute += step
                continue
            end = (start.astimezone(UTC) + dt.timedelta(minutes=duration)).astimezone(
                ZoneInfo(restaurant["timezone"]))
            candidate = {"restaurant_id": rid, "table_ids": [], "starts_at": _iso(start),
                         "ends_at": _iso(end), "status": "confirmed"}
            free_tables, available_options, explanations = [], [], []
            for table in restaurant["tables"]:
                candidate["table_ids"] = [table["id"]]
                capacity_holds = policy["capacities"][table["id"]] >= party
                overlap_holds = free_for(state, candidate)
                if capacity_holds and overlap_holds:
                    free_tables.append(table["id"])
                    available_options.append({"table_ids": [table["id"]],
                                              "capacity": policy["capacities"][table["id"]]})
                if explain:
                    explanations.append({"table_id": table["id"],
                                         "policy_version": policy["policy_version"],
                                         "available": capacity_holds and overlap_holds,
                                         "rules": [{"rule": "capacity", "holds": capacity_holds},
                                                   {"rule": "no_overlap", "holds": overlap_holds}]})
            for pair in restaurant.get("combinable", []):
                candidate["table_ids"] = list(pair)
                capacity = sum(policy["capacities"][table_id] for table_id in pair)
                if capacity >= party and free_for(state, candidate):
                    available_options.append({"table_ids": list(pair), "capacity": capacity})
            slot = {"starts_at_local": local.strftime("%Y-%m-%dT%H:%M"),
                    "starts_at": _iso(start), "available_table_ids": free_tables,
                    "available_options": available_options}
            if explain:
                slot["explain"] = explanations
            slots.append(slot)
            minute += step
    return {"restaurant_id": rid, "date": date.isoformat(),
            "timezone": restaurant["timezone"], "slots": slots}


@app.post("/reservations", status_code=201)
async def create_reservation(request: Request) -> ApiJSONResponse:
    body = await body_object(request)

    def change(state: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        uid = user_id_for(state, request)
        key = idempotency_key(request)
        previous = replay(state, uid, "/reservations", key, body)
        if previous is not None:
            return 200, previous
        rid = identifier(required(body, "restaurant_id"))
        table_ids = _requested_table_ids(body)
        start_local = required(body, "starts_at_local")
        if not isinstance(start_local, str):
            malformed()
        _parse_local(start_local)
        party = party_size_value(required(body, "party_size"))
        fields = booking_fields(state, rid, table_ids, start_local, party)
        reservation = {"reservation_id": _new_id(state, "res_", "reservation_id"),
                       "reference": _new_reference(state), "user_id": uid,
                       "restaurant_id": rid, "party_size": party,
                       "status": "confirmed", **fields, "created_at": utc_now()}
        _set_reservation_tables(reservation, fields["table_ids"])
        if not free_for(state, reservation):
            error(409, "table_unavailable", "That table is already reserved.")
        reservation["revision"] = 1
        reservation["history"] = []
        _record_history(reservation, "created", _creation_changes(reservation),
                        reservation["created_at"])
        state["reservations"].append(reservation)
        restaurant = restaurant_by_id(state, rid)
        restaurant["restaurant_revision"] = restaurant.get("restaurant_revision", 0) + 1
        response = public_reservation(reservation)
        record_receipt(state, uid, "/reservations", key, body, response)
        return 201, response

    status, response = transaction(change)
    return ApiJSONResponse(status_code=status, content=response)


@app.get("/reservations")
def list_reservations(request: Request) -> dict[str, Any]:
    state = read_state()
    uid = user_id_for(state, request)
    rows = [public_reservation(item) for item in state["reservations"]
            if item["user_id"] == uid]
    rows.sort(key=lambda item: _instant(item["starts_at"]), reverse=True)
    return {"reservations": rows}


@app.get("/reservations/{reference}")
def reservation_detail(reference: str, request: Request) -> dict[str, Any]:
    state = read_state()
    uid = user_id_for(state, request)
    return public_reservation(reservation_for_owner(state, reference, uid))


@app.post("/reservations/{reference}/cancel")
def cancel_reservation(reference: str, request: Request) -> dict[str, Any]:
    def change(state: dict[str, Any]) -> dict[str, Any]:
        uid = user_id_for(state, request)
        reservation = reservation_for_owner(state, reference, uid)
        if reservation["status"] == "cancelled":
            return public_reservation(reservation)
        restaurant = restaurant_by_id(state, reservation["restaurant_id"])
        if _cutoff_passed(reservation, restaurant):
            error(409, "cutoff_passed", "The cancellation cutoff has passed.")
        reservation["status"] = "cancelled"
        reservation["revision"] += 1
        _record_history(reservation, "cancelled", [])
        restaurant["restaurant_revision"] = restaurant.get("restaurant_revision", 0) + 1
        series_member = _series_for_reference(state, reference)
        if series_member is not None:
            series_member[0]["revision"] += 1
        return public_reservation(reservation)
    return transaction(change)


@app.patch("/reservations/{reference}")
async def amend_reservation(reference: str, request: Request) -> dict[str, Any]:
    body = await body_object(request)

    def change(state: dict[str, Any]) -> dict[str, Any]:
        uid = user_id_for(state, request)
        reservation = reservation_for_owner(state, reference, uid)
        _check_expected_revision(body, reservation)
        if reservation["status"] == "cancelled":
            error(409, "reservation_cancelled", "The reservation is cancelled.")
        restaurant = restaurant_by_id(state, reservation["restaurant_id"])
        if _cutoff_passed(reservation, restaurant):
            error(409, "cutoff_passed", "The cancellation cutoff has passed.")
        table_ids, start_local, party = _patch_inputs(body, reservation, restaurant)
        if (table_ids, start_local, party) == (
                _reservation_table_ids(reservation), reservation["starts_at_local"],
                reservation["party_size"]):
            return public_reservation(reservation)
        fields = booking_fields(state, reservation["restaurant_id"], table_ids,
                                start_local, party)
        candidate = {**reservation, "party_size": party, **fields}
        _set_reservation_tables(candidate, fields["table_ids"])
        if not free_for(state, candidate, {reference}):
            error(409, "table_unavailable", "That table is already reserved.")
        changes = _changed_fields(reservation, candidate)
        reservation.update({"party_size": party, **fields})
        _set_reservation_tables(reservation, fields["table_ids"])
        reservation["revision"] += 1
        _record_history(reservation, "changed", changes)
        restaurant["restaurant_revision"] = restaurant.get("restaurant_revision", 0) + 1
        series_member = _series_for_reference(state, reference)
        if series_member is not None:
            series_member[0]["revision"] += 1
            series_member[1]["exception"] = True
        return public_reservation(reservation)
    return transaction(change)


@app.post("/reservation-moves", status_code=201)
async def move_reservations(request: Request) -> ApiJSONResponse:
    body = await body_object(request)

    def change(state: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        uid = user_id_for(state, request)
        key = idempotency_key(request)
        previous = replay(state, uid, "/reservation-moves", key, body)
        if previous is not None:
            return 200, previous
        raw_moves = body.get("moves")
        if not isinstance(raw_moves, list) or not 1 <= len(raw_moves) <= 8:
            invalid()
        references, patches, expected_revisions = [], [], []
        for item in raw_moves:
            if not isinstance(item, dict):
                invalid()
            reference = item.get("reference")
            if not isinstance(reference, str) or not reference or len(reference) > 64:
                invalid()
            references.append(reference)
            patches.append({name: value for name, value in item.items()
                            if name in ("table_id", "table_ids", "starts_at_local", "party_size")})
            expected = item.get("expected_revision")
            if "expected_revision" in item and (type(expected) is not int or expected < 1):
                invalid()
            expected_revisions.append(expected if "expected_revision" in item else None)
        if len(set(references)) != len(references):
            invalid()

        reservations, candidates, common_restaurant = [], [], None
        for reference, expected in zip(references, expected_revisions):
            reservation = reservation_for_owner(state, reference, uid)
            if expected is not None and expected != reservation["revision"]:
                error(409, "stale_revision", "The reservation revision has changed.")
        for reference, patch in zip(references, patches):
            reservation = reservation_for_owner(state, reference, uid)
            if common_restaurant is None:
                common_restaurant = reservation["restaurant_id"]
            elif reservation["restaurant_id"] != common_restaurant:
                invalid()
            if reservation["status"] == "cancelled":
                error(409, "reservation_cancelled", "A reservation in the batch is cancelled.")
            restaurant = restaurant_by_id(state, reservation["restaurant_id"])
            if _cutoff_passed(reservation, restaurant):
                error(409, "cutoff_passed", "The cancellation cutoff has passed.")
            table_ids, start_local, party = _patch_inputs(patch, reservation, restaurant)
            if (table_ids, start_local, party) == (
                    _reservation_table_ids(reservation), reservation["starts_at_local"],
                    reservation["party_size"]):
                candidate = reservation.copy()
            else:
                fields = booking_fields(state, reservation["restaurant_id"], table_ids,
                                        start_local, party)
                candidate = {**reservation, "party_size": party, **fields}
                _set_reservation_tables(candidate, fields["table_ids"])
            reservations.append(reservation)
            candidates.append(candidate)

        ignored = set(references)
        if any(not free_for(state, candidate, ignored) for candidate in candidates):
            error(409, "table_unavailable", "A resulting table is already reserved.")
        for index, candidate in enumerate(candidates):
            for other in candidates[index + 1:]:
                if (candidate["restaurant_id"] == other["restaurant_id"] and
                        set(_reservation_table_ids(candidate)).intersection(
                            _reservation_table_ids(other)) and overlaps(candidate, other)):
                    error(409, "table_unavailable", "The batch contains overlapping reservations.")
        changed = []
        affected_series = {}
        for reservation, candidate in zip(reservations, candidates):
            fields_changed = _changed_fields(reservation, candidate)
            if not fields_changed:
                continue
            reservation.update({name: candidate[name] for name in (
                "party_size", "starts_at_local", "starts_at", "ends_at", "accepted_terms")})
            _set_reservation_tables(reservation, _reservation_table_ids(candidate))
            reservation["revision"] += 1
            _record_history(reservation, "changed", fields_changed)
            changed.append(reservation)
            series_member = _series_for_reference(state, reservation["reference"])
            if series_member is not None:
                series_member[1]["exception"] = True
                affected_series[series_member[0]["series_id"]] = series_member[0]
        if changed:
            restaurant = restaurant_by_id(state, common_restaurant)
            restaurant["restaurant_revision"] = restaurant.get("restaurant_revision", 0) + 1
            for series in affected_series.values():
                series["revision"] += 1
        response = {"reservations": [public_reservation(item) for item in reservations]}
        record_receipt(state, uid, "/reservation-moves", key, body, response)
        return 201, response

    status, response = transaction(change)
    return ApiJSONResponse(status_code=status, content=response)
