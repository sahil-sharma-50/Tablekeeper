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
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException

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
            "reservations": [], "receipts": []}


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
    return {"id": rid, "name": name, "timezone": timezone,
            "slot_minutes": slot, "reservation_duration_minutes": duration,
            "cancellation_cutoff_minutes": cutoff,
            "opening_hours": opening_hours, "tables": tables}


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
    state = {"version": 1, "users": users, "tokens": {}, "restaurants": restaurants,
             "reservations": [], "receipts": []}
    for item in reservations_raw:
        if not isinstance(item, dict):
            malformed()
        res_id = identifier(required(item, "id"))
        reference = string_value(required(item, "reference"))
        uid = identifier(required(item, "user_id"))
        rid = identifier(required(item, "restaurant_id"))
        tid = identifier(required(item, "table_id"))
        start_local = string_value(required(item, "starts_at_local"))
        party = party_size_value(required(item, "party_size"))
        if not REFERENCE_RE.fullmatch(reference) or uid not in user_ids:
            invalid()
        try:
            fields = booking_fields(state, rid, tid, start_local, party)
        except ApiError:
            invalid()
        status = item.get("status", "confirmed")
        if status not in ("confirmed", "cancelled"):
            invalid()
        reservation = {"reservation_id": res_id, "reference": reference, "user_id": uid,
                       "restaurant_id": rid, "table_id": tid, "party_size": party,
                       "status": status, **fields, "created_at": utc_now()}
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
            return restaurant
    error(404, "not_found", "Restaurant not found.")


def table_by_id(restaurant: dict[str, Any], tid: str) -> dict[str, Any]:
    for table in restaurant["tables"]:
        if table["id"] == tid:
            return table
    error(404, "not_found", "Table not found.")


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


def booking_fields(state: dict[str, Any], rid: str, tid: str,
                   starts_at_local: str, party: int) -> dict[str, str]:
    restaurant = restaurant_by_id(state, rid)
    table = table_by_id(restaurant, tid)
    local = _parse_local(starts_at_local)
    start = _resolve_local(local, restaurant["timezone"])
    weekday = WEEKDAYS[local.weekday()]
    hours = next((item for item in restaurant["opening_hours"]
                  if item["weekday"] == weekday), None)
    minute = local.hour * 60 + local.minute
    duration = restaurant["reservation_duration_minutes"]
    if hours is None:
        error(422, "outside_opening_hours", "The restaurant is closed then.")
    opening, closing = _minute(hours["opens"]), _minute(hours["closes"])
    if minute < opening or minute + duration > closing:
        error(422, "outside_opening_hours", "The reservation does not fit opening hours.")
    if (minute - opening) % restaurant["slot_minutes"]:
        error(422, "not_on_slot_grid", "The start is not on the reservation grid.")
    if party > table["capacity"]:
        error(422, "party_exceeds_capacity", "The party is larger than the table capacity.")
    end = (start.astimezone(UTC) + dt.timedelta(minutes=duration)).astimezone(
        ZoneInfo(restaurant["timezone"]))
    return {"starts_at_local": starts_at_local, "starts_at": _iso(start),
            "ends_at": _iso(end)}


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
    return not any(
        current["status"] == "confirmed" and current["reference"] not in ignored_references and
        current["restaurant_id"] == candidate["restaurant_id"] and
        current["table_id"] == candidate["table_id"] and overlaps(candidate, current)
        for current in state["reservations"])


def public_reservation(reservation: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in reservation.items() if key != "user_id"}


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
    return delta_us <= restaurant["cancellation_cutoff_minutes"] * 60 * 1_000_000


def _patch_inputs(body: dict[str, Any], current: dict[str, Any]) -> tuple[str, str, int]:
    table_id, start_local, party = (
        current["table_id"], current["starts_at_local"], current["party_size"])
    if "table_id" in body:
        table_id = identifier(body["table_id"])
    if "starts_at_local" in body:
        start_local = body["starts_at_local"]
        if not isinstance(start_local, str):
            malformed()
        _parse_local(start_local)
    if "party_size" in body:
        party = party_size_value(body["party_size"])
    return table_id, start_local, party


