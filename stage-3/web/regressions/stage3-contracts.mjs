async (page) => {
  const base = new URL(page.url()).origin;
  const weekdays = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
  const fixture = {
    users: [
      { id: 'u_manager', email: 'manager@example.test', password: 'Stage3-Test-Only-Password', display_name: 'Test Manager' },
      { id: 'u_diner', email: 'diner@example.test', password: 'Stage3-Test-Only-Password', display_name: 'Test Diner' },
    ],
    restaurants: [{
      id: 'r_stage3', name: 'Stage Three Table', timezone: 'Europe/Berlin',
      slot_minutes: 30, reservation_duration_minutes: 90, cancellation_cutoff_minutes: 120,
      opening_hours: weekdays.map((weekday) => ({ weekday, opens: '18:00', closes: '23:00' })),
      tables: [{ id: 't_a', label: 'A', capacity: 2 }, { id: 't_b', label: 'B', capacity: 4 }, { id: 't_c', label: 'C', capacity: 6 }],
      manager_user_ids: ['u_manager'],
    }],
    reservations: [],
  };
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
  const reset = await page.evaluate(async (state) => (await fetch('/_test/reset', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(state),
  })).status, fixture);
  if (reset !== 204) throw new Error(`Fixture reset returned ${reset}.`);
  const publicDetail = await page.evaluate(async () => (await fetch('/restaurants/r_stage3')).json());
  if (publicDetail.can_manage_policies !== false || 'manager_user_ids' in publicDetail) throw new Error('Public restaurant detail exposed manager membership.');

  await page.goto(`${base}/login`);
  await page.getByTestId('login-email').fill('manager@example.test');
  await page.getByTestId('login-password').fill('Stage3-Test-Only-Password');
  const login = page.waitForResponse((response) => response.url().endsWith('/auth/login'));
  await page.getByTestId('login-submit').click();
  if ((await login).status() !== 200) throw new Error('Manager login failed.');
  await page.waitForURL(`${base}/`);
  await page.getByTestId('policy-management').locator('summary').click();
  await page.getByTestId('policy-publish-form').waitFor();
  const effectiveDate = await page.evaluate(() => {
    const value = new Date();
    return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
  });
  await page.getByTestId('policy-effective-from').fill(effectiveDate);
  await page.getByTestId('policy-capacity-t_a').fill('3');
  let initialPolicyWrite;
  await page.route('**/restaurants/r_stage3/policies', async (route) => {
    if (route.request().method() === 'POST') {
      initialPolicyWrite = { body: route.request().postDataJSON(), key: route.request().headers()['idempotency-key'] };
      await route.fetch();
      await route.abort();
    } else await route.continue();
  });
  await page.getByTestId('policy-publish').click();
  await page.getByTestId('policy-uncertain').waitFor();
  const savedPolicyAttempt = await page.evaluate(() => JSON.parse(sessionStorage.getItem('tablekeeper.policyAttempt')));
  if (savedPolicyAttempt.status !== 'uncertain' || savedPolicyAttempt.restaurantId !== 'r_stage3') throw new Error('Uncertain policy target was not retained.');
  await page.unroute('**/restaurants/r_stage3/policies');
  let retriedPolicyWrite;
  await page.route('**/restaurants/r_stage3/policies', async (route) => {
    if (route.request().method() === 'POST') retriedPolicyWrite = { body: route.request().postDataJSON(), key: route.request().headers()['idempotency-key'] };
    await route.continue();
  });
  const policyResponse = page.waitForResponse((response) => response.url().endsWith('/restaurants/r_stage3/policies') && response.request().method() === 'POST');
  await page.getByTestId('policy-publish').click();
  const published = await policyResponse;
  if (published.status() !== 200 || (await published.json()).policy_version !== 1 || initialPolicyWrite.key !== retriedPolicyWrite.key || JSON.stringify(initialPolicyWrite.body) !== JSON.stringify(retriedPolicyWrite.body)) throw new Error(`Policy retry changed identity or did not replay: ${published.status()}.`);
  await page.unroute('**/restaurants/r_stage3/policies');
  await page.getByTestId('policy-success').waitFor();

  const bookingDate = await page.evaluate(() => {
    const value = new Date();
    value.setDate(value.getDate() + 14);
    return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
  });
  const competitor = await page.evaluate(async (date) => {
    const response = await fetch('/reservations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('tablekeeper.token')}`, 'Idempotency-Key': 'stage3-occupancy-explanation' },
      body: JSON.stringify({ restaurant_id: 'r_stage3', table_id: 't_b', starts_at_local: `${date}T18:00`, party_size: 4 }),
    });
    return response.status;
  }, bookingDate);
  if (competitor !== 201) throw new Error(`Occupancy fixture booking returned ${competitor}.`);

  await page.getByTestId('date-input').fill(bookingDate);
  await page.getByTestId('party-size-input').fill('4');
  const availabilityResponse = page.waitForResponse((response) => response.url().includes('/availability?'));
  await page.getByTestId('search-button').click();
  if ((await availabilityResponse).status() !== 200) throw new Error('Policy availability search failed.');
  await page.waitForFunction(() => Boolean(document.querySelector('[data-testid="availability-grid"]')));
  const capacityCell = await page.getByTestId('slot-t_a-19:00').innerText();
  const occupiedCell = await page.getByTestId('slot-t_b-19:00').innerText();
  const capacityLabel = await page.getByTestId('slot-t_a-19:00').getAttribute('aria-label');
  if (!capacityCell.includes('Capacity') || !occupiedCell.includes('Occupied') || !capacityLabel.includes('exceeds capacity 3')) throw new Error(`Availability explanations did not use the active policy: ${capacityCell} / ${occupiedCell} / ${capacityLabel}.`);
  await page.getByTestId('slot-t_c-19:00').click();
  const bookingResponse = page.waitForResponse((response) => response.url().endsWith('/reservations') && response.request().method() === 'POST');
  await page.getByTestId('booking-submit').click();
  const booked = await bookingResponse;
  const receipt = await booked.json();
  if (booked.status() !== 201 || receipt.accepted_terms?.policy_version !== 1 || receipt.revision !== 1) throw new Error('Booking receipt omitted its accepted policy terms or revision.');
  await page.getByTestId('confirmation').getByTestId('accepted-terms').waitFor();

  await page.goto(`${base}/lookup?reference=${encodeURIComponent(receipt.reference)}`);
  const lookupResponse = page.waitForResponse((response) => response.url().endsWith(`/reservations/${receipt.reference}`));
  await page.getByTestId('lookup-submit').click();
  if ((await lookupResponse).status() !== 200) throw new Error('Reservation lookup failed.');
  await page.getByTestId('reservation-revision').waitFor();
  await page.getByTestId('reservation-history').locator('summary').click();
  await page.getByTestId('history-entry-1').waitFor();
  await page.getByTestId('series-count').selectOption('3');
  let initialSeriesWrite;
  await page.route('**/series', async (route) => {
    if (route.request().method() === 'POST') {
      initialSeriesWrite = { body: route.request().postDataJSON(), key: route.request().headers()['idempotency-key'] };
      await route.fetch();
      await route.abort();
    } else await route.continue();
  });
  await page.getByTestId('series-create').click();
  await page.getByTestId('series-uncertain').waitFor();
  const savedSeriesAttempt = await page.evaluate(() => JSON.parse(sessionStorage.getItem('tablekeeper.seriesAttempt')));
  if (savedSeriesAttempt.status !== 'uncertain' || savedSeriesAttempt.body.anchor_reference !== receipt.reference) throw new Error('Uncertain series anchor was not retained.');
  await page.unroute('**/series');
  let retriedSeriesWrite;
  await page.route('**/series', async (route) => {
    if (route.request().method() === 'POST') retriedSeriesWrite = { body: route.request().postDataJSON(), key: route.request().headers()['idempotency-key'] };
    await route.continue();
  });
  const seriesResponse = page.waitForResponse((response) => response.url().endsWith('/series') && response.request().method() === 'POST');
  await page.getByTestId('series-create').click();
  const createdSeries = await seriesResponse;
  const seriesReceipt = await createdSeries.json();
  if (createdSeries.status() !== 200 || seriesReceipt.occurrences.length !== 3 || initialSeriesWrite.key !== retriedSeriesWrite.key || JSON.stringify(initialSeriesWrite.body) !== JSON.stringify(retriedSeriesWrite.body)) throw new Error(`Series retry changed identity or returned ${createdSeries.status()} with ${seriesReceipt.occurrences?.length} occurrences.`);
  await page.unroute('**/series');
  await page.getByTestId('series-occurrence-2').waitFor();
  const seriesId = seriesReceipt.series_id;
  const generatedReference = seriesReceipt.occurrences[1].reference;
  const changed = await page.evaluate(async ({ reference }) => {
    const response = await fetch(`/reservations/${encodeURIComponent(reference)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('tablekeeper.token')}` },
      body: JSON.stringify({ expected_revision: 1, table_id: 't_b' }),
    });
    return response.status;
  }, { reference: generatedReference });
  if (changed !== 200) throw new Error(`Individual occurrence change returned ${changed}.`);
  const cancel = page.waitForResponse((response) => response.url().endsWith(`/reservations/${seriesReceipt.occurrences[2].reference}/cancel`));
  await page.getByTestId('series-cancel-2').click();
  if ((await cancel).status() !== 200) throw new Error('Single-click occurrence cancellation failed.');
  await page.waitForFunction(() => document.querySelector('[data-testid="series-exception-1"]') && document.querySelector('[data-testid="series-occurrence-2"]')?.innerText.includes('cancelled'));
  const currentSeries = await page.evaluate(async (id) => {
    const response = await fetch(`/series/${encodeURIComponent(id)}`, { headers: { Authorization: `Bearer ${localStorage.getItem('tablekeeper.token')}` } });
    return response.json();
  }, seriesId);
  if (currentSeries.occurrences[1].exception !== true || currentSeries.occurrences[2].reservation.status !== 'cancelled') throw new Error('Current series did not retain its independent change and cancellation.');

  const layouts = [];
  for (const theme of ['light', 'dark']) {
    await page.evaluate((value) => localStorage.setItem('tablekeeper.theme', value), theme);
    for (const [width, height] of [[375, 812], [640, 360], [768, 900], [1280, 720]]) {
      await page.setViewportSize({ width, height });
      await page.goto(`${base}/`);
      await page.getByTestId('policy-management').locator('summary').click();
      const layout = await page.evaluate(() => ({ width: innerWidth, scrollWidth: document.documentElement.scrollWidth, theme: document.documentElement.dataset.theme }));
      if (layout.scrollWidth > layout.width) throw new Error(`Stage 3 layout overflowed at ${width}px in ${theme}: ${JSON.stringify(layout)}.`);
      layouts.push(layout);
    }
  }
  await page.evaluate(() => { localStorage.removeItem('tablekeeper.token'); localStorage.removeItem('tablekeeper.displayName'); });
  await page.goto(`${base}/login`);
  await page.getByTestId('login-email').fill('diner@example.test');
  await page.getByTestId('login-password').fill('Stage3-Test-Only-Password');
  const dinerLogin = page.waitForResponse((response) => response.url().endsWith('/auth/login'));
  await page.getByTestId('login-submit').click();
  if ((await dinerLogin).status() !== 200) throw new Error('Diner login failed.');
  await page.waitForURL(`${base}/`);
  await page.getByTestId('policy-management').locator('summary').click();
  await page.getByTestId('policy-manager-access').waitFor();
  if (await page.getByTestId('policy-publish-form').count()) throw new Error('A non-manager saw the policy editor.');

  return { policyVersion: 1, policyRetrySameBodyAndKey: true, managerEditorGated: true, publicManagerIdsHidden: true, capacityReason: capacityCell.trim(), occupancyReason: occupiedCell.trim(), acceptedTermsVisible: true, ownerHistoryVisible: true, seriesOccurrences: currentSeries.occurrences.length, seriesRetrySameBodyAndKey: true, independentException: currentSeries.occurrences[1].exception, cancelledOccurrence: currentSeries.occurrences[2].reservation.status, layouts };
}
