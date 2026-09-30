"use strict";

const assert = require("node:assert/strict");

const RID = "r_stage4_qa";
const weekdays = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

function dateAfter(days) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Berlin", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date()).map((part) => [part.type, part.value]));
  const date = new Date(`${parts.year}-${parts.month}-${parts.day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

async function measured(page, zoom, label, selectors) {
  assert.equal(await zoom.getZoom(), 2, `${label}: native tab zoom`);
  const state = await page.evaluate((ids) => {
    const nodes = {};
    for (const id of ids) {
      const node = document.querySelector(`[data-testid="${CSS.escape(id)}"]`);
      if (!node) { nodes[id] = null; continue; }
      const rect = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      const contents = node.matches('[data-testid^="series-occurrence-"]')
        ? node.querySelector(":scope > div") : null;
      nodes[id] = {
        visible: style.display !== "none" && style.visibility !== "hidden" &&
          rect.width > 0 && rect.height > 0,
        bounds: [Math.round(rect.x), Math.round(rect.y),
          Math.round(rect.width), Math.round(rect.height)],
        scrollWidth: node.scrollWidth,
        clientWidth: node.clientWidth,
        textOverflow: contents ? contents.scrollWidth > contents.clientWidth : false,
        role: node.getAttribute("role"),
      };
    }
    return {
      cssViewport: [innerWidth, innerHeight],
      devicePixelRatio,
      theme: document.documentElement.dataset.theme,
      focused: document.activeElement?.dataset?.testid || document.activeElement?.tagName || null,
      document: [document.documentElement.clientWidth, document.documentElement.scrollWidth],
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      overflowNodes: Array.from(document.querySelectorAll("body *"))
        .map((node) => {
          const rect = node.getBoundingClientRect();
          return { testid: node.getAttribute("data-testid"),
            className: typeof node.className === "string" ? node.className : "",
            tag: node.tagName.toLowerCase(), left: Math.round(rect.left),
            right: Math.round(rect.right), clientWidth: node.clientWidth,
            scrollWidth: node.scrollWidth };
        })
        .filter((node) => node.right > document.documentElement.clientWidth + 1 ||
          node.scrollWidth > node.clientWidth + 1)
        .slice(0, 40),
      nodes,
    };
  }, selectors);
  for (const id of selectors) assert.ok(state.nodes[id]?.visible, `${label}: visible ${id}`);
  return { label, tabZoom: 2, ...state };
}

module.exports = async function stage4BrowserRecheck(page, zoom) {
  const base = new URL(page.url()).origin;
  const fixture = {
    users: [],
    restaurants: [{
      id: RID, name: "Stage Four QA Restaurant", timezone: "Europe/Berlin",
      slot_minutes: 30, reservation_duration_minutes: 90,
      cancellation_cutoff_minutes: 0,
      opening_hours: weekdays.map((weekday) => ({ weekday, opens: "18:00", closes: "23:00" })),
      tables: [
        { id: "t_1", label: "A", capacity: 2 },
        { id: "t_2", label: "B", capacity: 4 },
        { id: "t_3", label: "C", capacity: 6 },
      ],
      combinable: [["t_1", "t_2"], ["t_2", "t_3"]],
      manager_user_ids: [],
    }],
    reservations: [],
  };
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
  const reset = await page.evaluate(async (state) => (await fetch("/_test/reset", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(state),
  })).status, fixture);
  assert.equal(reset, 204, "isolated browser fixture reset");
  await page.goto(base);

  const accounts = await page.evaluate(async () => {
    const create = async (label) => {
      const suffix = crypto.randomUUID();
      const response = await fetch("/auth/signup", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: `s4-${label}-${suffix}@example.test`,
          password: `${crypto.randomUUID()}-Q9!`, display_name: `QA ${label}` }),
      });
      if (response.status !== 201) throw new Error(`QA signup failed (${response.status})`);
      return response.json();
    };
    const manager = await create("manager");
    const diner = await create("diner");
    const snapshot = await (await fetch("/_test/export")).json();
    snapshot.state.restaurants[0].manager_user_ids = [manager.user_id];
    const imported = await fetch("/_test/import", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(snapshot),
    });
    if (imported.status !== 204) throw new Error(`QA authorization setup failed (${imported.status})`);
    return { manager: { userId: manager.user_id, token: manager.token },
      diner: { userId: diner.user_id, token: diner.token } };
  });

  const setAccount = async (account) => {
    await page.evaluate((value) => {
      localStorage.setItem("tablekeeper.token", value.token);
      localStorage.setItem("tablekeeper.displayName", `QA ${value.label}`);
      sessionStorage.clear();
    }, account);
    await page.goto(base);
  };
  await page.evaluate(() => {
    localStorage.removeItem("tablekeeper.token");
    localStorage.removeItem("tablekeeper.displayName");
  });
  await page.goto(base);
  assert.equal(await page.getByTestId("recovery-auth-required").count(), 1,
    "anonymous view explains manager sign-in requirement");
  const rolePicker = await page.locator("select").evaluateAll((nodes) => nodes.some((node) =>
    /role|account type/i.test(node.labels?.[0]?.innerText || node.parentElement?.innerText || "")));
  assert.equal(rolePicker, false, "no public role picker");
  const anonymousStatus = await page.evaluate(async () => (await fetch(
    `/restaurants/${"r_stage4_qa"}/replans`, { method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ table_id: "t_2", from: "2026-10-20T18:00:00+02:00",
        to: "2026-10-20T19:00:00+02:00" }) })).status);
  assert.equal(anonymousStatus, 401, "anonymous replan is denied by the server");

  await setAccount({ ...accounts.diner, label: "Diner" });
  await page.getByTestId("recovery-manager-access").waitFor({ state: "visible" });
  assert.equal(await page.getByTestId("replan-form").count(), 0,
    "diner has no replan form");
  assert.equal(await page.getByTestId("policy-publish-form").count(), 0,
    "diner has no policy publication form");
  const dinerStatus = await page.evaluate(async (token) => (await fetch(
    `/restaurants/${"r_stage4_qa"}/replans`, { method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID(),
        Authorization: `Bearer ${token}` },
      body: JSON.stringify({ table_id: "t_2", from: "2026-10-20T18:00:00+02:00",
        to: "2026-10-20T19:00:00+02:00" }) })).status, accounts.diner.token);
  assert.equal(dinerStatus, 403, "diner replan is denied by the server");

  await setAccount({ ...accounts.manager, label: "Manager" });
  await page.getByTestId("replan-form").waitFor({ state: "visible" });
  const date = dateAfter(14);
  const effectiveDate = dateAfter(30);
  await page.getByTestId("date-input").fill(date);
  await page.getByTestId("party-size-input").fill("4");
  const searchResponse = page.waitForResponse((response) =>
    response.url().includes("/availability?") && response.request().method() === "GET");
  await page.getByTestId("search-button").click();
  assert.equal((await searchResponse).status(), 200);
  const cell = page.getByTestId("slot-t_2-19:00");
  assert.equal(await cell.getAttribute("data-available"), "true");
  await cell.click();
  const bookingResponse = page.waitForResponse((response) =>
    response.url().endsWith("/reservations") && response.request().method() === "POST");
  await page.getByTestId("booking-submit").click();
  const booked = await bookingResponse;
  assert.equal(booked.status(), 201);
  const reservation = await booked.json();
  await page.getByTestId("confirmation").waitFor({ state: "visible" });
  const reference = reservation.reference;

  // A no-assignment preview becomes stale after a real policy revision. The error
  // must be visible, announced, and focused below the sticky header.
  await page.getByTestId("replan-table").selectOption("t_1");
  await page.getByTestId("replan-from").fill(`${date}T18:00`);
  await page.getByTestId("replan-to").fill(`${date}T18:30`);
  const emptyPreviewResponse = page.waitForResponse((response) =>
    response.url().endsWith(`/restaurants/${RID}/replans`) && response.request().method() === "POST");
  await page.getByTestId("replan-preview-submit").click();
  const emptyPreview = await emptyPreviewResponse;
  assert.equal(emptyPreview.status(), 201);
  assert.deepEqual((await emptyPreview.json()).assignments, []);
  await page.getByTestId("policy-management").locator("summary").click();
  await page.getByTestId("policy-effective-from").fill(effectiveDate);
  const policyResponse = page.waitForResponse((response) =>
    response.url().endsWith(`/restaurants/${RID}/policies`) && response.request().method() === "POST");
  await page.getByTestId("policy-publish").click();
  assert.equal((await policyResponse).status(), 201);
  await page.getByTestId("policy-success").waitFor({ state: "visible" });
  const staleResponse = page.waitForResponse((response) =>
    response.url().includes("/replans/") && response.url().endsWith("/apply"));
  await page.getByTestId("replan-apply").click();
  const staleReply = await staleResponse;
  assert.equal(staleReply.status(), 409);
  assert.equal((await staleReply.json()).error.code, "stale_plan");
  const staleFeedback = page.getByTestId("replan-apply-error");
  await staleFeedback.waitFor({ state: "visible" });
  const staleGeometry = await staleFeedback.evaluate((node) => {
    const rect = node.getBoundingClientRect();
    const header = document.querySelector(".site-header")?.getBoundingClientRect();
    return { role: node.getAttribute("role"), focused: document.activeElement === node,
      bounds: [Math.round(rect.x), Math.round(rect.y), Math.round(rect.width), Math.round(rect.height)],
      headerBottom: Math.round(header?.bottom || 0),
      visible: rect.top >= 0 && rect.bottom <= innerHeight };
  });
  assert.equal(staleGeometry.role, "alert");
  assert.equal(staleGeometry.focused, true);
  assert.equal(staleGeometry.visible, true);
  assert.ok(staleGeometry.bounds[1] >= staleGeometry.headerBottom,
    "stale feedback clears the sticky header");
  assert.equal(await page.getByTestId("replan-apply").count(), 0,
    "stale preview cannot be applied again");

  const lightPreviewLayout = await measured(page, zoom, "manager replan controls light",
    ["service-recovery", "replan-form"]);
  await page.getByTestId("theme-toggle").click();
  assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");

  // Close the booked table during the booking interval. Drop the successful
  // preview response, then ensure retry preserves its exact body and key.
  await page.getByTestId("replan-table").selectOption("t_2");
  await page.getByTestId("replan-from").fill(`${date}T19:00`);
  await page.getByTestId("replan-to").fill(`${date}T20:30`);
  const previewUrl = `**/restaurants/${RID}/replans`;
  let firstPreview;
  await page.route(previewUrl, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    firstPreview = { body: route.request().postDataJSON(),
      key: route.request().headers()["idempotency-key"], status: (await route.fetch()).status() };
    assert.equal(firstPreview.status, 201);
    await route.abort("failed");
  });
  await page.getByTestId("replan-preview-submit").click();
  await page.getByTestId("replan-preview-uncertain").waitFor({ state: "visible" });
  const savedPreview = await page.evaluate(() => JSON.parse(
    sessionStorage.getItem("tablekeeper.replanPreviewAttempt")));
  assert.equal(savedPreview.status, "uncertain");
  assert.deepEqual(savedPreview.body, firstPreview.body);
  assert.equal(savedPreview.key, firstPreview.key);
  await page.unroute(previewUrl);
  let retriedPreview;
  await page.route(previewUrl, async (route) => {
    if (route.request().method() === "POST") retriedPreview = {
      body: route.request().postDataJSON(), key: route.request().headers()["idempotency-key"],
    };
    await route.continue();
  });
  const retryPreviewResponse = page.waitForResponse((response) =>
    response.url().endsWith(`/restaurants/${RID}/replans`) && response.request().method() === "POST");
  await page.getByTestId("replan-preview-submit").click();
  const retryPreview = await retryPreviewResponse;
  assert.equal(retryPreview.status(), 200, "preview retry replays the committed original");
  assert.deepEqual(retriedPreview, { body: firstPreview.body, key: firstPreview.key });
  const plan = await retryPreview.json();
  await page.unroute(previewUrl);
  assert.equal(plan.assignments.length, 1);
  assert.deepEqual(Object.keys(plan.assignments[0]).sort(), ["changed", "reference", "table_ids"]);
  assert.equal(plan.assignments[0].reference, reference);
  assert.equal(plan.assignments[0].changed, true);
  assert.equal(plan.assignments[0].table_ids.includes("t_2"), false);
  const assignmentRow = page.getByTestId(`replan-assignment-${reference}`);
  await assignmentRow.waitFor({ state: "visible" });
  const assignmentText = await assignmentRow.innerText();
  assert.match(assignmentText, /Prior table assignment is not available/,
    "the preview does not invent an unavailable prior assignment");
  const afterLabel = plan.assignments[0].table_ids.map((id) =>
    ({ t_1: "A", t_2: "B", t_3: "C" })[id]).join(" + ");
  assert.ok(assignmentText.includes(`After: ${afterLabel}`), "preview shows proposed destination");
  assert.match(await page.getByTestId("replan-preview").innerText(), /Read-only plan preview/);
  const previewLayout = await measured(page, zoom, "native zoom plan preview dark",
    ["replan-preview", `replan-assignment-${reference}`]);

  // Drop the committed apply response and retry the original request.
  const applyUrl = `**/restaurants/${RID}/replans/${plan.plan_id}/apply`;
  let firstApply;
  await page.route(applyUrl, async (route) => {
    firstApply = { body: route.request().postDataJSON(),
      key: route.request().headers()["idempotency-key"], status: (await route.fetch()).status() };
    assert.equal(firstApply.status, 201);
    await route.abort("failed");
  });
  await page.getByTestId("replan-apply").click();
  await page.getByTestId("replan-apply-uncertain").waitFor({ state: "visible" });
  const savedApply = await page.evaluate(() => JSON.parse(
    sessionStorage.getItem("tablekeeper.replanApplyAttempt")));
  assert.equal(savedApply.status, "uncertain");
  assert.deepEqual(savedApply.body, firstApply.body);
  assert.equal(savedApply.key, firstApply.key);
  await page.unroute(applyUrl);
  let retriedApply;
  await page.route(applyUrl, async (route) => {
    retriedApply = { body: route.request().postDataJSON(),
      key: route.request().headers()["idempotency-key"] };
    await route.continue();
  });
  const retryApplyResponse = page.waitForResponse((response) =>
    response.url().endsWith(`/replans/${plan.plan_id}/apply`));
  await page.getByTestId("replan-apply").click();
  const retryApply = await retryApplyResponse;
  assert.equal(retryApply.status(), 200, "apply retry replays the committed original");
  assert.deepEqual(retriedApply, { body: firstApply.body, key: firstApply.key });
  const applied = await retryApply.json();
  await page.unroute(applyUrl);
  assert.equal(applied.reservations.length, 1);
  assert.deepEqual(applied.reservations[0].table_ids, plan.assignments[0].table_ids);
  await page.getByTestId("replan-applied").waitFor({ state: "visible" });
  assert.match(await page.getByTestId("replan-applied").innerText(), /accepted policy 0/);
  const appliedLayout = await measured(page, zoom, "native zoom applied plan dark",
    ["replan-preview", "replan-applied"]);

  // Lookup must show the current post-plan table, time and accepted terms.
  await page.goto(`${base}/lookup`);
  await page.getByTestId("lookup-reference-input").fill(reference);
  const lookupResponse = page.waitForResponse((response) =>
    response.url().endsWith(`/reservations/${reference}`) && response.request().method() === "GET");
  await page.getByTestId("lookup-submit").click();
  assert.equal((await lookupResponse).status(), 200);
  await page.getByTestId("reservation-detail").waitFor({ state: "visible" });
  assert.equal((await page.getByTestId("reservation-status").innerText()).trim(), "confirmed");
  assert.equal((await page.getByTestId("reservation-tables").innerText()).trim(), afterLabel);
  assert.equal((await page.getByTestId("reservation-detail").innerText()).includes(`${date} · 19:00`), true);
  assert.equal(await page.getByTestId("series-create-form").count(), 1);
  const createSeriesResponse = page.waitForResponse((response) =>
    response.url().endsWith("/series") && response.request().method() === "POST");
  await page.getByTestId("series-count").selectOption("4");
  await page.getByTestId("series-create").click();
  const createdSeries = await createSeriesResponse;
  assert.equal(createdSeries.status(), 201);
  const series = await createdSeries.json();
  const seriesId = series.series_id;
  const refs = series.occurrences.map((item) => item.reservation.reference);
  assert.equal(series.occurrences.length, 4);

  // Owner privacy holds for history, terms and series; another valid account
  // sees the same not-found result as an anonymous visitor.
  const privacy = await page.evaluate(async ({ id, ref, otherToken }) => {
    const paths = [`/series/${id}`, `/reservations/${ref}/history`,
      `/reservations/${ref}/decision`];
    const status = async (path, token) => (await fetch(path, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })).status;
    return {
      anonymous: await Promise.all(paths.map((path) => status(path, ""))),
      otherOwner: await Promise.all(paths.map((path) => status(path, otherToken))),
    };
  }, { id: seriesId, ref: reference, otherToken: accounts.diner.token });
  assert.deepEqual(privacy.anonymous, [404, 404, 404]);
  assert.deepEqual(privacy.otherOwner, [404, 404, 404]);

  // Mark visit two as an independent exception through the real Stage 3 move
  // contract, then reload the series in the browser.
  const exceptionMove = await page.evaluate(async ({ ref, token }) => {
    const response = await fetch("/reservation-moves", {
      method: "POST", headers: { "Content-Type": "application/json",
        "Idempotency-Key": crypto.randomUUID(), Authorization: `Bearer ${token}` },
      body: JSON.stringify({ moves: [{ reference: ref, table_id: "t_2", expected_revision: 1 }] }),
    });
    return response.status;
  }, { ref: refs[1], token: accounts.manager.token });
  assert.equal(exceptionMove, 201);
  await page.goto(`${base}/lookup?reference=${encodeURIComponent(reference)}&series_id=${encodeURIComponent(seriesId)}`);
  await page.getByTestId("lookup-reference-input").fill(reference);
  const reloadLookup = page.waitForResponse((response) =>
    response.url().endsWith(`/reservations/${reference}`) && response.request().method() === "GET");
  await page.getByTestId("lookup-submit").click();
  assert.equal((await reloadLookup).status(), 200);
  await page.getByTestId("series-panel").waitFor({ state: "visible" });
  await page.getByTestId("series-exception-1").waitFor({ state: "visible" });
  assert.match(await page.getByTestId("series-occurrence-1").innerText(), /changed independently/i);

  // One click cancels a future occurrence; the cancelled row stays visible and
  // its action disappears.
  const cancelResponse = page.waitForResponse((response) =>
    response.url().endsWith(`/reservations/${refs[2]}/cancel`) && response.request().method() === "POST");
  await page.getByTestId("series-cancel-2").click();
  assert.equal((await cancelResponse).status(), 200);
  await page.getByTestId("series-cancel-2").waitFor({ state: "detached" });
  const cancelledRow = page.getByTestId("series-occurrence-2");
  assert.match(await cancelledRow.innerText(), /cancelled/i);
  assert.equal(await page.getByTestId("series-cancel-2").count(), 0);

  // The committed series amendment response is lost once. The exact original
  // body/key must recover it without repeating revisions or changing identity.
  await page.getByTestId("series-amend-from").selectOption("0");
  await page.getByTestId("series-amend-time").fill("20:00");
  const amendUrl = `**/series/${seriesId}/amend`;
  let firstAmend;
  await page.route(amendUrl, async (route) => {
    firstAmend = { body: route.request().postDataJSON(),
      key: route.request().headers()["idempotency-key"], status: (await route.fetch()).status() };
    assert.equal(firstAmend.status, 201);
    await route.abort("failed");
  });
  await page.getByTestId("series-amend-submit").click();
  await page.getByTestId("series-amend-uncertain").waitFor({ state: "visible" });
  const savedAmend = await page.evaluate(() => JSON.parse(
    sessionStorage.getItem("tablekeeper.seriesAmendAttempt")));
  assert.equal(savedAmend.status, "uncertain");
  assert.deepEqual(savedAmend.body, firstAmend.body);
  assert.equal(savedAmend.key, firstAmend.key);
  await page.unroute(amendUrl);
  let retriedAmend;
  await page.route(amendUrl, async (route) => {
    retriedAmend = { body: route.request().postDataJSON(),
      key: route.request().headers()["idempotency-key"] };
    await route.continue();
  });
  const retryAmendResponse = page.waitForResponse((response) =>
    response.url().endsWith(`/series/${seriesId}/amend`));
  await page.getByTestId("series-amend-submit").click();
  const retryAmend = await retryAmendResponse;
  assert.equal(retryAmend.status(), 200);
  assert.deepEqual(retriedAmend, { body: firstAmend.body, key: firstAmend.key });
  const amendment = await retryAmend.json();
  await page.unroute(amendUrl);
  await page.getByTestId("series-amend-success").waitFor({ state: "visible" });
  assert.equal(await page.getByTestId("series-amend-success").getAttribute("role"), "status");
  assert.equal(amendment.occurrences[0].reservation.starts_at_local.endsWith("T20:00"), true);
  assert.equal(amendment.occurrences[1].exception, true);
  assert.equal(amendment.occurrences[2].reservation.status, "cancelled");
  assert.equal(amendment.occurrences[3].reservation.starts_at_local.endsWith("T20:00"), true);
  for (const index of [0, 3]) {
    assert.equal(amendment.occurrences[index].reservation.starts_at_local.slice(0, 10),
      series.occurrences[index].reservation.starts_at_local.slice(0, 10));
    assert.deepEqual(amendment.occurrences[index].reservation.table_ids,
      series.occurrences[index].reservation.table_ids);
  }
  await page.getByTestId("series-occurrence-0").waitFor({ state: "visible" });
  assert.match(await page.getByTestId("series-occurrence-0").innerText(), /20:00/);
  assert.match(await page.getByTestId("series-occurrence-1").innerText(), /changed independently/i);
  assert.match(await page.getByTestId("series-occurrence-2").innerText(), /cancelled/i);
  assert.equal(await page.getByTestId("series-cancel-2").count(), 0);

  const seriesNativeLayout = await measured(page, zoom, "series amendment controls dark",
    ["series-panel", "series-amend-form", "series-occurrences", "series-occurrence-0", "series-occurrence-1", "series-occurrence-2"]);

  // Check the new recovery and recurrence controls at true tab zoom across
  // mobile, tablet and desktop dimensions, with both in-product themes.
  const matrix = [];
  const keyboardFocus = [];
  const sizes = [[375, 812], [768, 1024], [1280, 720], [1440, 900]];
  for (const theme of ["light", "dark"]) {
    const currentTheme = await page.locator("html").getAttribute("data-theme");
    if (currentTheme !== theme) await page.getByTestId("theme-toggle").click();
    await page.goto(base);
    await page.getByTestId("replan-form").waitFor({ state: "visible" });
    await page.getByTestId("replan-table").focus();
    await page.keyboard.press("Tab");
    const focused = await page.evaluate(() => ({
      id: document.activeElement?.dataset?.testid || null,
      visible: document.activeElement?.matches(":focus-visible") || false,
    }));
    assert.equal(focused.id, "replan-from");
    assert.equal(focused.visible, true);
    keyboardFocus.push({ theme, ...focused });
    for (const [width, height] of sizes) {
      await page.setViewportSize({ width, height });
      await page.waitForTimeout(100);
      await page.getByTestId("replan-form").scrollIntoViewIfNeeded();
      matrix.push(await measured(page, zoom, `replan ${width}x${height} ${theme}`,
        ["service-recovery", "replan-form", "replan-preview-submit"]));
    }
    await page.goto(`${base}/lookup?reference=${encodeURIComponent(reference)}&series_id=${encodeURIComponent(seriesId)}`);
    await page.getByTestId("lookup-reference-input").fill(reference);
    const lookupAgain = page.waitForResponse((response) =>
      response.url().endsWith(`/reservations/${reference}`) && response.request().method() === "GET");
    await page.getByTestId("lookup-submit").click();
    assert.equal((await lookupAgain).status(), 200);
    await page.getByTestId("series-amend-form").waitFor({ state: "visible" });
    for (const [width, height] of sizes) {
      await page.setViewportSize({ width, height });
      await page.waitForTimeout(100);
      await page.getByTestId("series-amend-form").scrollIntoViewIfNeeded();
      const sample = await measured(page, zoom, `series ${width}x${height} ${theme}`,
        ["series-panel", "series-amend-form", "series-occurrences", "series-occurrence-0", "series-occurrence-1", "series-occurrence-2"]);
      for (const index of [0, 1, 2]) {
        if (sample.nodes[`series-occurrence-${index}`].scrollWidth >
            sample.nodes[`series-occurrence-${index}`].clientWidth ||
            sample.nodes[`series-occurrence-${index}`].textOverflow) {
          (sample.clippedOccurrences ||= []).push(index);
        }
      }
      matrix.push(sample);
    }
  }

  await page.evaluate(() => document.fonts.ready);
  const assets = await page.evaluate(() => ({
    font: getComputedStyle(document.body).fontFamily,
    sourceSans3Loaded: Array.from(document.fonts).some((font) =>
      font.family.replace(/"/g, "") === "Source Sans 3" && font.status === "loaded"),
    externalOrigins: Array.from(performance.getEntriesByType("resource"))
      .map((item) => new URL(item.name).origin).filter((origin) => origin !== location.origin),
  }));
  assert.match(assets.font, /Source Sans 3/);
  assert.equal(assets.sourceSans3Loaded, true);
  assert.deepEqual(assets.externalOrigins, []);

  const allLayouts = [lightPreviewLayout, previewLayout, appliedLayout,
    seriesNativeLayout, ...matrix];
  const layoutFailures = allLayouts.filter((sample) => sample.horizontalOverflow ||
    sample.clippedOccurrences?.length);
  return {
    ok: layoutFailures.length === 0,
    exactSource: "ef76b375e4483da8c46f54220b2ef687c3a9b9e8",
    nativeZoom: { required: 2, final: await zoom.getZoom() },
    authorization: { anonymousStatus, dinerStatus, controlsHiddenForDiner: true, noRolePicker: !rolePicker },
    stalePlan: { status: 409, role: staleGeometry.role, focused: staleGeometry.focused,
      inViewport: staleGeometry.visible, headerBottom: staleGeometry.headerBottom,
      feedbackBounds: staleGeometry.bounds },
    preview: { exactAssignmentKeys: ["reference", "table_ids", "changed"],
      noInventedBeforeAssignment: true, committedRetryKeptBodyAndKey: true },
    apply: { committedRetryKeptBodyAndKey: true, lookupShowsAppliedTable: true,
      acceptedTermsPreserved: true },
    series: { ownerPrivacy404: privacy, importedSessionAndCurrentReference: true,
      datesAndCurrentTablesVisible: true, exceptionVisible: true,
      oneClickCancellationRemoved: true, amendmentReplayKeptBodyAndKey: true,
      cancelledAndChangedStatesVisible: true,
      keyboardFocus },
    sourceRuntime: assets,
    nativeSamples: [lightPreviewLayout, previewLayout, appliedLayout, seriesNativeLayout],
    layoutMatrix: matrix,
    layoutFailures: layoutFailures.map((sample) => ({
      label: sample.label, cssViewport: sample.cssViewport,
      document: sample.document, clippedOccurrences: sample.clippedOccurrences || [],
      overflowNodes: sample.overflowNodes,
    })),
  };
};
