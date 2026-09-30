"use strict";

const assert = require("node:assert/strict");

module.exports = async function nativeZoomLayout(page, zoom) {
  const base = new URL(page.url()).origin;
  const weekdays = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
  const fixture = {
    users: [],
    restaurants: [{
      id: "r_native_zoom",
      name: "Native Zoom Test",
      timezone: "Europe/Berlin",
      slot_minutes: 30,
      reservation_duration_minutes: 90,
      cancellation_cutoff_minutes: 0,
      opening_hours: weekdays.map((weekday) => ({ weekday, opens: "18:00", closes: "23:00" })),
      tables: [
        { id: "t_native_close", label: "Window", capacity: 4 },
        { id: "t_native_destination", label: "Garden", capacity: 4 },
      ],
      combinable: [],
      manager_user_ids: [],
    }],
    reservations: [],
  };

  const reset = await page.evaluate(async (state) => (await fetch("/_test/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(state),
  })).status, fixture);
  assert.equal(reset, 204, "isolated zoom fixture reset");

  const manager = await page.evaluate(async () => {
    const response = await fetch("/auth/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: `native-zoom-${crypto.randomUUID()}@example.test`,
        password: `${crypto.randomUUID()}-Q9!`,
        display_name: "Zoom Test Manager",
      }),
    });
    if (response.status !== 201) throw new Error(`Manager setup returned ${response.status}`);
    return response.json();
  });
  const snapshot = await page.evaluate(async () => (await (await fetch("/_test/export")).json()));
  snapshot.state.restaurants[0].manager_user_ids = [manager.user_id];
  const imported = await page.evaluate(async (state) => (await fetch("/_test/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(state),
  })).status, snapshot);
  assert.equal(imported, 204, "manager membership setup");

  const booking = await page.evaluate(async (token) => {
    const day = new Date();
    day.setUTCDate(day.getUTCDate() + 42);
    const date = day.toISOString().slice(0, 10);
    const response = await fetch("/reservations", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify({
        restaurant_id: "r_native_zoom",
        table_id: "t_native_close",
        starts_at_local: `${date}T19:00`,
        party_size: 4,
      }),
    });
    if (response.status !== 201) throw new Error(`Booking setup returned ${response.status}`);
    return response.json();
  }, manager.token);
  const seriesResponse = await page.evaluate(async ({ reference, token }) => {
    const response = await fetch("/series", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify({ anchor_reference: reference, count: 4, interval_weeks: 1 }),
    });
    if (response.status !== 201 && response.status !== 200) {
      throw new Error(`Series setup returned ${response.status}`);
    }
    return response.json();
  }, { reference: booking.reference, token: manager.token });

  await page.evaluate((account) => {
    localStorage.setItem("tablekeeper.token", account.token);
    localStorage.setItem("tablekeeper.displayName", "Zoom Test Manager");
  }, manager);
  await page.reload();
  await page.goto(`${base}/#service-recovery`);
  await page.getByTestId("replan-form").waitFor({ state: "visible" });
  await page.getByTestId("policy-management").evaluate((details) => { details.open = true; });

  const sample = async (label, selectors) => {
    assert.equal(await zoom.getZoom(), 2, `${label}: native tab zoom`);
    const state = await page.evaluate((ids) => {
      const width = document.documentElement.clientWidth;
      const nodes = Object.fromEntries(ids.map((id) => {
        const node = id.startsWith(".")
          ? document.querySelector(id)
          : document.querySelector(`[data-testid="${CSS.escape(id)}"]`);
        if (!node) return [id, null];
        const rect = node.getBoundingClientRect();
        return [id, {
          visible: rect.width > 0 && rect.height > 0,
          bounds: [Math.round(rect.left), Math.round(rect.right)],
          width: node.clientWidth,
          scrollWidth: node.scrollWidth,
        }];
      }));
      return {
        viewport: [innerWidth, innerHeight],
        document: [width, document.documentElement.scrollWidth],
        horizontalOverflow: document.documentElement.scrollWidth > width,
        nodes,
      };
    }, selectors);
    assert.equal(state.horizontalOverflow, false, `${label}: document fits viewport ${JSON.stringify(state)}`);
    for (const id of selectors) assert.ok(state.nodes[id]?.visible, `${label}: visible ${id}`);
    for (const [id, node] of Object.entries(state.nodes)) {
      assert.ok(node.bounds[0] >= 0 && node.bounds[1] <= state.document[0], `${label}: ${id} remains within viewport`);
      assert.ok(node.scrollWidth <= node.width + 1, `${label}: ${id} has no internal horizontal clipping`);
    }
    return { label, ...state };
  };

  const layouts = [];
  const homePanels = ["service-recovery", "replan-form", "replan-preview-submit", ".hours-days", ".policy-form", ".policy-hours", ".policy-day", ".policy-numbers", ".policy-capacities"];
  layouts.push(await sample("recovery light", homePanels));
  await page.getByTestId("theme-toggle").evaluate((button) => button.click());
  layouts.push(await sample("recovery dark", homePanels));

  const day = booking.starts_at_local.slice(0, 10);
  await page.getByTestId("replan-table").selectOption("t_native_close");
  await page.getByTestId("replan-from").fill(`${day}T19:00`);
  await page.getByTestId("replan-to").fill(`${day}T20:30`);
  const previewResponse = page.waitForResponse((response) =>
    response.url().endsWith("/restaurants/r_native_zoom/replans") && response.request().method() === "POST");
  await page.getByTestId("replan-preview-submit").click();
  assert.equal((await previewResponse).status(), 201, "recovery preview submits at native zoom");
  await page.getByTestId("replan-preview").waitFor({ state: "visible" });
  const competitor = await page.evaluate(async ({ day, token }) => {
    const response = await fetch("/reservations", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify({
        restaurant_id: "r_native_zoom",
        table_id: "t_native_destination",
        starts_at_local: `${day}T19:00`,
        party_size: 4,
      }),
    });
    return { status: response.status, body: await response.json() };
  }, { day, token: manager.token });
  assert.equal(competitor.status, 201, "competing reservation setup");
  const applyResponse = page.waitForResponse((response) =>
    response.url().endsWith("/apply") && response.request().method() === "POST");
  await page.getByTestId("replan-apply").click();
  assert.equal((await applyResponse).status(), 409, "stale plan refusal is surfaced at native zoom");
  const feedback = await page.getByTestId("replan-apply-error").evaluate((node) => {
    const rect = node.getBoundingClientRect();
    const headerBottom = document.querySelector(".site-header").getBoundingClientRect().bottom;
    return {
      role: node.getAttribute("role"),
      focused: document.activeElement === node,
      bounds: [Math.round(rect.top), Math.round(rect.bottom)],
      headerBottom: Math.round(headerBottom),
      viewportHeight: innerHeight,
    };
  });
  assert.equal(feedback.role, "alert", "stale-plan feedback is an alert");
  assert.equal(feedback.focused, true, "stale-plan feedback receives focus");
  assert.ok(feedback.bounds[0] >= feedback.headerBottom && feedback.bounds[1] <= feedback.viewportHeight,
    `stale-plan feedback stays visible below the sticky header: ${JSON.stringify(feedback)}`);
  assert.equal(await page.getByTestId("replan-table").inputValue(), "t_native_close");
  assert.equal(await page.getByTestId("replan-from").inputValue(), `${day}T19:00`);
  assert.equal(await page.getByTestId("replan-to").inputValue(), `${day}T20:30`);

  await page.goto(`${base}/lookup?reference=${encodeURIComponent(booking.reference)}&series_id=${encodeURIComponent(seriesResponse.series_id)}`);
  await page.getByTestId("lookup-reference-input").fill(booking.reference);
  await Promise.all([
    page.waitForResponse((response) => response.url().endsWith(`/reservations/${booking.reference}`)),
    page.getByTestId("lookup-submit").evaluate((button) => button.click()),
  ]);
  await page.getByTestId("series-amend-form").waitFor({ state: "visible" });
  layouts.push(await sample("series dark", ["series-panel", "series-amend-form", "series-amend-submit", "series-occurrences", "series-occurrence-0"]));
  await page.getByTestId("theme-toggle").evaluate((button) => button.click());
  layouts.push(await sample("series light", ["series-panel", "series-amend-form", "series-amend-submit", "series-occurrences", "series-occurrence-0"]));

  return {
    ok: layouts.every((layout) => !layout.horizontalOverflow),
    exactZoom: await zoom.getZoom(),
    staleFeedback: feedback,
    layouts,
  };
};