def _validate_internal_state(state: Any) -> bool:
    if not isinstance(state, dict) or type(state.get("version")) is not int or state["version"] != 1:
        return False
    if any(not isinstance(state.get(key), list)
           for key in ("users", "restaurants", "reservations", "receipts")):
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
    restaurants = {item["id"]: item for item in checked}
    refs, ids = set(), set()
    for reservation in state["reservations"]:
        if not isinstance(reservation, dict) or not all(
                isinstance(reservation.get(key), str) for key in (
                    "reservation_id", "reference", "user_id", "restaurant_id",
                    "table_id", "starts_at_local", "starts_at", "ends_at",
                    "created_at", "status")):
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
            table_by_id(restaurant, reservation["table_id"])
            local = _parse_local(reservation["starts_at_local"])
            if _instant(reservation["starts_at"]) != _resolve_local(
                    local, restaurant["timezone"]).astimezone(UTC):
                return False
            if _instant(reservation["ends_at"]) <= _instant(reservation["starts_at"]):
                return False
            _instant(reservation["created_at"])
        except (ApiError, ValueError, ZoneInfoNotFoundError):
            return False
    rows = state["reservations"]
    for index, reservation in enumerate(rows):
        if reservation["status"] == "confirmed" and any(
                other["status"] == "confirmed" and
                other["restaurant_id"] == reservation["restaurant_id"] and
                other["table_id"] == reservation["table_id"] and overlaps(reservation, other)
                for other in rows[index + 1:]):
            return False
    scopes = set()
    for receipt in state["receipts"]:
        if not isinstance(receipt, dict) or (
                receipt.get("user_id") not in user_ids or receipt.get("method") != "POST" or
                receipt.get("path") not in ("/reservations", "/reservation-moves") or
                not isinstance(receipt.get("key"), str) or
                not 1 <= len(receipt["key"]) <= 255 or
                not isinstance(receipt.get("body"), dict) or
                not isinstance(receipt.get("response"), dict)):
            return False
        scope = (receipt["user_id"], receipt["method"], receipt["path"], receipt["key"])
        if scope in scopes:
            return False
        scopes.add(scope)
    return True


app = FastAPI()


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status,
                        content={"error": {"code": exc.code, "message": str(exc)}})


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code = "not_found" if exc.status_code == 404 else "method_not_allowed"
    return JSONResponse(status_code=exc.status_code,
                        content={"error": {"code": code, "message": "The route was not found."}})


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={
        "error": {"code": "internal_error", "message": "The service could not complete the request."}})


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
            value["format_version"] != 1 or not _validate_internal_state(value.get("state"))):
        invalid()
    transaction(lambda state: state.update(value["state"]))
    return Response(status_code=204)


@app.post("/auth/signup", status_code=201)
async def signup(request: Request) -> JSONResponse:
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

    return JSONResponse(status_code=201, content=transaction(change))


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
def restaurant_detail(restaurant_id: str) -> dict[str, Any]:
    return restaurant_by_id(read_state(), restaurant_id)


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
    state = read_state()
    restaurant = restaurant_by_id(state, rid)
    weekday = WEEKDAYS[date.weekday()]
    hours = next((item for item in restaurant["opening_hours"]
                  if item["weekday"] == weekday), None)
    slots = []
    if hours is not None:
        opening, closing = _minute(hours["opens"]), _minute(hours["closes"])
        duration, step = restaurant["reservation_duration_minutes"], restaurant["slot_minutes"]
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
            candidate = {"restaurant_id": rid, "table_id": "", "starts_at": _iso(start),
                         "ends_at": _iso(end), "status": "confirmed"}
            free_tables = []
            for table in restaurant["tables"]:
                candidate["table_id"] = table["id"]
                if table["capacity"] >= party and free_for(state, candidate):
                    free_tables.append(table["id"])
            slots.append({"starts_at_local": local.strftime("%Y-%m-%dT%H:%M"),
                          "starts_at": _iso(start), "available_table_ids": free_tables})
            minute += step
    return {"restaurant_id": rid, "date": date.isoformat(),
            "timezone": restaurant["timezone"], "slots": slots}


