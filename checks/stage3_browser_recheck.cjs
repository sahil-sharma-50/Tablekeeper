#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");

const weekdays = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const password = "Stage3-QA-Only-Password";

function dateAfter(days) {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

async function sample(page, zoom, label, selectors, requiredZoom) {
  const actualZoom = await zoom.getZoom();
  assert.equal(actualZoom, requiredZoom, `${label}: tab zoom`);
  const state = await page.evaluate((ids) => {
    const nodes = {};
    for (const id of ids) {
      const selector = id.startsWith("css:") ? id.slice(4) : `[data-testid="${CSS.escape(id)}"]`;
      const node = document.querySelector(selector);
      if (!node) { nodes[id] = null; continue; }
      const rect = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      nodes[id] = {
        visible: style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0,
        inViewport: rect.left >= 0 && rect.top >= 0 && rect.right <= innerWidth && rect.bottom <= innerHeight,
        bounds: [Math.round(rect.x), Math.round(rect.y), Math.round(rect.width), Math.round(rect.height)],
        role: node.getAttribute("role"),
        scrollWidth: node.scrollWidth,
        clientWidth: node.clientWidth,
        text: (node.innerText || "").replace(/[A-Z0-9]{6,12}/g, "[reference]").slice(0, 160),
      };
    }
    return {
      cssViewport: [innerWidth, innerHeight], outerViewport: [outerWidth, outerHeight],
      dpr: devicePixelRatio, scroll: [scrollX, scrollY],
      document: [document.documentElement.clientWidth, document.documentElement.scrollWidth],
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      theme: document.documentElement.dataset.theme,
      focused: document.activeElement?.dataset?.testid || document.activeElement?.tagName || null,
      nodes,
    };
  }, selectors);
  assert.equal(state.horizontalOverflow, false, `${label}: page horizontal overflow`);
  for (const selector of selectors) assert.ok(state.nodes[selector], `${label}: missing ${selector}`);
  return { label, tabZoom: actualZoom, ...state };
}

async function signIn(page, base, email) {
  await page.goto(`${base}/login`);
  await page.getByTestId("login-email").fill(email);
  await page.getByTestId("login-password").fill(password);
  const response = page.waitForResponse((item) => item.url().endsWith("/auth/login"));
  await page.getByTestId("login-submit").click();
  assert.equal((await response).status(), 200, "account login");
  await page.waitForURL(`${base}/`);
}

async function openLookup(page, base, reference, seriesId) {
  await page.goto(`${base}/lookup?reference=${encodeURIComponent(reference)}&series_id=${encodeURIComponent(seriesId || "")}`);
  const response = page.waitForResponse((item) => item.url().endsWith(`/reservations/${reference}`));
  await page.getByTestId("lookup-submit").click();
  assert.equal((await response).status(), 200, "reservation lookup");
}

module.exports = async function stage3BrowserRecheck(page, zoom) {
  const base = new URL(page.url()).origin;
  const captures = [];
  const fixture = {
    users: [
      { id: "qa-manager", email: "stage3-manager@example.test", password, display_name: "QA Manager" },
      { id: "qa-diner", email: "stage3-diner@example.test", password, display_name: "QA Diner" },
    ],
    restaurants: [{
      id: "r_stage3_qa", name: "Stage Three QA Restaurant", timezone: "Europe/Berlin",
      slot_minutes: 30, reservation_duration_minutes: 90, cancellation_cutoff_minutes: 0,
      opening_hours: weekdays.map((weekday) => ({ weekday, opens: "18:00", closes: "23:00" })),
      tables: [{ id: "t_a", label: "A", capacity: 2 }, { id: "t_b", label: "B", capacity: 4 }, { id: "t_c", label: "C", capacity: 6 }],
      manager_user_ids: ["qa-manager"],
    }],
    reservations: [],
  };
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
  const reset = await page.evaluate(async (state) => (await fetch("/_test/reset", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(state),
  })).status, fixture);
  assert.equal(reset, 204, "disposable browser fixture reset");
  await page.goto(base);
  const runtimeAssets = await page.evaluate(async () => {
    await document.fonts.ready;
    return {
      bodyFont: getComputedStyle(document.body).fontFamily,
      sourceSans3: Array.from(document.fonts).filter((font) => font.family.replace(/"/g, "") === "Source Sans 3").map((font) => font.status),
      externalResources: Array.from(performance.getEntriesByType("resource")).map((item) => new URL(item.name).origin).filter((origin) => origin !== location.origin),
    };
  });
  assert.match(runtimeAssets.bodyFont, /Source Sans 3/);
  assert.ok(runtimeAssets.sourceSans3.includes("loaded"), "bundled Source Sans 3 face loads in Chromium");
  assert.deepEqual(runtimeAssets.externalResources, [], "browser UI has no cross-origin runtime assets");
  const publicDetail = await page.evaluate(async () => (await fetch("/restaurants/r_stage3_qa")).json());
  assert.equal(publicDetail.can_manage_policies, false);
  assert.equal(Object.hasOwn(publicDetail, "manager_user_ids"), false);
  await signIn(page, base, "stage3-manager@example.test");
  assert.equal(await page.locator("select").evaluateAll((nodes) => nodes.some((node) => /role|account type/i.test(node.parentElement?.innerText || ""))), false, "no public role picker");

  const policySummary = page.getByTestId("policy-management").locator("summary");
  await policySummary.focus();
  await page.keyboard.press("Enter");
  assert.equal(await page.getByTestId("policy-management").evaluate((node) => node.open), true, "policy disclosure opens from the keyboard");
  await page.keyboard.press("Tab");
  const policyKeyboardFocus = await page.evaluate(() => ({ id: document.activeElement?.dataset?.testid, visible: document.activeElement?.matches(":focus-visible") }));
  assert.equal(policyKeyboardFocus.id, "policy-effective-from", "policy form follows the disclosure in keyboard order");
  assert.equal(policyKeyboardFocus.visible, true, "keyboard focus is visibly indicated on the policy form");
  await page.getByTestId("policy-publish-form").waitFor({ state: "visible" });
  await page.getByTestId("policy-effective-from").fill(dateAfter(0));
  let firstPolicy;
  await page.route("**/restaurants/r_stage3_qa/policies", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    firstPolicy = { body: route.request().postDataJSON(), key: route.request().headers()["idempotency-key"] };
    await route.fetch();
    await route.abort();
  });
  await page.getByTestId("policy-publish").focus();
  await page.keyboard.press("Enter");
  await page.getByTestId("policy-uncertain").waitFor({ state: "visible" });
  const policyAttempt = await page.evaluate(() => JSON.parse(sessionStorage.getItem("tablekeeper.policyAttempt")));
  assert.equal(policyAttempt.status, "uncertain");
  assert.equal(policyAttempt.key, firstPolicy.key);
  captures.push(await sample(page, zoom, "policy uncertainty at native zoom", ["policy-management", "policy-uncertain", "policy-publish"], 2));
  await page.unroute("**/restaurants/r_stage3_qa/policies");
  let retriedPolicy;
  await page.route("**/restaurants/r_stage3_qa/policies", async (route) => {
    if (route.request().method() === "POST") retriedPolicy = { body: route.request().postDataJSON(), key: route.request().headers()["idempotency-key"] };
    await route.continue();
  });
  const policyResponse = page.waitForResponse((item) => item.url().endsWith("/restaurants/r_stage3_qa/policies") && item.request().method() === "POST");
  await page.getByTestId("policy-publish").click();
  const published = await policyResponse;
  assert.equal(published.status(), 200);
  assert.deepEqual(retriedPolicy, firstPolicy, "policy retry retains request body and key");
  await page.getByTestId("policy-success").waitFor({ state: "visible" });
  assert.equal(await page.getByTestId("policy-success").getAttribute("role"), "status");
  captures.push(await sample(page, zoom, "published policy controls at native zoom", ["policy-list", "policy-version-1", "policy-publish"], 2));
  await page.route("**/restaurants/r_stage3_qa/policies", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const body = route.request().postDataJSON();
    body.capacities.t_a = true;
    await route.continue({ postData: JSON.stringify(body) });
  });
  const invalidPolicyResponse = page.waitForResponse((item) => item.url().endsWith("/restaurants/r_stage3_qa/policies") && item.request().method() === "POST");
  await page.getByTestId("policy-publish").click();
  assert.equal((await invalidPolicyResponse).status(), 422, "server rejects strict policy capacity type");
  await page.getByTestId("policy-error").waitFor({ state: "visible" });
  assert.equal(await page.getByTestId("policy-error").getAttribute("role"), "alert");
  assert.equal(await page.getByTestId("policy-publish").getAttribute("aria-describedby"), "policy-error");
  const policyErrorFeedback = await sample(page, zoom, "policy validation feedback at native zoom", ["policy-error", "policy-publish"], 2);
  assert.equal(policyErrorFeedback.nodes["policy-error"].visible, true);
  assert.equal(policyErrorFeedback.nodes["policy-error"].inViewport, true, "policy error visible after submit without extra scrolling");
  await page.unroute("**/restaurants/r_stage3_qa/policies");

  const bookingDate = dateAfter(14);
  await page.getByTestId("date-input").fill(bookingDate);
  await page.getByTestId("party-size-input").fill("4");
  const availability = page.waitForResponse((item) => item.url().includes("/availability?"));
  await page.getByTestId("search-button").click();
  assert.equal((await availability).status(), 200);
  await page.getByTestId("slot-t_b-19:00").click();
  const bookingResponse = page.waitForResponse((item) => item.url().endsWith("/reservations") && item.request().method() === "POST");
  await page.getByTestId("booking-submit").click();
  const booking = await bookingResponse;
  assert.equal(booking.status(), 201);
  const receipt = await booking.json();
  assert.equal(receipt.accepted_terms.policy_version, 1);
  await page.getByTestId("confirmation").waitFor({ state: "visible" });
  await page.getByTestId("confirmation").getByTestId("accepted-terms").scrollIntoViewIfNeeded();
  captures.push(await sample(page, zoom, "booking terms at native zoom", ["confirmation", "accepted-terms"], 2));
  const reference = receipt.reference;

  await openLookup(page, base, reference);
  const historySummary = page.getByTestId("reservation-history").locator("summary");
  await historySummary.focus();
  await page.keyboard.press("Enter");
  assert.equal(await page.getByTestId("reservation-history").evaluate((node) => node.open), true, "history disclosure opens from the keyboard");
  await page.getByTestId("history-entry-1").waitFor({ state: "visible" });
  const firstHistoryEntry = page.getByTestId("history-entry-1");
  await firstHistoryEntry.locator("details summary").first().focus();
  await page.keyboard.press("Enter");
  const historicalTerms = firstHistoryEntry.getByTestId("accepted-terms");
  await historicalTerms.locator("details summary").focus();
  await page.keyboard.press("Enter");
  await historicalTerms.waitFor({ state: "visible" });
  await page.getByTestId("history-entry-1").scrollIntoViewIfNeeded();
  captures.push(await sample(page, zoom, "reservation history at native zoom", ["reservation-history", "history-entry-1", 'css:[data-testid="history-entry-1"] [data-testid="accepted-terms"]'], 2));
  const seriesCount = page.getByTestId("series-count");
  await seriesCount.focus();
  await page.keyboard.press("Home");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  assert.equal(await seriesCount.inputValue(), "3", "series count can be selected from the keyboard");
  await page.route("**/series", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const body = route.request().postDataJSON();
    body.count = 13;
    await route.continue({ postData: JSON.stringify(body) });
  });
  const rejectedAdoption = page.waitForResponse((item) => item.url().endsWith("/series") && item.request().method() === "POST");
  await page.getByTestId("series-create").click();
  assert.equal((await rejectedAdoption).status(), 422, "server rejects out-of-range adoption count");
  await page.getByTestId("series-create-error").waitFor({ state: "visible" });
  assert.equal(await page.getByTestId("series-create-error").getAttribute("role"), "alert");
  assert.equal(await page.getByTestId("series-create").getAttribute("aria-describedby"), "series-create-error");
  const adoptionErrorFeedback = await sample(page, zoom, "adoption validation feedback at native zoom", ["series-create-error", "series-create"], 2);
  assert.equal(adoptionErrorFeedback.nodes["series-create-error"].visible, true);
  assert.equal(adoptionErrorFeedback.nodes["series-create-error"].inViewport, true, "adoption error visible after submit without extra scrolling");
  await page.unroute("**/series");
  await page.evaluate(() => sessionStorage.removeItem("tablekeeper.seriesAttempt"));
  let firstSeries;
  await page.route("**/series", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    firstSeries = { body: route.request().postDataJSON(), key: route.request().headers()["idempotency-key"] };
    await route.fetch();
    await route.abort();
  });
  await page.getByTestId("series-create").focus();
  await page.keyboard.press("Enter");
  await page.getByTestId("series-uncertain").waitFor({ state: "visible" });
  const seriesAttempt = await page.evaluate(() => JSON.parse(sessionStorage.getItem("tablekeeper.seriesAttempt")));
  assert.equal(seriesAttempt.status, "uncertain");
  assert.equal(seriesAttempt.key, firstSeries.key);
  captures.push(await sample(page, zoom, "series uncertainty at native zoom", ["series-panel", "series-uncertain", "series-create"], 2));
  await page.unroute("**/series");
  let retriedSeries;
  await page.route("**/series", async (route) => {
    if (route.request().method() === "POST") retriedSeries = { body: route.request().postDataJSON(), key: route.request().headers()["idempotency-key"] };
    await route.continue();
  });
  const seriesResponse = page.waitForResponse((item) => item.url().endsWith("/series") && item.request().method() === "POST");
  await page.getByTestId("series-create").click();
  const seriesReply = await seriesResponse;
  assert.equal(seriesReply.status(), 200);
  assert.deepEqual(retriedSeries, firstSeries, "adoption retry retains request body and key");
  await page.getByTestId("series-summary").waitFor({ state: "visible" });
  assert.match(await page.getByTestId("series-summary").innerText(), /revision 1/);
  const seriesReceipt = await seriesReply.json();
  const seriesId = seriesReceipt.series_id;
  assert.equal(seriesReceipt.occurrences.length, 3);
  await page.getByTestId("series-occurrence-2").waitFor({ state: "visible" });
  const recurrenceDateChecks = [];
  for (const index of [0, 1, 2]) {
    const row = page.getByTestId(`series-occurrence-${index}`);
    await row.scrollIntoViewIfNeeded();
    const expectedLabel = seriesReceipt.occurrences[index].reservation.starts_at_local.replace("T", " · ");
    const dateCheck = await row.evaluate((node, label) => {
      const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
      let textNode;
      let match;
      while ((textNode = walker.nextNode())) {
        const start = textNode.nodeValue.indexOf(label);
        if (start >= 0) { match = { textNode, start }; break; }
      }
      if (!match) return { found: false, clippedBy: [] };
      const range = document.createRange();
      range.setStart(match.textNode, match.start);
      range.setEnd(match.textNode, match.start + label.length);
      const rects = Array.from(range.getClientRects()).map((rect) => ({ left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom }));
      const stickyBottom = document.querySelector("header")?.getBoundingClientRect().bottom || 0;
      const clippedBy = [];
      for (let ancestor = match.textNode.parentElement; ancestor && ancestor !== node.parentElement; ancestor = ancestor.parentElement) {
        const style = getComputedStyle(ancestor);
        const rect = ancestor.getBoundingClientRect();
        for (const line of rects) {
          if (/(hidden|clip|auto|scroll)/.test(style.overflowX) && (line.left < rect.left - 0.5 || line.right > rect.right + 0.5)) clippedBy.push(ancestor.tagName + ":x");
          if (/(hidden|clip|auto|scroll)/.test(style.overflowY) && (line.top < rect.top - 0.5 || line.bottom > rect.bottom + 0.5)) clippedBy.push(ancestor.tagName + ":y");
        }
      }
      const inViewport = rects.length > 0 && rects.every((rect) => rect.left >= 0 && rect.right <= innerWidth && rect.top >= stickyBottom && rect.bottom <= innerHeight);
      return { found: true, label, rects, clippedBy, inViewport, stickyBottom, rowScroll: [node.scrollWidth, node.clientWidth, node.scrollHeight, node.clientHeight] };
    }, expectedLabel);
    assert.equal(dateCheck.found, true, `recurrence occurrence ${index} date is rendered`);
    assert.ok(dateCheck.rects.length && dateCheck.rects.every((rect) => rect.right > rect.left && rect.bottom > rect.top), `recurrence occurrence ${index} date has visible text bounds`);
    assert.equal(dateCheck.clippedBy.length, 0, `recurrence occurrence ${index} date is not clipped`);
    assert.equal(dateCheck.inViewport, true, `recurrence occurrence ${index} date can be brought below the sticky header`);
    await sample(page, zoom, `series occurrence ${index} at native zoom`, [`series-occurrence-${index}`], 2);
    recurrenceDateChecks.push(dateCheck);
  }

  const changed = await page.evaluate(async ({ token, ref }) => (await fetch(`/reservations/${encodeURIComponent(ref)}`, {
    method: "PATCH", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ expected_revision: 1, table_id: "t_c" }),
  })).status, { token: await page.evaluate(() => localStorage.getItem("tablekeeper.token")), ref: seriesReceipt.occurrences[1].reference });
  assert.equal(changed, 200, "one generated visit changes independently");
  const occurrenceCancel = page.waitForResponse((item) => item.url().endsWith(`/reservations/${seriesReceipt.occurrences[2].reference}/cancel`));
  await page.getByTestId("series-cancel-2").click();
  assert.equal((await occurrenceCancel).status(), 200, "single-click occurrence cancellation");
  await page.getByTestId("series-exception-1").waitFor({ state: "visible" });
  await page.getByTestId("series-occurrence-2").waitFor({ state: "visible" });
  assert.equal(await page.getByTestId("series-cancel-2").count(), 0, "cancel button removed after cancellation");
  const cancelledText = await page.getByTestId("series-occurrence-2").innerText();
  assert.match(cancelledText, /cancelled/i);

  const anchorCancel = page.waitForResponse((item) => item.url().endsWith(`/reservations/${reference}/cancel`));
  await page.getByTestId("reservation-cancel-button").click();
  assert.equal((await anchorCancel).status(), 200, "single-click anchor cancellation");
  assert.equal(await page.getByTestId("reservation-status").innerText(), "cancelled");
  assert.equal(await page.getByTestId("reservation-cancel-button").count(), 0);
  await openLookup(page, base, reference, seriesId);
  await page.getByTestId("reservation-history").locator("summary").click();
  await page.getByTestId("history-entry-2").waitFor({ state: "visible" });
  assert.equal(await page.getByTestId("series-occurrence-0").getByText("cancelled").count(), 1, "cancelled anchor remains in the agreement");
  assert.equal(await page.getByTestId("series-occurrence-1").getByText("confirmed").count(), 1, "anchor cancellation preserves confirmed siblings");
  assert.equal(await page.getByTestId("series-occurrence-2").getByText("cancelled").count(), 1, "independent cancelled occurrence remains cancelled");

  const normalLayouts = [];
  await zoom.setZoom(1);
  for (const theme of ["light", "dark"]) for (const [width, height] of [[375, 812], [768, 1024], [1280, 720]]) {
    await page.setViewportSize({ width, height });
    await page.evaluate((value) => localStorage.setItem("tablekeeper.theme", value), theme);
    await page.goto(base);
    await page.getByTestId("policy-management").locator("summary").click();
    normalLayouts.push(await sample(page, zoom, `policy form ${width}x${height} ${theme}`, ["policy-management", "policy-publish-form", "policy-list"], 1));
    await openLookup(page, base, reference, seriesId);
    await page.getByTestId("reservation-history").locator("summary").click();
    await page.getByTestId("history-entry-1").waitFor({ state: "visible" });
    await page.getByTestId("series-occurrence-2").waitFor({ state: "visible" });
    for (const index of [0, 1, 2]) await page.getByTestId(`series-occurrence-${index}`).scrollIntoViewIfNeeded();
    normalLayouts.push(await sample(page, zoom, `history and series ${width}x${height} ${theme}`, ["history-entry-1", 'css:[data-testid="history-entry-1"] [data-testid="accepted-terms"]', "series-occurrence-0", "series-occurrence-1", "series-occurrence-2", "series-exception-1"], 1));
  }

  const zoomLayouts = [];
  await zoom.setZoom(2);
  for (const theme of ["light", "dark"]) for (const [width, height] of [[1280, 720], [1440, 900]]) {
    await page.setViewportSize({ width, height });
    await page.evaluate((value) => localStorage.setItem("tablekeeper.theme", value), theme);
    await page.goto(base);
    await page.getByTestId("policy-management").locator("summary").click();
    await page.getByTestId("policy-publish-form").waitFor({ state: "visible" });
    await page.getByTestId("policy-publish").scrollIntoViewIfNeeded();
    zoomLayouts.push(await sample(page, zoom, `policy controls ${width}x${height} ${theme} at native 200%`, ["policy-management", "policy-publish-form", "policy-version-1", "policy-publish"], 2));
    await openLookup(page, base, reference, seriesId);
    await page.getByTestId("reservation-history").locator("summary").click();
    await page.getByTestId("history-entry-1").waitFor({ state: "visible" });
    await page.getByTestId("history-entry-1").scrollIntoViewIfNeeded();
    await page.getByTestId("history-entry-1").getByTestId("accepted-terms").scrollIntoViewIfNeeded();
    for (const id of ["series-occurrence-0", "series-occurrence-1", "series-occurrence-2"]) await page.getByTestId(id).scrollIntoViewIfNeeded();
    zoomLayouts.push(await sample(page, zoom, `history and series ${width}x${height} ${theme} at native 200%`, ["history-entry-1", 'css:[data-testid="history-entry-1"] [data-testid="accepted-terms"]', "series-occurrence-0", "series-occurrence-1", "series-occurrence-2", "series-exception-1"], 2));
  }

  await zoom.setZoom(1);
  await page.goto(base);
  await page.getByTestId("logout-button").click();
  await signIn(page, base, "stage3-diner@example.test");
  await page.getByTestId("policy-management").locator("summary").click();
  await page.getByTestId("policy-manager-access").waitFor({ state: "visible" });
  assert.equal(await page.getByTestId("policy-publish-form").count(), 0, "non-manager has no policy editor");
  await page.goto(`${base}/lookup?reference=${encodeURIComponent(reference)}`);
  const privateLookup = page.waitForResponse((item) => item.url().endsWith(`/reservations/${reference}`));
  await page.getByTestId("lookup-submit").click();
  assert.equal((await privateLookup).status(), 404, "other diner cannot look up the manager's booking");
  await page.getByTestId("reservation-error").waitFor({ state: "visible" });
  assert.equal(await page.getByTestId("reservation-error").getAttribute("role"), "alert");
  const privateError = await sample(page, zoom, "other-owner lookup denial", ["reservation-error"], 1);
  assert.equal(privateError.nodes["reservation-error"].inViewport, true, "denial feedback visible without manual scroll");

  await page.goto(base);
  await page.getByTestId("logout-button").click();
  const authErrors = [];
  await zoom.setZoom(1);
  for (const theme of ["light", "dark"]) for (const [width, height] of [[375, 812], [1280, 720]]) {
    await page.setViewportSize({ width, height });
    await page.evaluate((value) => localStorage.setItem("tablekeeper.theme", value), theme);
    await page.goto(`${base}/login`);
    await page.getByTestId("login-email").fill("stage3-manager@example.test");
    await page.getByTestId("login-password").fill("wrong-password-only");
    const badLogin = page.waitForResponse((item) => item.url().endsWith("/auth/login"));
    await page.getByTestId("login-submit").click();
    assert.equal((await badLogin).status(), 401);
    await page.getByTestId("auth-error").waitFor({ state: "visible" });
    const loginError = await sample(page, zoom, `login error ${width}x${height} ${theme}`, ["auth-error"], 1);
    assert.equal(loginError.nodes["auth-error"].inViewport, true, "login error visible without additional scroll");
    assert.equal(loginError.focused, "auth-error", "login error receives focus");
    assert.equal(await page.getByTestId("login-email").inputValue(), "stage3-manager@example.test");
    authErrors.push(loginError);

    await page.goto(`${base}/signup`);
    await page.getByTestId("signup-display-name").fill("QA Existing Account");
    await page.getByTestId("signup-email").fill("stage3-manager@example.test");
    await page.getByTestId("signup-password").fill(password);
    const duplicateSignup = page.waitForResponse((item) => /\/auth\/(register|signup)$/.test(new URL(item.url()).pathname));
    await page.getByTestId("signup-submit").click();
    assert.equal((await duplicateSignup).status(), 409, "duplicate signup response");
    await page.getByTestId("auth-error").waitFor({ state: "visible" });
    const signupError = await sample(page, zoom, `duplicate signup error ${width}x${height} ${theme}`, ["auth-error"], 1);
    assert.equal(signupError.nodes["auth-error"].inViewport, true, "signup error visible without additional scroll");
    assert.equal(signupError.focused, "auth-error", "signup error receives focus");
    assert.equal(await page.getByTestId("signup-display-name").inputValue(), "QA Existing Account");
    authErrors.push(signupError);
  }

  const reserveErrors = [];
  for (const theme of ["light", "dark"]) for (const [width, height] of [[375, 812], [1280, 720]]) {
    await page.setViewportSize({ width, height });
    await page.evaluate((value) => localStorage.setItem("tablekeeper.theme", value), theme);
    await page.goto(base);
    await page.getByTestId("date-input").fill(bookingDate);
    await page.getByTestId("party-size-input").fill("4");
    const availability = page.waitForResponse((item) => item.url().includes("/availability?"));
    await page.getByTestId("search-button").click();
    assert.equal((await availability).status(), 200);
    await page.getByTestId("slot-t_c-19:00").click();
    await page.getByTestId("booking-submit").click();
    await page.getByTestId("auth-error").waitFor({ state: "visible" });
    const error = await sample(page, zoom, `logged-out reserve ${width}x${height} ${theme}`, ["reservation-panel", "auth-error", "booking-submit"], 1);
    assert.equal(error.nodes["auth-error"].inViewport, true, "reserve sign-in error visible without manual scroll");
    assert.equal(error.nodes["booking-submit"].visible, true, "reserve remains enabled and visible");
    assert.equal(await page.getByTestId("booking-submit").getAttribute("aria-describedby"), "auth-error");
    const adjacent = await page.getByTestId("auth-error").evaluate((node) => node.parentElement?.querySelector(".sign-in-action")?.nextElementSibling === node);
    assert.equal(adjacent, true, "reserve error appears immediately below Sign in");
    assert.equal(await page.getByTestId("booking-submit").isDisabled(), false);
    reserveErrors.push(error);
  }
  await zoom.setZoom(2);
  const finalZoom = await zoom.getZoom();
  assert.equal(finalZoom, 2);
  return {
    ok: true,
    managerPolicyNoRolePicker: true,
    runtimeAssets,
    keyboardNavigation: { policySummary: true, firstPolicyControlHasVisibleFocus: policyKeyboardFocus.visible, historyDisclosuresOpen: true, seriesCountKeyboard: true, adoptionSubmitKeyboard: true },
    policyAndSeriesRetriesSameBodyAndKey: true,
    policyErrorVisibleAndLinked: true,
    seriesAdoptionErrorVisibleAndLinked: true,
    publicationStatusVisible: true,
    adoptionResultVisible: true,
    otherOwnerDenialVisible: true,
    reservationTermsAndHistoryRendered: true,
    seriesDatesRendered: seriesReceipt.occurrences.map((item) => item.reservation.starts_at_local),
    recurrenceDateChecks,
    independentSeriesExceptionVisible: true,
    cancelledOccurrenceButtonRemoved: true,
    anchorCancellationLeavesSiblingsVisible: true,
    normalLayouts, zoomLayouts, authErrors, reserveErrors,
    finalNativeZoom: finalZoom,
  };
};
