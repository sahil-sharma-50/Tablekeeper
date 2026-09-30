#!/usr/bin/env python3
"""Check the opt-in seven-day demo fixture against a disposable Stage 2 service."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from urllib.parse import urlencode

import stage1_independent as s1


WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--fixture", required=True, type=Path)
    args = parser.parse_args()

    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    assert fixture["users"] == [] and fixture["reservations"] == []
    restaurant, = fixture["restaurants"]
    assert [entry["weekday"] for entry in restaurant["opening_hours"]] == list(WEEKDAYS)
    assert restaurant["combinable"] == [["demo_two", "demo_four"]]

    s1.expect_empty_204(s1.call(args.base_url, "/_test/reset", "POST", fixture,
                                 timeout=10), "/_test/reset")
    listing = s1.expect(s1.call(args.base_url, "/restaurants"), 200).body
    assert [row["id"] for row in listing["restaurants"]] == [restaurant["id"]]

    first_monday = dt.date(2026, 10, 5)
    for offset, weekday in enumerate(WEEKDAYS):
        day = first_monday + dt.timedelta(days=offset)
        query = urlencode({"restaurant_id": restaurant["id"],
                           "date": day.isoformat(), "party_size": 4})
        reply = s1.expect(s1.call(args.base_url, f"/availability?{query}"), 200)
        slots = reply.body["slots"]
        assert len(slots) == 8, (day, len(slots))
        assert [slot["starts_at_local"][-5:] for slot in slots] == [
            (dt.datetime.combine(day, dt.time(17, 0)) +
             dt.timedelta(minutes=30 * index)).strftime("%H:%M")
            for index in range(8)]
        for slot in slots:
            assert slot["available_table_ids"] == ["demo_four", "demo_six"]
            assert slot["available_options"] == [
                {"table_ids": ["demo_four"], "capacity": 4},
                {"table_ids": ["demo_six"], "capacity": 6},
                {"table_ids": ["demo_two", "demo_four"], "capacity": 6},
            ]
        print(f"PASS {day.isoformat()} ({weekday}) 8 slots, singles and declared pair")

    print("PASS opt-in demo fixture: empty users/reservations, seven weekdays, correct availability")


if __name__ == "__main__":
    main()
