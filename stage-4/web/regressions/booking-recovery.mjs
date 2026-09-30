async (page) => {
  const base = new URL(page.url()).origin;
  const settleViewport = () => page.evaluate(async () => {
    let previous = scrollY;
    let stableFrames = 0;
    for (let frame = 0; frame < 120 && stableFrames < 3; frame += 1) {
      await new Promise(requestAnimationFrame);
      stableFrames = Math.abs(scrollY - previous) < 0.5 ? stableFrames + 1 : 0;
      previous = scrollY;
    }
  });
  const weekdays = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
  const restaurant = {
    id: 'r_combo', name: 'Booking Recovery Table', timezone: 'Europe/Berlin',
    slot_minutes: 30, reservation_duration_minutes: 90, cancellation_cutoff_minutes: 120,
    opening_hours: weekdays.map((weekday) => ({ weekday, opens: '18:00', closes: '23:00' })),
    tables: [
      { id: 't_a', label: 'A', capacity: 2 }, { id: 't_b', label: 'B', capacity: 4 },
      { id: 't_c', label: 'C', capacity: 3 }, { id: 't_d', label: 'D', capacity: 5 },
    ],
    combinable: [['t_c', 't_a'], ['t_a', 't_b'], ['t_b', 't_d']],
  };
  await page.evaluate(() => {
    localStorage.removeItem('tablekeeper.token');
    localStorage.removeItem('tablekeeper.displayName');
    sessionStorage.clear();
  });
  const reset = await page.evaluate(async (fixture) => {
    const response = await fetch('/_test/reset', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(fixture),
    });
    return response.status;
  }, { users: [], restaurants: [restaurant], reservations: [] });
  if (reset !== 204) throw new Error(`Disposable fixture reset returned ${reset}.`);

  const signedOutFeedback = [];
  for (const theme of ['light', 'dark']) {
    for (const [width, height] of [[375, 812], [1280, 720]]) {
      await page.setViewportSize({ width, height });
      await page.evaluate((value) => {
        localStorage.setItem('tablekeeper.theme', value);
        sessionStorage.clear();
      }, theme);
      await page.goto(`${base}/`);
      await page.getByTestId('date-input').fill('2026-10-14');
      await page.getByTestId('party-size-input').fill('4');
      const availability = page.waitForResponse((response) => response.url().includes('/availability?'));
      await page.getByTestId('search-button').click();
      if ((await availability).status() !== 200) throw new Error('Signed-out availability search failed.');
      await page.getByTestId('slot-t_c+t_a-18:00').click();
      await page.waitForFunction(() => {
        const alert = document.querySelector('[data-testid="auth-error"]');
        const signIn = document.querySelector('.sign-in-action');
        const button = document.querySelector('[data-testid="booking-submit"]');
        const box = alert?.getBoundingClientRect();
        const headerBottom = document.querySelector('.site-header')?.getBoundingClientRect().bottom || 0;
        return Boolean(alert && signIn && button && box && document.activeElement === alert && box.top >= headerBottom && box.bottom <= innerHeight && !button.disabled && (signIn.compareDocumentPosition(alert) & Node.DOCUMENT_POSITION_FOLLOWING));
      });
      await settleViewport();
      const geometry = await page.evaluate(() => {
        const alert = document.querySelector('[data-testid="auth-error"]');
        const box = alert.getBoundingClientRect();
        const active = document.activeElement;
        const button = document.querySelector('[data-testid="booking-submit"]');
        return {
          viewport: [innerWidth, innerHeight], scrollY,
          alert: { top: box.top, bottom: box.bottom },
          headerBottom: document.querySelector('.site-header').getBoundingClientRect().bottom,
      focused: { tag: active.tagName, id: active.id, testId: active.dataset.testid || null },
      focusedAlert: active === alert, reserveEnabled: !button.disabled,
      outline: getComputedStyle(alert).outlineWidth,
        };
      });
      if (!geometry.focusedAlert || geometry.alert.top < geometry.headerBottom || geometry.alert.bottom > height || !geometry.reserveEnabled) throw new Error(`Signed-out reserve feedback missed the viewport or action: ${JSON.stringify(geometry)}`);
      signedOutFeedback.push({ theme, ...geometry });
    }
  }
  await page.evaluate(() => sessionStorage.clear());

  const email = `booking-${Date.now()}@example.invalid`;
  const password = 'BookingRegression-Only-2026';
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(`${base}/signup`);
  await page.getByTestId('signup-display-name').fill('Booking Regression');
  await page.getByTestId('signup-email').fill(email);
  await page.getByTestId('signup-password').fill(password);
  const signupResponse = page.waitForResponse((response) => response.url().endsWith('/auth/signup'));
  await page.getByTestId('signup-submit').click();
  if ((await signupResponse).status() !== 201) throw new Error('Signup failed.');
  await page.waitForURL(`${base}/`);
  await page.getByTestId('date-input').fill('2026-10-14');
  await page.getByTestId('party-size-input').fill('4');
  await page.getByTestId('search-button').click();
  await page.getByTestId('availability-grid').waitFor();
  await page.getByTestId('slot-t_d-19:00').click();

  const competitorStatus = await page.evaluate(async () => {
    const response = await fetch('/reservations', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${localStorage.getItem('tablekeeper.token')}`,
        'Idempotency-Key': `competitor-${Date.now()}`,
      },
      body: JSON.stringify({ restaurant_id: 'r_combo', table_id: 't_d', starts_at_local: '2026-10-14T19:00', party_size: 4 }),
    });
    return response.status;
  });
  if (competitorStatus !== 201) throw new Error(`Second client booking returned ${competitorStatus}.`);

  const refused = page.waitForResponse((response) => response.url().endsWith('/reservations') && response.request().method() === 'POST');
  await page.getByTestId('booking-submit').click();
  if ((await refused).status() !== 409) throw new Error('The selected 19:00 booking was not refused.');
  await page.getByTestId('booking-error').waitFor();
  await page.waitForFunction(() => {
    const alert = document.querySelector('[data-testid="booking-error"]');
    const box = alert?.getBoundingClientRect();
    const headerBottom = document.querySelector('.site-header')?.getBoundingClientRect().bottom || 0;
    return Boolean(alert && box && document.activeElement === alert && box.top >= headerBottom && box.bottom <= innerHeight);
  });
  await page.waitForFunction(() => document.querySelector('[data-testid="slot-t_d-19:00"]')?.disabled === true);
  if (!(await page.getByTestId('slot-t_d-21:00').isEnabled())) throw new Error('The alternate 21:00 slot is not available.');
  await page.getByTestId('slot-t_d-21:00').click();
  await page.getByTestId('booking-error').waitFor({ state: 'detached' });
  const summary = await page.getByTestId('booking-summary').innerText();
  const clearedAttempt = await page.evaluate(() => sessionStorage.getItem('tablekeeper.bookingAttempt'));
  if (!summary.includes('21:00') || clearedAttempt !== null || !(await page.getByTestId('booking-submit').isEnabled())) throw new Error('The 19:00 refusal was not cleared for the 21:00 selection.');

  await page.route('**/reservations', (route) => route.request().method() === 'POST' ? route.abort() : route.continue());
  await page.getByTestId('booking-submit').click();
  await page.getByTestId('booking-uncertain').waitFor();
  const uncertain = await page.evaluate(() => JSON.parse(sessionStorage.getItem('tablekeeper.bookingAttempt')));
  if (uncertain.status !== 'uncertain' || uncertain.body.starts_at_local !== '2026-10-14T21:00' || !(await page.getByTestId('booking-submit').isEnabled())) throw new Error('Uncertain retry identity was not retained.');
  await page.unroute('**/reservations');
  await page.getByTestId('booking-submit').click();
  await page.getByTestId('confirmation').waitFor();
  const confirmed = await page.evaluate(() => JSON.parse(sessionStorage.getItem('tablekeeper.bookingAttempt')));
  if (confirmed.status !== 'confirmed' || confirmed.key !== uncertain.key || JSON.stringify(confirmed.body) !== JSON.stringify(uncertain.body)) throw new Error('Retry changed the uncertain request identity.');

  await page.setViewportSize({ width: 375, height: 812 });
  await page.getByTestId('slot-t_c+t_a-18:00').click();
  const pairCompetitorStatus = await page.evaluate(async () => {
    const response = await fetch('/reservations', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${localStorage.getItem('tablekeeper.token')}`,
        'Idempotency-Key': `pair-competitor-${Date.now()}`,
      },
      body: JSON.stringify({ restaurant_id: 'r_combo', table_ids: ['t_c', 't_a'], starts_at_local: '2026-10-14T18:00', party_size: 4 }),
    });
    return response.status;
  });
  if (pairCompetitorStatus !== 201) throw new Error(`Second-client pair booking returned ${pairCompetitorStatus}.`);
  const pairRefused = page.waitForResponse((response) => response.url().endsWith('/reservations') && response.request().method() === 'POST');
  await page.getByTestId('booking-submit').click();
  if ((await pairRefused).status() !== 409) throw new Error('Competing pair reservation was not refused.');
  await page.waitForFunction(() => document.querySelector('[data-testid="slot-t_c+t_a-18:00"]')?.disabled === true);
  await page.waitForFunction(() => {
    const alert = document.querySelector('[data-testid="booking-error"]');
    const box = alert?.getBoundingClientRect();
    const headerBottom = document.querySelector('.site-header')?.getBoundingClientRect().bottom || 0;
    return Boolean(alert && box && document.activeElement === alert && box.top >= headerBottom && box.bottom <= innerHeight);
  });
  await settleViewport();
  const refusalGeometry = await page.evaluate(() => {
    const alert = document.querySelector('[data-testid="booking-error"]');
    const box = alert.getBoundingClientRect();
    const active = document.activeElement;
    return {
      viewport: [innerWidth, innerHeight], scrollY,
      alert: { top: box.top, bottom: box.bottom },
      headerBottom: document.querySelector('.site-header').getBoundingClientRect().bottom,
      focused: { tag: active.tagName, id: active.id, testId: active.dataset.testid || null },
      focusedAlert: active === alert,
      outline: getComputedStyle(alert).outlineWidth,
    };
  });
  if (!refusalGeometry.focusedAlert || refusalGeometry.alert.top < refusalGeometry.headerBottom || refusalGeometry.alert.bottom > 812) throw new Error(`Booking refusal missed the mobile viewport: ${JSON.stringify(refusalGeometry)}`);
  const mobileError = await page.getByTestId('booking-error').evaluate((alert) => [alert.getAttribute('role'), alert.id, getComputedStyle(alert).outlineWidth]);
  const retainedSearch = await page.evaluate(() => [document.querySelector('[data-testid="date-input"]').value, document.querySelector('[data-testid="party-size-input"]').value, document.querySelector('[data-testid="booking-submit"]').getAttribute('aria-describedby')]);
  if (mobileError[0] !== 'alert' || mobileError[1] !== 'booking-error' || Number.parseFloat(mobileError[2]) <= 0 || retainedSearch[0] !== '2026-10-14' || retainedSearch[1] !== '4' || retainedSearch[2] !== 'booking-error') throw new Error('Mobile pair refusal lacks visible focused feedback or lost its search details.');
  if (!(await page.getByTestId('slot-t_c+t_a-21:00').isEnabled())) throw new Error('The alternate C + A slot is not available.');
  await page.getByTestId('slot-t_c+t_a-21:00').click();
  await page.getByTestId('booking-error').waitFor({ state: 'detached' });
  const pairResponse = page.waitForResponse((response) => response.url().endsWith('/reservations') && response.request().method() === 'POST');
  await page.getByTestId('booking-submit').click();
  if ((await pairResponse).status() !== 201) throw new Error('The declared C + A pair was not reserved.');
  await page.getByTestId('confirmation').waitFor();
  const pairLabel = (await page.getByTestId('confirmation-tables').innerText()).trim();
  if (pairLabel !== 'C + A' || !(await page.getByTestId('confirmation-details').innerText()).includes(pairLabel)) throw new Error(`Pair confirmation omitted or reordered table labels: ${pairLabel}`);
  const reference = await page.getByTestId('confirmation-reference').innerText();
  await page.goto(`${base}/lookup`);
  await page.getByTestId('lookup-reference-input').fill(reference);
  const lookupResponse = page.waitForResponse((response) => response.url().includes('/reservations/') && response.request().method() === 'GET');
  await page.getByTestId('lookup-submit').click();
  if ((await lookupResponse).status() !== 200) throw new Error('Pair reservation lookup failed.');
  await page.getByTestId('reservation-detail').waitFor();
  if ((await page.getByTestId('reservation-tables').innerText()).trim() !== pairLabel) throw new Error('Pair lookup omitted or reordered table labels.');
  const cancelButton = page.getByTestId('reservation-cancel-button');
  if ((await cancelButton.innerText()).trim() !== 'Cancel reservation') throw new Error('Cancellation action is not clearly labelled.');
  const cancelStyle = await cancelButton.evaluate((button) => [button.className, getComputedStyle(button).borderTopStyle, getComputedStyle(button).backgroundColor]);
  if (!cancelStyle[0].includes('button-outline') || cancelStyle[1] === 'none' || cancelStyle[2] !== 'rgba(0, 0, 0, 0)') throw new Error('Cancellation action is not outlined.');
  const cancellation = page.waitForResponse((response) => response.url().includes('/cancel') && response.request().method() === 'POST');
  await cancelButton.click();
  if ((await cancellation).status() !== 200) throw new Error('Single-click pair cancellation failed.');
  await page.waitForFunction(() => document.querySelector('[data-testid="reservation-status"]')?.textContent?.trim() === 'cancelled');
  const cancelledLabel = (await page.getByTestId('reservation-status').innerText()).trim();
  if (cancelledLabel !== 'cancelled') throw new Error(`Cancelled pair status was not shown: ${JSON.stringify(cancelledLabel)}`);
  await page.getByTestId('reservation-cancel-button').waitFor({ state: 'detached' });
  return { competitorStatus, refusedStatus: 409, staleAlertCleared: true, uncertaintyRetrySameBodyAndKey: true, signedOutFeedback, mobilePairCompetitorStatus: pairCompetitorStatus, mobileRefusalGeometry: refusalGeometry, pairConfirmationLookupLabels: pairLabel, singleClickCancel: true };
}
