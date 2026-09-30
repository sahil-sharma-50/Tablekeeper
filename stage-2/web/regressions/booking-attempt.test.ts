import assert from "node:assert/strict";
import test from "node:test";
import { clearSupersededRejection } from "../src/booking-attempt.ts";

test("clears a rejected booking when its selected request body changes", () => {
  const refused = { status: "rejected", body: { table_id: "t_d", starts_at_local: "2026-10-14T19:00", party_size: 4 } };
  const next = { table_id: "t_d", starts_at_local: "2026-10-14T21:00", party_size: 4 };
  assert.equal(clearSupersededRejection(refused, next), null);
});

test("keeps same-body rejection and preserves uncertain request identity", () => {
  const rejected = { status: "rejected", key: "rejected-key", body: { table_id: "t_d", starts_at_local: "2026-10-14T19:00", party_size: 4 } };
  const uncertain = { ...rejected, status: "uncertain", key: "uncertain-key" };
  assert.equal(clearSupersededRejection(rejected, { ...rejected.body }), rejected);
  assert.equal(clearSupersededRejection(uncertain, { table_id: "t_d", starts_at_local: "2026-10-14T21:00", party_size: 4 }), uncertain);
});
