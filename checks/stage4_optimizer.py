#!/usr/bin/env python3
"""Small exact reference optimizer for Stage 4 seating-repair plans."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Booking:
    reference: str
    starts_at: datetime
    ends_at: datetime
    party_size: int
    table_ids: tuple[str, ...]
    accepted_capacities: Mapping[str, int]


@dataclass(frozen=True)
class Occupancy:
    starts_at: datetime
    ends_at: datetime
    table_ids: tuple[str, ...]


@dataclass(frozen=True)
class Closure:
    table_id: str
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True)
class Option:
    table_ids: tuple[str, ...]
    rank: int


@dataclass(frozen=True)
class Solution:
    assignments: Mapping[str, tuple[str, ...]]
    moved_count: int
    unused_seats: int
    rank_vector: tuple[int, ...]


def _overlap(a_start: datetime, a_end: datetime,
             b_start: datetime, b_end: datetime) -> bool:
    if any(value.utcoffset() is None for value in (a_start, a_end, b_start, b_end)):
        raise ValueError("optimizer intervals must have explicit UTC offsets")
    # Normalize explicitly: same-zone aware datetimes compare wall time across a
    # DST fold, while the contract is about instants supplied with offsets.
    a_start, a_end = a_start.astimezone(timezone.utc), a_end.astimezone(timezone.utc)
    b_start, b_end = b_start.astimezone(timezone.utc), b_end.astimezone(timezone.utc)
    return a_start < b_end and b_start < a_end


def options(singles: Sequence[str], pairs: Sequence[Sequence[str]]) -> tuple[Option, ...]:
    """Return the only legal assignments in the contract's rank order."""
    result = [Option((table_id,), rank) for rank, table_id in enumerate(singles)]
    seen = {frozenset(option.table_ids) for option in result}
    for pair in pairs:
        tables = tuple(pair)
        if len(tables) != 2 or len(set(tables)) != 2:
            raise ValueError("each declared pair must name two distinct tables")
        if frozenset(tables) in seen:
            raise ValueError("a declared pair duplicates an existing option")
        seen.add(frozenset(tables))
        result.append(Option(tables, len(result)))
    return tuple(result)


def optimize(singles: Sequence[str], pairs: Sequence[Sequence[str]],
             considered: Sequence[Booking], *, fixed: Sequence[Occupancy] = (),
             closures: Sequence[Closure] = (),
             proposed: Closure | None = None) -> Solution | None:
    """Enumerate every feasible assignment and minimize the exact 3-part objective."""
    ranked = options(singles, pairs)
    all_closures = tuple(closures) + ((proposed,) if proposed is not None else ())
    bookings = tuple(sorted(considered, key=lambda booking: booking.reference))
    best_key: tuple[int, int, tuple[int, ...]] | None = None
    best: Solution | None = None
    picked: list[Option] = []

    def visit(index: int, moved: int, unused: int) -> None:
        nonlocal best_key, best
        if best_key is not None and moved > best_key[0]:
            return
        if index == len(bookings):
            vector = tuple(option.rank for option in picked)
            score = (moved, unused, vector)
            if best_key is None or score < best_key:
                best_key = score
                best = Solution(
                    assignments={booking.reference: option.table_ids
                                 for booking, option in zip(bookings, picked)},
                    moved_count=moved,
                    unused_seats=unused,
                    rank_vector=vector,
                )
            return

        booking = bookings[index]
        old_tables = frozenset(booking.table_ids)
        for option in ranked:
            assigned = frozenset(option.table_ids)
            capacity = sum(booking.accepted_capacities.get(table, 0)
                           for table in option.table_ids)
            if capacity < booking.party_size:
                continue
            if any(closure.table_id in assigned and
                   _overlap(booking.starts_at, booking.ends_at,
                            closure.starts_at, closure.ends_at)
                   for closure in all_closures):
                continue
            if any(assigned.intersection(occupancy.table_ids) and
                   _overlap(booking.starts_at, booking.ends_at,
                            occupancy.starts_at, occupancy.ends_at)
                   for occupancy in fixed):
                continue
            conflict = False
            for earlier, earlier_option in zip(bookings[:index], picked):
                if assigned.intersection(earlier_option.table_ids) and _overlap(
                        booking.starts_at, booking.ends_at,
                        earlier.starts_at, earlier.ends_at):
                    conflict = True
                    break
            if conflict:
                continue
            picked.append(option)
            visit(index + 1,
                  moved + (assigned != old_tables),
                  unused + capacity - booking.party_size)
            picked.pop()

    visit(0, 0, 0)
    return best


