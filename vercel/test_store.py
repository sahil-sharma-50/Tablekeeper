"""Check shared storage using a disposable LOCAL Postgres database only."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

database_url = os.environ["TABLEKEEPER_TEST_DATABASE_URL"]
assert urlsplit(database_url).hostname in {"localhost", "127.0.0.1", "host.docker.internal"}, "Use a disposable local database"
os.environ["DATABASE_URL"] = database_url
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vercel import entrypoint as store

assert store.read_state()["restaurants"][0]["name"] == "Nobu (Demo)"
assert not any(getattr(route, "path", "").startswith("/_test/") for route in store.app.routes)
store.transaction(lambda state: state.update(_store_test_counter=0))


def increment(_):
    def change(state):
        state["_store_test_counter"] += 1
    store.transaction(change)


with ThreadPoolExecutor(max_workers=8) as pool:
    list(pool.map(increment, range(16)))
assert store.read_state()["_store_test_counter"] == 16, "Concurrent writes lost data"


def fail(state):
    state["_store_test_counter"] = -1
    raise ValueError("deliberate rollback")


try:
    store.transaction(fail)
except ValueError:
    pass
else:
    raise AssertionError("Callback failure was swallowed")
assert store.read_state()["_store_test_counter"] == 16, "Failed transaction committed"
subprocess.run([sys.executable, "-c", "from vercel.entrypoint import read_state; assert read_state()['_store_test_counter'] == 16"],
               cwd=Path(__file__).resolve().parents[1], check=True)
store.transaction(lambda state: state.pop("_store_test_counter"))
print("PASS: seed, hidden test controls, concurrent writes, rollback, fresh-process persistence")
