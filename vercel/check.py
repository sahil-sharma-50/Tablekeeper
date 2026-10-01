"""Smoke-check a demo deployment; creates a test account and cancels its booking."""
import datetime as dt
import json
import secrets
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

base = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000"


def call(path, body=None, token=None, key=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if key:
        headers["Idempotency-Key"] = key
    data = json.dumps(body).encode() if body is not None else None
    with urlopen(Request(base + path, data=data, headers=headers), timeout=30) as response:
        return json.load(response)


assert call("/health") == {"status": "ok"}
assert any(item["name"] == "Nobu (Demo)" for item in call("/restaurants")["restaurants"])
manager = call("/auth/login", {
    "email": "manager@tablekeeper.example", "password": "TablekeeperDemo2026!",
})["token"]
assert call("/restaurants/r_demo_week", token=manager)["can_manage_policies"]
assert not call("/restaurants/r_demo_week")["can_manage_policies"]
for path in ["/", "/login", "/signup", "/lookup", "/assets/source-sans-3.woff2",
             "/assets/restaurant-illustration.png"]:
    with urlopen(base + path, timeout=30) as response:
        assert response.status == 200 and response.read(), path
for path in ["/_test/export", "/_test/reset", "/_test/import"]:
    try:
        call(path, {} if path != "/_test/export" else None)
    except HTTPError as error:
        assert error.code == 404, path
    else:
        raise AssertionError("Public test control exposed: " + path)

token = call("/auth/signup", {
    "email": "vercel-check-" + secrets.token_hex(8) + "@example.com",
    "password": secrets.token_urlsafe(24), "display_name": "Deployment check",
})["token"]
day = (dt.date.today() + dt.timedelta(days=30)).isoformat()
availability = call("/availability?" + urlencode({
    "restaurant_id": "r_demo_week", "date": day, "party_size": 2,
}))
assert availability["slots"]
body = {"restaurant_id": "r_demo_week", "table_id": "demo_two",
        "starts_at_local": day + "T19:30", "party_size": 2}
key = secrets.token_hex(16)
reservation = call("/reservations", body, token, key)
try:
    assert call("/reservations", body, token, key) == reservation
    assert call("/reservations/" + reservation["reference"], token=token)["status"] == "confirmed"
finally:
    assert call("/reservations/" + reservation["reference"] + "/cancel", {}, token)["status"] == "cancelled"
print("PASS: pages/assets, health, seeded restaurant/manager, authorization, availability, signup, booking/retry, lookup, cancellation, blocked test controls")