@app.post("/reservations", status_code=201)
async def create_reservation(request: Request) -> JSONResponse:
    body = await body_object(request)

    def change(state: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        uid = user_id_for(state, request)
        key = idempotency_key(request)
        previous = replay(state, uid, "/reservations", key, body)
        if previous is not None:
            return 200, previous
        rid = identifier(required(body, "restaurant_id"))
        tid = identifier(required(body, "table_id"))
        start_local = required(body, "starts_at_local")
        if not isinstance(start_local, str):
            malformed()
        _parse_local(start_local)
        party = party_size_value(required(body, "party_size"))
        fields = booking_fields(state, rid, tid, start_local, party)
        reservation = {"reservation_id": _new_id(state, "res_", "reservation_id"),
                       "reference": _new_reference(state), "user_id": uid,
                       "restaurant_id": rid, "table_id": tid, "party_size": party,
                       "status": "confirmed", **fields, "created_at": utc_now()}
        if not free_for(state, reservation):
            error(409, "table_unavailable", "That table is already reserved.")
        state["reservations"].append(reservation)
        response = public_reservation(reservation)
        record_receipt(state, uid, "/reservations", key, body, response)
        return 201, response

    status, response = transaction(change)
    return JSONResponse(status_code=status, content=response)


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
        return public_reservation(reservation)
    return transaction(change)


@app.patch("/reservations/{reference}")
async def amend_reservation(reference: str, request: Request) -> dict[str, Any]:
    body = await body_object(request)

    def change(state: dict[str, Any]) -> dict[str, Any]:
        uid = user_id_for(state, request)
        reservation = reservation_for_owner(state, reference, uid)
        if reservation["status"] == "cancelled":
            error(409, "reservation_cancelled", "The reservation is cancelled.")
        restaurant = restaurant_by_id(state, reservation["restaurant_id"])
        if _cutoff_passed(reservation, restaurant):
            error(409, "cutoff_passed", "The cancellation cutoff has passed.")
        tid, start_local, party = _patch_inputs(body, reservation)
        if (tid, start_local, party) == (
                reservation["table_id"], reservation["starts_at_local"], reservation["party_size"]):
            return public_reservation(reservation)
        fields = booking_fields(state, reservation["restaurant_id"], tid, start_local, party)
        candidate = {**reservation, "table_id": tid, "party_size": party, **fields}
        if not free_for(state, candidate, {reference}):
            error(409, "table_unavailable", "That table is already reserved.")
        reservation.update({"table_id": tid, "party_size": party, **fields})
        return public_reservation(reservation)
    return transaction(change)


@app.post("/reservation-moves", status_code=201)
async def move_reservations(request: Request) -> JSONResponse:
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
        references, patches = [], []
        for item in raw_moves:
            if not isinstance(item, dict):
                invalid()
            reference = item.get("reference")
            if not isinstance(reference, str) or not reference or len(reference) > 64:
                invalid()
            references.append(reference)
            patches.append({name: value for name, value in item.items()
                            if name in ("table_id", "starts_at_local", "party_size")})
        if len(set(references)) != len(references):
            invalid()

        reservations, candidates, common_restaurant = [], [], None
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
            tid, start_local, party = _patch_inputs(patch, reservation)
            if (tid, start_local, party) == (
                    reservation["table_id"], reservation["starts_at_local"],
                    reservation["party_size"]):
                candidate = reservation.copy()
            else:
                fields = booking_fields(state, reservation["restaurant_id"], tid, start_local, party)
                candidate = {**reservation, "table_id": tid, "party_size": party, **fields}
            reservations.append(reservation)
            candidates.append(candidate)

        ignored = set(references)
        if any(not free_for(state, candidate, ignored) for candidate in candidates):
            error(409, "table_unavailable", "A resulting table is already reserved.")
        for index, candidate in enumerate(candidates):
            for other in candidates[index + 1:]:
                if (candidate["restaurant_id"] == other["restaurant_id"] and
                        candidate["table_id"] == other["table_id"] and overlaps(candidate, other)):
                    error(409, "table_unavailable", "The batch contains overlapping reservations.")
        for reservation, candidate in zip(reservations, candidates):
            reservation.update({name: candidate[name] for name in (
                "table_id", "party_size", "starts_at_local", "starts_at", "ends_at")})
        response = {"reservations": [public_reservation(item) for item in candidates]}
        record_receipt(state, uid, "/reservation-moves", key, body, response)
        return 201, response

    status, response = transaction(change)
    return JSONResponse(status_code=status, content=response)