def _time(hour: int, minute: int = 0) -> datetime:
    return datetime(2030, 1, 1, hour, minute, tzinfo=timezone.utc)


def _booking(reference: str, tables: tuple[str, ...], party: int,
             capacities: Mapping[str, int], start: int = 18,
             end: int = 20) -> Booking:
    return Booking(reference, _time(start), _time(end), party, tables, capacities)


def self_check() -> None:
    # Keeping an existing assignment beats any tighter-capacity move.
    kept = optimize(["t1", "t2"], [], [
        _booking("A", ("t1",), 4, {"t1": 8, "t2": 4})])
    assert kept and kept.assignments == {"A": ("t1",)}
    assert (kept.moved_count, kept.unused_seats, kept.rank_vector) == (0, 4, (0,))

    # Accepted capacities belong to each booking; they are not one live shared policy.
    per_booking = optimize(["t1", "t2"], [], [
        _booking("A", ("t2",), 6, {"t1": 1, "t2": 6}),
        _booking("B", ("t1",), 6, {"t1": 6, "t2": 1}),
    ])
    assert per_booking and per_booking.assignments == {"A": ("t2",), "B": ("t1",)}
    assert per_booking.moved_count == 0

    # With moved count tied, unused seats outrank the option-rank vector.
    seat_fit = optimize(["old", "rank0", "rank1"], [], [
        _booking("A", ("old",), 4, {"old": 9, "rank0": 8, "rank1": 5})],
        proposed=Closure("old", _time(17), _time(21)))
    assert seat_fit and seat_fit.assignments["A"] == ("rank1",)
    assert (seat_fit.moved_count, seat_fit.unused_seats) == (1, 1)

    # With both preceding objective parts tied, ranks are compared in reference order.
    rank_tie = optimize(["t1", "t2", "oldA", "oldB"], [], [
        _booking("B", ("oldB",), 2,
                 {"t1": 2, "t2": 2, "oldA": 2, "oldB": 2}),
        _booking("A", ("oldA",), 2,
                 {"t1": 2, "t2": 2, "oldA": 2, "oldB": 2}),
    ], closures=[Closure("oldB", _time(17), _time(21))],
        proposed=Closure("oldA", _time(17), _time(21)))
    assert rank_tie and rank_tie.assignments == {"A": ("t1",), "B": ("t2",)}
    assert rank_tie.rank_vector == (0, 1)

    # Fixed occupancy and half-open closure boundaries are both respected.
    fixed = optimize(["t1", "t2"], [], [
        _booking("A", ("t1",), 2, {"t1": 2, "t2": 2})],
        fixed=[Occupancy(_time(18), _time(20), ("t1",))])
    assert fixed and fixed.assignments["A"] == ("t2",)
    boundary = optimize(["t1"], [], [
        _booking("A", ("t1",), 2, {"t1": 2}, start=20, end=21)],
        proposed=Closure("t1", _time(18), _time(20)))
    assert boundary and boundary.moved_count == 0

    # The repeated Berlin wall clock hour still contains two distinct instants.
    berlin = ZoneInfo("Europe/Berlin")
    fold_early = datetime(2026, 10, 25, 2, 15, tzinfo=berlin, fold=0)
    fold_late = datetime(2026, 10, 25, 2, 15, tzinfo=berlin, fold=1)
    assert _overlap(fold_early, fold_early.replace(minute=45),
                    fold_late, fold_late.replace(minute=45)) is False

    # Declared pairs are ranked after singles and non-transitive combinations stay absent.
    choices = options(["t1", "t2", "t3"], [("t1", "t2"), ("t2", "t3")])
    assert [option.rank for option in choices] == list(range(5))
    assert frozenset(("t1", "t3")) not in {
        frozenset(option.table_ids) for option in choices
    }
    no_plan = optimize(["t1"], [], [
        _booking("A", ("t1",), 1, {"t1": 1})],
        proposed=Closure("t1", _time(17), _time(21)))
    assert no_plan is None
    print("PASS Stage 4 exact optimizer: movement, capacity, ranks, fixed occupancy, closures, pairs and no-plan")


if __name__ == "__main__":
    self_check()
