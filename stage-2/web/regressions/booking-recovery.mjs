async (page) => {
  const base = new URL(page.url()).origin;
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
  await page.getByTestId('slot-t_c+t_a-19:00').click();
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
  return { competitorStatus, refusedStatus: 409, staleAlertCleared: true, uncertaintyRetrySameBodyAndKey: true, pairConfirmationLookupLabels: pairLabel, singleClickCancel: true };
}
