"""Vercel-only demo adapter; judged stage snapshots remain unchanged."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import psycopg
from psycopg.types.json import Jsonb

stage = Path(__file__).resolve().parents[1] / "stage-4"
os.environ["TABLEKEEPER_STATIC"] = str(stage / "web" / "dist")
os.environ["TABLEKEEPER_DB"] = str(Path(tempfile.gettempdir()) / "tablekeeper-vercel.sqlite3")

spec = importlib.util.spec_from_file_location("tablekeeper_stage4", stage / "server" / "app.py")
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)

database_url = os.environ["DATABASE_URL"]
fixture = json.loads((stage / "demo" / "multi-day-demo.json").read_text(encoding="utf-8"))

# Serialize schema initialization across concurrent cold starts; seed only once.
with psycopg.connect(database_url, connect_timeout=10) as connection:
    connection.execute("SELECT pg_advisory_xact_lock(795246631)")
    connection.execute("CREATE TABLE IF NOT EXISTS tablekeeper_demo_state (id integer PRIMARY KEY CHECK (id = 1), body jsonb NOT NULL)")
    if connection.execute("SELECT 1 FROM tablekeeper_demo_state WHERE id = 1").fetchone() is None:
        connection.execute("INSERT INTO tablekeeper_demo_state (id, body) VALUES (1, %s)", (Jsonb(service._fixture(fixture)),))


def read_state():
    with psycopg.connect(database_url, connect_timeout=10) as connection:
        return connection.execute("SELECT body FROM tablekeeper_demo_state WHERE id = 1").fetchone()[0]


def transaction(change):
    # ponytail: one locked state row serializes writes; split by restaurant if throughput matters.
    with psycopg.connect(database_url, connect_timeout=10) as connection:
        state = connection.execute("SELECT body FROM tablekeeper_demo_state WHERE id = 1 FOR UPDATE").fetchone()[0]
        result = change(state)
        encoded = Jsonb(state, dumps=lambda value: json.dumps(value, ensure_ascii=False, allow_nan=False))
        connection.execute("UPDATE tablekeeper_demo_state SET body = %s WHERE id = 1", (encoded,))
        return result


service.read_state = read_state
service.transaction = transaction
service._DB.close()

app = service.app
# Public deployments must not expose evaluation-only state controls.
app.router.routes[:] = [
    route for route in app.router.routes
    if not getattr(route, "path", "").startswith("/_test/")
]
