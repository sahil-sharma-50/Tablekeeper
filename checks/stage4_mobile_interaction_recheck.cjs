"use strict";

const assert = require("node:assert/strict");
const fullScenario = require("./stage4_browser_recheck.cjs");

const RID = "r_stage4_qa";
const SLOT = "slot-t_2-19:00";

function dateAfter(days) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Berlin", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date()).map((part) => [part.type, part.value]));
  const date = new Date(`${parts.year}-${parts.month}-${parts.day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

async function search(page, date) {
  await page.getByTestId("date-input").fill(date);
  await page.getByTestId("party-size-input").fill("4");
  const response = page.waitForResponse((item) =>
    item.url().includes("/availability?") && item.request().method() === "GET");
  await page.getByTestId("search-button").click();
  return response;
}

async function geometry(locator) {
  return locator.evaluate((node) => {
    const rect = node.getBoundingClientRect();
    const header = document.querySelector(".site-header")?.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    const hit = document.elementFromPoint(x, y);
    return {
      bounds: [Math.round(rect.x), Math.round(rect.y),
        Math.round(rect.width), Math.round(rect.height)],
      headerBottom: Math.round(header?.bottom || 0),
      viewport: [innerWidth, innerHeight],
      dpr: devicePixelRatio,
      inViewport: rect.left >= 0 && rect.right <= innerWidth &&
        rect.top >= 0 && rect.bottom <= innerHeight,
      belowHeader: rect.top >= (header?.bottom || 0),
      focused: document.activeElement === node,
      focusVisible: node.matches(":focus-visible"),
      centerHitsTarget: hit === node || node.contains(hit),
      centerHitTag: hit?.tagName?.toLowerCase() || null,
      centerHitClass: typeof hit?.className === "string" ? hit.className : null,
      centerHitTestId: hit?.dataset?.testid || null,
      enabled: !node.disabled,
      scrollY: Math.round(window.scrollY),
    };
  });
}

function errorLine(error) {
  return String(error?.message || error).split("\n")[0].slice(0, 240);
}

module.exports = async function stage4MobileInteractionRecheck(page, zoom) {
  const base = new URL(page.url()).origin;
  const baseline = await fullScenario(page, zoom);
  const failures = [];
  const result = { exactSource: "ef76b375e4483da8c46f54220b2ef687c3a9b9e8",
    baselinePassed: baseline.ok,
    nativeLayout: baseline.layoutMatrix.map((sample) => ({
      label: sample.label, tabZoom: sample.tabZoom, cssViewport: sample.cssViewport,
      devicePixelRatio: sample.devicePixelRatio, theme: sample.theme,
      document: sample.document, horizontalOverflow: sample.horizontalOverflow,
    })),
    slotAccess: {}, mobileStaleFeedback: null,
    loggedOutReserve: [] };

  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(base);
  await page.getByTestId("replan-form").waitFor({ state: "visible" });

  const pointerDate = dateAfter(16);
  assert.equal((await search(page, pointerDate)).status(), 200);
  const pointerCell = page.getByTestId(SLOT);
  assert.equal(await pointerCell.getAttribute("data-available"), "true");
  const pointerBefore = await geometry(pointerCell);
  let pointerError = null;
  try { await pointerCell.click({ timeout: 5000 }); }
  catch (error) { pointerError = errorLine(error); }
  const pointerAfter = await geometry(pointerCell);
  const pointerSelected = (await pointerCell.getAttribute("aria-pressed")) === "true";
  result.slotAccess.pointer = { viewport: [375, 812], zoom: await zoom.getZoom(),
    before: pointerBefore, after: pointerAfter, selected: pointerSelected,
    clickError: pointerError };
  if (!pointerSelected || pointerError || !pointerAfter.centerHitsTarget || !pointerAfter.inViewport) {
    failures.push("mobile pointer slot selection was not visibly hit and selected");
  }

  const keyboardDate = dateAfter(17);
  await page.goto(base);
  await page.getByTestId("replan-form").waitFor({ state: "visible" });
  await page.getByTestId("date-input").fill(keyboardDate);
  await page.getByTestId("party-size-input").fill("4");
  await page.keyboard.press("Tab");
  const searchFocus = await page.evaluate(() => ({
    id: document.activeElement?.dataset?.testid || null,
    tag: document.activeElement?.tagName || null,
  }));
  let keyboardDateStatus = null;
  if (searchFocus.id === "search-button") {
    const keyboardSearch = page.waitForResponse((item) =>
      item.url().includes("/availability?") && item.request().method() === "GET");
    await page.keyboard.press("Enter");
    keyboardDateStatus = (await keyboardSearch).status();
  }
  const keyboardCell = page.getByTestId(SLOT);
  if (keyboardDateStatus === 200) assert.equal(await keyboardCell.getAttribute("data-available"), "true");
  const startId = await page.evaluate(() => document.activeElement?.dataset?.testid || null);
  let tabStopsToSlot = 0;
  let keyboardReached = false;
  if (keyboardDateStatus === 200) {
    for (; tabStopsToSlot < 120; tabStopsToSlot++) {
      await page.keyboard.press("Tab");
      await page.waitForTimeout(120);
      const id = await page.evaluate(() => document.activeElement?.dataset?.testid || null);
      if (id === SLOT) { keyboardReached = true; tabStopsToSlot++; break; }
    }
  }
  let keyboardState = null;
  let bookingAction = null;
  if (keyboardReached) {
    await page.waitForTimeout(700);
    keyboardState = await geometry(keyboardCell);
    await page.keyboard.press("Enter");
    const selected = (await keyboardCell.getAttribute("aria-pressed")) === "true";
    keyboardState.selectedByEnter = selected;
    if (!selected) failures.push("Enter did not select the focused slot");

    if (selected) {
      let tabsToAction = 0;
      let actionReached = false;
      for (; tabsToAction < 120; tabsToAction++) {
        await page.keyboard.press("Tab");
        await page.waitForTimeout(120);
        const id = await page.evaluate(() => document.activeElement?.dataset?.testid || null);
        if (id === "booking-submit") { actionReached = true; tabsToAction++; break; }
      }
      if (actionReached) await page.waitForTimeout(700);
      const action = page.getByTestId("booking-submit");
      const exists = (await action.count()) > 0;
      bookingAction = { reachedByTab: actionReached, tabsAfterSlot: tabsToAction,
        geometry: exists ? await geometry(action) : null };
      if (!actionReached || !bookingAction.geometry?.enabled ||
          !bookingAction.geometry.inViewport || !bookingAction.geometry.belowHeader) {
        failures.push("Reserve action was not keyboard-reachable and visible below the mobile header");
      }
    } else {
      bookingAction = { reachedByTab: false, reason: "slot selection by Enter failed" };
    }
  } else {
    keyboardState = { searchFocus, searchStatus: keyboardDateStatus,
      focusAfterSearch: startId, reachedByTab: false, tabStopsToSlot };
    failures.push("Keyboard search or Tab traversal did not reach the available slot");
  }
  result.slotAccess.keyboard = { viewport: [375, 812], zoom: await zoom.getZoom(),
    searchFocus, searchStatus: keyboardDateStatus, focusAfterSearch: startId, tabStopsToSlot,
    reachedByTab: keyboardReached, target: keyboardState, bookingAction };

  // Trigger a stale preview at mobile size and measure the focused 409 alert
  // against the enlarged native-zoom header without manually scrolling.
  await page.goto(base);
  await page.getByTestId("replan-table").selectOption("t_1");
  const staleDate = dateAfter(18);
  await page.getByTestId("replan-from").fill(`${staleDate}T18:00`);
  await page.getByTestId("replan-to").fill(`${staleDate}T18:30`);
  const planResponse = page.waitForResponse((item) =>
    item.url().endsWith(`/restaurants/${RID}/replans`) && item.request().method() === "POST");
  await page.getByTestId("replan-preview-submit").click();
  const plan = await planResponse;
  const planBody = await plan.json();
  assert.equal(plan.status(), 201);
  assert.deepEqual(planBody.assignments, []);
  await page.getByTestId("policy-management").locator("summary").click();
  await page.getByTestId("policy-effective-from").fill(dateAfter(50));
  const policyResponse = page.waitForResponse((item) =>
    item.url().endsWith(`/restaurants/${RID}/policies`) && item.request().method() === "POST");
  await page.getByTestId("policy-publish").click();
  assert.equal((await policyResponse).status(), 201);
  const staleResponse = page.waitForResponse((item) =>
    item.url().includes("/replans/") && item.url().endsWith("/apply"));
  await page.getByTestId("replan-apply").click();
  const stale = await staleResponse;
  assert.equal(stale.status(), 409);
  const alert = page.getByTestId("replan-apply-error");
  await alert.waitFor({ state: "visible" });
  const staleGeometry = await geometry(alert);
  result.mobileStaleFeedback = { status: stale.status(), role: await alert.getAttribute("role"),
    geometry: staleGeometry, viewport: [375, 812], zoom: await zoom.getZoom() };
  if (result.mobileStaleFeedback.role !== "alert" || !staleGeometry.focused ||
      !staleGeometry.inViewport || !staleGeometry.belowHeader) {
    failures.push("Mobile stale-plan alert was not focused and visible below the sticky header");
  }

  // Recheck inherited logged-out Reserve visibility at normal zoom on the
  // exact changed source, at both required mobile/desktop sizes and themes.
  for (const [theme, viewport, days] of [
    ["light", [375, 812], 19], ["dark", [375, 812], 20],
    ["light", [1280, 720], 21], ["dark", [1280, 720], 22],
  ]) {
    await zoom.setZoom(1);
    await page.waitForTimeout(200);
    await page.setViewportSize({ width: viewport[0], height: viewport[1] });
    await page.goto(base);
    const activeTheme = await page.locator("html").getAttribute("data-theme");
    if (activeTheme !== theme) await page.getByTestId("theme-toggle").click();
    await page.evaluate(() => {
      localStorage.removeItem("tablekeeper.token");
      localStorage.removeItem("tablekeeper.displayName");
      sessionStorage.clear();
    });
    await page.goto(base);
    const beforeSearch = await page.evaluate(() => Math.round(window.scrollY));
    assert.equal((await search(page, dateAfter(days))).status(), 200);
    const reserveCell = page.locator('button[data-testid^="slot-"][data-available="true"]').first();
    const slotTestId = await reserveCell.getAttribute("data-testid");
    let clickError = null;
    try { await reserveCell.click({ timeout: 5000 }); }
    catch (error) { clickError = errorLine(error); }
    const selected = (await reserveCell.getAttribute("aria-pressed")) === "true";
    await page.waitForTimeout(700);
    const panel = await geometry(page.getByTestId("reservation-panel"));
    const reserve = page.getByTestId("booking-submit");
    const reserveExists = (await reserve.count()) > 0;
    const reserveGeometry = reserveExists ? await geometry(reserve) : null;
    const reserveEnabled = reserveExists && await reserve.isEnabled();
    const item = { theme, viewport, zoom: await zoom.getZoom(), slotTestId,
      slotSelected: selected, slotClickError: clickError,
      pageScrollBeforeSearch: beforeSearch, pageScrollAfterSelection: panel.scrollY,
      panel, reserveExists, reserveEnabled, reserve: reserveGeometry, error: null };
    if (!selected || clickError || !reserveEnabled || !reserveGeometry.inViewport ||
        !reserveGeometry.belowHeader) {
      failures.push(`${theme} logged-out Reserve panel/action was not visible and enabled without manual scroll`);
    } else {
      try {
        const authError = page.getByTestId("auth-error");
        const preSubmitAuthError = await authError.count()
          ? await geometry(authError) : null;
        await reserve.click({ timeout: 5000 });
        await authError.waitFor({ state: "visible", timeout: 5000 });
        const authGeometry = await geometry(authError);
        const signIn = page.locator('[data-testid="reservation-panel"] .sign-in-action');
        const signInBox = await geometry(signIn);
        item.error = { role: await authError.getAttribute("role"), geometry: authGeometry,
          preSubmitGeometry: preSubmitAuthError,
          reserveDescribedBy: await reserve.getAttribute("aria-describedby"),
          insideReservationPanel: await authError.evaluate((node) =>
            Boolean(node.closest('[data-testid="reservation-panel"]'))),
          afterSignIn: await authError.evaluate((node) => {
            const link = node.parentElement?.querySelector(".sign-in-action");
            return Boolean(link && (link.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING));
          }),
          belowSignIn: authGeometry.bounds[1] >= (signInBox.bounds[1] + signInBox.bounds[3]) };
        if (item.error.role !== "alert" ||
            (!preSubmitAuthError?.focused && !authGeometry.focused) || !authGeometry.inViewport ||
            !authGeometry.belowHeader || !item.error.insideReservationPanel ||
            !item.error.afterSignIn || !item.error.belowSignIn ||
            !String(item.error.reserveDescribedBy || "").split(/\s+/).includes("auth-error")) {
          failures.push(`${theme} logged-out auth error was not focused immediately below Sign in inside the visible panel`);
        }
      } catch (error) {
        item.errorFlowError = errorLine(error);
        failures.push(`${theme} logged-out auth error flow failed: ${item.errorFlowError}`);
      }
    }
    result.loggedOutReserve.push(item);
  }
  await zoom.setZoom(2);

  result.failures = failures;
  result.ok = baseline.ok && failures.length === 0;
  return result;
};
