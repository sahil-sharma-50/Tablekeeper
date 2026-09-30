async (page) => {
  const base = new URL(page.url()).origin;
  const weekdays = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
  const password = 'Stage4-Test-Only-Password';
  const dateAfter = (days) => {
    const value = new Date();
    value.setDate(value.getDate() + days);
    return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
  };
  const zoneOffset = (day, time, timeZone) => {
    const [year, month, date] = day.split('-').map(Number);
    const [hour, minute] = time.split(':').map(Number);
    const guess = new Date(Date.UTC(year, month - 1, date, hour, minute));
    const zone = new Intl.DateTimeFormat('en-GB', { timeZone, timeZoneName: 'longOffset' }).formatToParts(guess).find((part) => part.type === 'timeZoneName')?.value;
    return zone === 'GMT' ? '+00:00' : zone?.slice(3);
  };
  const fixture = {
    users: [
      { id: 'u_manager', email: 'manager@example.test', password, display_name: 'Test Manager' },
      { id: 'u_diner', email: 'diner@example.test', password, display_name: 'Test Diner' },
    ],
    restaurants: [{
      id: 'r_stage4', name: 'Stage Four Table', timezone: 'Europe/Berlin',
      slot_minutes: 30, reservation_duration_minutes: 90, cancellation_cutoff_minutes: 0,
      opening_hours: weekdays.map((weekday) => ({ weekday, opens: '18:00', closes: '23:00' })),
      tables: [
        { id: 't_1', label: 'Window', capacity: 2 }, { id: 't_2', label: 'Garden', capacity: 4 },
        { id: 't_3', label: 'Terrace', capacity: 4 }, { id: 't_4', label: 'Room', capacity: 6 },
      ],
      combinable: [['t_1', 't_2']], manager_user_ids: ['u_manager'],
    }],
    reservations: [],
  };
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto(base);
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
  const reset = await page.evaluate(async (state) => (await fetch('/_test/reset', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(state),
  })).status, fixture);
  if (reset !== 204) throw new Error(`Stage 4 fixture reset returned ${reset}.`);
  const publicDetail = await page.evaluate(async () => (await fetch('/restaurants/r_stage4')).json());
  if (publicDetail.can_manage_policies !== false || 'manager_user_ids' in publicDetail) throw new Error('Public restaurant detail exposed manager access data.');
  const managerToken = await page.evaluate(async (secret) => {
    const response = await fetch('/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: 'manager@example.test', password: secret }) });
    if (!response.ok) throw new Error(`Manager setup login returned ${response.status}.`);
    return (await response.json()).token;
  }, password);
  const dinerToken = await page.evaluate(async (secret) => {
    const response = await fetch('/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: 'diner@example.test', password: secret }) });
    if (!response.ok) throw new Error(`Diner setup login returned ${response.status}.`);
    return (await response.json()).token;
  }, password);
  const postBooking = async (token, date, tableId, at, key) => page.evaluate(async ({ bearer, day, table, time, idem }) => {
    const response = await fetch('/reservations', {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${bearer}`, 'Idempotency-Key': idem },
      body: JSON.stringify({ restaurant_id: 'r_stage4', table_id: table, starts_at_local: `${day}T${time}`, party_size: 4 }),
    });
    return { status: response.status, body: await response.json() };
  }, { bearer: token, day: date, table: tableId, time: at, idem: key });

  const closureDate = dateAfter(14);
  const closureBookingResult = await postBooking(dinerToken, closureDate, 't_2', '19:00', 'stage4-closure-booking');
  if (closureBookingResult.status !== 201) throw new Error(`Closure booking setup returned ${closureBookingResult.status}.`);
  const closureBooking = closureBookingResult.body;
  await page.goto(`${base}/login`);
  await page.getByTestId('login-email').fill('manager@example.test');
  await page.getByTestId('login-password').fill(password);
  const loginResponse = page.waitForResponse((response) => response.url().endsWith('/auth/login'));
  await page.getByTestId('login-submit').click();
  if ((await loginResponse).status() !== 200) throw new Error('Manager UI login failed.');
  await page.waitForURL(`${base}/`);
  await page.getByTestId('replan-form').waitFor();
  await page.getByRole('link', { name: 'Service recovery' }).click();
  await page.waitForURL(`${base}/#service-recovery`);
  await page.getByTestId('replan-table').selectOption('t_2');
  await page.getByTestId('replan-from').fill(`${closureDate}T18:00`);
  await page.getByTestId('replan-to').fill(`${closureDate}T23:00`);

  let firstPreviewRequest;
  let firstPreviewReceipt;
  await page.route('**/restaurants/r_stage4/replans', async (route) => {
    if (route.request().method() !== 'POST' || firstPreviewRequest) return route.continue();
    firstPreviewRequest = { body: route.request().postDataJSON(), key: route.request().headers()['idempotency-key'] };
    const committed = await route.fetch();
    firstPreviewReceipt = await committed.json();
    await route.abort();
  });
  await page.getByTestId('replan-preview-submit').click();
  await page.getByTestId('replan-preview-uncertain').waitFor();
  const storedPreview = await page.evaluate(() => JSON.parse(sessionStorage.getItem('tablekeeper.replanPreviewAttempt')));
  if (storedPreview.status !== 'uncertain' || storedPreview.restaurantId !== 'r_stage4' || JSON.stringify(storedPreview.body) !== JSON.stringify(firstPreviewRequest.body) || storedPreview.key !== firstPreviewRequest.key) throw new Error('Lost preview response did not retain its original target, body, and key.');
  await page.unroute('**/restaurants/r_stage4/replans');
  let retriedPreviewRequest;
  await page.route('**/restaurants/r_stage4/replans', async (route) => {
    if (route.request().method() === 'POST') retriedPreviewRequest = { body: route.request().postDataJSON(), key: route.request().headers()['idempotency-key'] };
    await route.continue();
  });
  const previewRetryResponse = page.waitForResponse((response) => response.url().endsWith('/restaurants/r_stage4/replans') && response.request().method() === 'POST');
  await page.getByTestId('replan-preview-submit').click();
  const previewRetry = await previewRetryResponse;
  const preview = await previewRetry.json();
  if (previewRetry.status() !== 200 || preview.plan_id !== firstPreviewReceipt.plan_id || JSON.stringify(retriedPreviewRequest.body) !== JSON.stringify(firstPreviewRequest.body) || retriedPreviewRequest.key !== firstPreviewRequest.key) throw new Error('Preview retry changed identity or did not recover the saved plan.');
  await page.unroute('**/restaurants/r_stage4/replans');
  if (preview.closure.table_id !== 't_2' || preview.assignments.length !== 1 || preview.assignments[0].reference !== closureBooking.reference) throw new Error('Preview omitted the actual closure or considered booking.');
  if (Object.keys(preview.assignments[0]).sort().join(',') !== 'changed,reference,table_ids' || preview.assignments[0].table_ids.join('+') !== 't_3') throw new Error('Preview assignment did not match the confirmed API contract.');
  const firstAssignment = page.getByTestId(`replan-assignment-${closureBooking.reference}`);
  const firstAssignmentText = await firstAssignment.innerText();
  if (!(await page.getByTestId('replan-plan-metrics').innerText()).includes(`${preview.moved_count} bookings moved`) || !firstAssignmentText.includes('Prior table assignment is not available') || !firstAssignmentText.includes('After: Terrace')) throw new Error('Preview did not truthfully render the API plan and available labels.');
  const closureBody = firstPreviewRequest.body;
  const expectedClosureOffset = zoneOffset(closureDate, '18:00', 'Europe/Berlin');
  if (!closureBody.from.endsWith(expectedClosureOffset) || !closureBody.to.endsWith(expectedClosureOffset)) throw new Error('Closure instants were not sent with the restaurant timezone offset.');

  const competitorResult = await postBooking(dinerToken, closureDate, 't_3', '19:00', 'stage4-competing-booking');
  if (competitorResult.status !== 201) throw new Error(`Competing reservation returned ${competitorResult.status}.`);
  const staleResponse = page.waitForResponse((response) => response.url().includes('/replans/') && response.url().endsWith('/apply'));
  await page.getByTestId('replan-apply').click();
  const stale = await staleResponse;
  const staleProblem = await stale.json();
  if (stale.status() !== 409 || staleProblem.error?.code !== 'stale_plan') throw new Error(`Competing write did not invalidate the preview: ${stale.status()}.`);
  await page.getByTestId('replan-apply-error').waitFor();
  if (await page.getByTestId('replan-apply').count()) throw new Error('The stale plan remained applyable.');
  const staleState = await page.evaluate(() => ({ active: document.activeElement?.getAttribute('data-testid'), message: document.querySelector('[data-testid="replan-apply-error"]')?.getBoundingClientRect().toJSON(), top: document.querySelector('.site-header')?.getBoundingClientRect().bottom || 0, height: innerHeight }));
  if (staleState.active !== 'replan-apply-error' || !staleState.message || staleState.message.top < staleState.top || staleState.message.bottom > staleState.height) throw new Error(`Stale-plan feedback was not focused and visible: ${JSON.stringify(staleState)}.`);
  if (await page.getByTestId('replan-from').inputValue() !== `${closureDate}T18:00` || await page.getByTestId('replan-to').inputValue() !== `${closureDate}T23:00`) throw new Error('Stale-plan refusal lost the closure form values.');

  const freshPreviewResponse = page.waitForResponse((response) => response.url().endsWith('/restaurants/r_stage4/replans') && response.request().method() === 'POST');
  await page.getByTestId('replan-preview-submit').click();
  const freshPreview = await freshPreviewResponse;
  const freshPlan = await freshPreview.json();
  if (freshPreview.status() !== 201 || freshPlan.assignments.find((item) => item.reference === closureBooking.reference)?.table_ids.join('+') !== 't_4') throw new Error(`Fresh preview did not account for the competitor: ${freshPreview.status()}.`);
  if (freshPlan.moved_count !== freshPlan.assignments.filter((item) => item.changed).length || freshPlan.unused_seats < 0) throw new Error('Preview metrics do not reflect the actual assignment response.');
  const acceptedBeforeApply = closureBooking.accepted_terms;
  let firstApplyRequest;
  let firstApplyReceipt;
  await page.route('**/replans/*/apply', async (route) => {
    if (route.request().method() !== 'POST' || firstApplyRequest) return route.continue();
    firstApplyRequest = { body: route.request().postDataJSON(), key: route.request().headers()['idempotency-key'], url: route.request().url() };
    const committed = await route.fetch();
    firstApplyReceipt = await committed.json();
    await route.abort();
  });
  await page.getByTestId('replan-apply').click();
  await page.getByTestId('replan-apply-uncertain').waitFor();
  const storedApply = await page.evaluate(() => JSON.parse(sessionStorage.getItem('tablekeeper.replanApplyAttempt')));
  if (storedApply.status !== 'uncertain' || storedApply.body && Object.keys(storedApply.body).length !== 0 || storedApply.key !== firstApplyRequest.key || storedApply.plan.plan_id !== freshPlan.plan_id) throw new Error('Lost apply response did not retain the exact plan and original apply identity.');
  await page.unroute('**/replans/*/apply');
  let retriedApplyRequest;
  await page.route('**/replans/*/apply', async (route) => {
    if (route.request().method() === 'POST') retriedApplyRequest = { body: route.request().postDataJSON(), key: route.request().headers()['idempotency-key'], url: route.request().url() };
    await route.continue();
  });
  const applyRetryResponse = page.waitForResponse((response) => response.url().includes('/replans/') && response.url().endsWith('/apply'));
  await page.getByTestId('replan-apply').click();
  const applyRetry = await applyRetryResponse;
  const applyReceipt = await applyRetry.json();
  if (applyRetry.status() !== 200 || retriedApplyRequest.key !== firstApplyRequest.key || JSON.stringify(retriedApplyRequest.body) !== JSON.stringify(firstApplyRequest.body) || retriedApplyRequest.url !== firstApplyRequest.url) throw new Error('Apply retry changed its plan, body, or idempotency key.');
  if (JSON.stringify(applyReceipt) !== JSON.stringify(firstApplyReceipt) || applyReceipt.plan_id !== freshPlan.plan_id || applyReceipt.reservations.length !== freshPlan.assignments.length || applyReceipt.restaurant_revision !== freshPlan.restaurant_revision + 1) throw new Error('Recovered apply receipt did not return the original complete atomic result.');
  await page.unroute('**/replans/*/apply');
  await page.getByTestId('replan-applied').waitFor();
  const appliedBooking = applyReceipt.reservations.find((item) => item.reference === closureBooking.reference);
  if (!appliedBooking || appliedBooking.table_ids.join('+') !== 't_4' || appliedBooking.starts_at_local !== closureBooking.starts_at_local || JSON.stringify(appliedBooking.accepted_terms) !== JSON.stringify(acceptedBeforeApply)) throw new Error('Applied receipt changed the booking time/terms or omitted the moved table.');

  await page.getByTestId('replan-from').fill('2026-10-25T02:30');
  await page.getByTestId('replan-to').fill('2026-10-25T03:30');
  let foldBody;
  await page.route('**/restaurants/r_stage4/replans', async (route) => {
    if (route.request().method() === 'POST') foldBody = route.request().postDataJSON();
    await route.continue();
  });
  const foldResponse = page.waitForResponse((response) => response.url().endsWith('/restaurants/r_stage4/replans') && response.request().method() === 'POST');
  await page.getByTestId('replan-preview-submit').click();
  if ((await foldResponse).status() !== 201 || foldBody.from !== '2026-10-25T02:30:00+02:00' || foldBody.to !== '2026-10-25T03:30:00+01:00') throw new Error(`DST fold did not select the first valid offset: ${JSON.stringify(foldBody)}.`);
  await page.unroute('**/restaurants/r_stage4/replans');
  let gapRequest = false;
  await page.route('**/restaurants/r_stage4/replans', async (route) => {
    if (route.request().method() === 'POST') gapRequest = true;
    await route.continue();
  });
  await page.getByTestId('replan-from').fill('2027-03-28T02:30');
  await page.getByTestId('replan-to').fill('2027-03-28T03:30');
  await page.getByTestId('replan-preview-submit').click();
  await page.getByTestId('replan-preview-error').waitFor();
  if (gapRequest || !(await page.getByTestId('replan-preview-error').innerText()).includes('does not exist')) throw new Error('DST gap was not refused before sending a preview request.');
  await page.unroute('**/restaurants/r_stage4/replans');

  const seriesDate = dateAfter(42);
  const anchorResult = await postBooking(managerToken, seriesDate, 't_2', '19:00', 'stage4-series-anchor');
  if (anchorResult.status !== 201) throw new Error(`Series anchor booking returned ${anchorResult.status}.`);
  const anchor = anchorResult.body;
  await page.goto(`${base}/lookup?reference=${encodeURIComponent(anchor.reference)}`);
  const lookupResponse = page.waitForResponse((response) => response.url().endsWith(`/reservations/${anchor.reference}`));
  await page.getByTestId('lookup-submit').click();
  if ((await lookupResponse).status() !== 200) throw new Error('Series anchor lookup failed.');
  await page.getByTestId('series-create').waitFor();
  await page.getByTestId('series-count').selectOption('5');
  const createSeriesResponse = page.waitForResponse((response) => response.url().endsWith('/series') && response.request().method() === 'POST');
  await page.getByTestId('series-create').click();
  const createdSeriesResponse = await createSeriesResponse;
  const createdSeries = await createdSeriesResponse.json();
  if (![200, 201].includes(createdSeriesResponse.status()) || createdSeries.occurrences.length !== 5) throw new Error('Series setup did not return five current occurrences.');
  const seriesId = createdSeries.series_id;
  const exceptionReference = createdSeries.occurrences[1].reference;
  const exceptionChange = await page.evaluate(async ({ reference, bearer }) => {
    const response = await fetch(`/reservations/${encodeURIComponent(reference)}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${bearer}` },
      body: JSON.stringify({ expected_revision: 1, table_id: 't_3' }),
    });
    return { status: response.status, body: await response.json() };
  }, { reference: exceptionReference, bearer: managerToken });
  if (exceptionChange.status !== 200) throw new Error(`Independent occurrence change returned ${exceptionChange.status}.`);
  await page.goto(`${base}/lookup?reference=${encodeURIComponent(anchor.reference)}&series_id=${encodeURIComponent(seriesId)}`);
  const seriesLookupResponse = page.waitForResponse((response) => response.url().endsWith(`/reservations/${anchor.reference}`));
  await page.getByTestId('lookup-submit').click();
  if ((await seriesLookupResponse).status() !== 200) throw new Error('Series lookup refresh failed.');
  await page.getByTestId('series-occurrence-1').waitFor();
  const cancelResponse = page.waitForResponse((response) => response.url().endsWith(`/reservations/${createdSeries.occurrences[2].reference}/cancel`));
  await page.getByTestId('series-cancel-2').click();
  if ((await cancelResponse).status() !== 200) throw new Error('Series cancellation did not complete in one click.');
  await page.waitForFunction(() => document.querySelector('[data-testid="series-occurrence-2"]')?.innerText.includes('cancelled'));
  const staleSeriesRevision = await page.evaluate(async ({ id, bearer }) => {
    const response = await fetch(`/series/${encodeURIComponent(id)}`, { headers: { Authorization: `Bearer ${bearer}` } });
    return (await response.json()).revision;
  }, { id: seriesId, bearer: managerToken });
  await page.getByTestId('series-amend-from').selectOption('0');
  await page.getByTestId('series-amend-time').fill('20:00');
  const outsideCancel = await page.evaluate(async ({ reference, bearer }) => (await fetch(`/reservations/${encodeURIComponent(reference)}/cancel`, {
    method: 'POST', headers: { Authorization: `Bearer ${bearer}` },
  })).status, { reference: createdSeries.occurrences[4].reference, bearer: managerToken });
  if (outsideCancel !== 200) throw new Error(`Competing occurrence cancellation returned ${outsideCancel}.`);
  const staleAmendResponse = page.waitForResponse((response) => response.url().endsWith(`/series/${seriesId}/amend`));
  await page.getByTestId('series-amend-submit').click();
  const staleAmend = await staleAmendResponse;
  const staleAmendProblem = await staleAmend.json();
  if (staleAmend.status() !== 409 || staleAmendProblem.error?.code !== 'stale_revision') throw new Error(`Competing series write did not reject a stale revision: ${staleAmend.status()}.`);
  await page.getByTestId('series-amend-error').waitFor();
  await page.waitForFunction((revision) => document.querySelector('[data-testid="series-summary"]')?.textContent?.includes(`revision ${revision + 1}`), staleSeriesRevision);
  if (await page.getByTestId('series-amend-from').inputValue() !== '0' || await page.getByTestId('series-amend-time').inputValue() !== '20:00') throw new Error('Stale series refusal lost the amendment form values.');

  let firstAmendRequest;
  let firstAmendReceipt;
  const amendRoute = `**/series/${seriesId}/amend`;
  await page.route(amendRoute, async (route) => {
    if (route.request().method() !== 'POST' || firstAmendRequest) return route.continue();
    firstAmendRequest = { body: route.request().postDataJSON(), key: route.request().headers()['idempotency-key'] };
    const committed = await route.fetch();
    firstAmendReceipt = await committed.json();
    await route.abort();
  });
  await page.getByTestId('series-amend-submit').click();
  await page.getByTestId('series-amend-uncertain').waitFor();
  const storedAmend = await page.evaluate(() => JSON.parse(sessionStorage.getItem('tablekeeper.seriesAmendAttempt')));
  if (storedAmend.status !== 'uncertain' || storedAmend.seriesId !== seriesId || storedAmend.key !== firstAmendRequest.key || JSON.stringify(storedAmend.body) !== JSON.stringify(firstAmendRequest.body)) throw new Error('Lost series amendment response changed its original body or key.');
  if (firstAmendRequest.body.expected_revision !== staleSeriesRevision + 1 || firstAmendRequest.body.from_index !== 0 || firstAmendRequest.body.local_time !== '20:00') throw new Error('Series amendment sent the wrong revision, start index, or time.');
  await page.unroute(amendRoute);
  let retriedAmendRequest;
  await page.route(amendRoute, async (route) => {
    if (route.request().method() === 'POST') retriedAmendRequest = { body: route.request().postDataJSON(), key: route.request().headers()['idempotency-key'] };
    await route.continue();
  });
  const amendRetryResponse = page.waitForResponse((response) => response.url().endsWith(`/series/${seriesId}/amend`));
  await page.getByTestId('series-amend-submit').click();
  const amendRetry = await amendRetryResponse;
  const amendedSeries = await amendRetry.json();
  if (amendRetry.status() !== 200 || retriedAmendRequest.key !== firstAmendRequest.key || JSON.stringify(retriedAmendRequest.body) !== JSON.stringify(firstAmendRequest.body) || JSON.stringify(amendedSeries) !== JSON.stringify(firstAmendReceipt)) throw new Error('Series amendment retry did not recover the original committed response.');
  await page.unroute(amendRoute);
  await page.getByTestId('series-amend-success').waitFor();
  const currentSeries = await page.evaluate(async ({ id, bearer }) => {
    const response = await fetch(`/series/${encodeURIComponent(id)}`, { headers: { Authorization: `Bearer ${bearer}` } });
    return response.json();
  }, { id: seriesId, bearer: managerToken });
  if (currentSeries.occurrences.some((item, index) => item.reference !== createdSeries.occurrences[index].reference || item.reservation.starts_at_local.slice(0, 10) !== createdSeries.occurrences[index].reservation.starts_at_local.slice(0, 10))) throw new Error('Series amendment changed an occurrence reference or scheduled date.');
  if (currentSeries.occurrences[0].reservation.starts_at_local.slice(11, 16) !== '20:00' || currentSeries.occurrences[3].reservation.starts_at_local.slice(11, 16) !== '20:00') throw new Error('Eligible series occurrences did not adopt the new local time.');
  if (currentSeries.occurrences[1].exception !== true || currentSeries.occurrences[1].reservation.table_ids?.join('+') !== 't_3') throw new Error('Independently changed occurrence was not preserved.');
  if (currentSeries.occurrences[2].reservation.status !== 'cancelled' || currentSeries.occurrences[4].reservation.status !== 'cancelled') throw new Error('Cancelled series occurrences were not preserved.');
  if (currentSeries.occurrences[0].reservation.table_ids?.join('+') !== 't_2' || currentSeries.occurrences[3].reservation.table_ids?.join('+') !== 't_2') throw new Error('Series amendment changed current table selections.');

  const layouts = [];
  for (const theme of ['light', 'dark']) {
    await page.evaluate((value) => localStorage.setItem('tablekeeper.theme', value), theme);
    for (const [width, height] of [[375, 812], [640, 360], [768, 900], [1280, 720]]) {
      await page.setViewportSize({ width, height });
      await page.goto(base);
      await page.getByTestId('replan-form').waitFor();
      const layout = await page.evaluate(() => ({ width: innerWidth, scrollWidth: document.documentElement.scrollWidth, theme: document.documentElement.dataset.theme, recoveryWidth: document.querySelector('[data-testid="service-recovery"]')?.getBoundingClientRect().width }));
      if (layout.scrollWidth > layout.width) throw new Error(`Stage 4 recovery overflowed at ${width}px in ${theme}: ${JSON.stringify(layout)}.`);
      layouts.push(layout);
    }
  }
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(base);
  await page.getByTestId('replan-form').waitFor();
  await page.getByTestId('replan-from').fill(`${closureDate}T22:00`);
  await page.getByTestId('replan-to').fill(`${closureDate}T20:00`);
  await page.getByTestId('replan-preview-submit').click();
  await page.getByTestId('replan-preview-error').waitFor();
  const mobileFeedback = await page.evaluate(() => ({ active: document.activeElement?.getAttribute('data-testid'), bounds: document.querySelector('[data-testid="replan-preview-error"]')?.getBoundingClientRect().toJSON(), headerBottom: document.querySelector('.site-header')?.getBoundingClientRect().bottom || 0, height: innerHeight, scrollWidth: document.documentElement.scrollWidth }));
  if (mobileFeedback.active !== 'replan-preview-error' || !mobileFeedback.bounds || mobileFeedback.bounds.top < mobileFeedback.headerBottom || mobileFeedback.bounds.bottom > mobileFeedback.height || mobileFeedback.scrollWidth > 375) throw new Error(`Mobile recovery feedback was not focused and visible: ${JSON.stringify(mobileFeedback)}.`);
  await page.getByTestId('replan-table').focus();
  await page.keyboard.press('Tab');
  const keyboardFocus = await page.evaluate(() => ({ testid: document.activeElement?.getAttribute('data-testid'), outline: getComputedStyle(document.activeElement).outlineStyle, width: getComputedStyle(document.activeElement).outlineWidth }));
  if (keyboardFocus.testid !== 'replan-from' || keyboardFocus.outline === 'none' || parseFloat(keyboardFocus.width) < 2) throw new Error(`Recovery controls lack visible keyboard focus: ${JSON.stringify(keyboardFocus)}.`);
  await page.goto(`${base}/login`);
  await page.getByTestId('login-email').fill('diner@example.test');
  await page.getByTestId('login-password').fill(password);
  const dinerLoginResponse = page.waitForResponse((response) => response.url().endsWith('/auth/login'));
  await page.getByTestId('login-submit').click();
  if ((await dinerLoginResponse).status() !== 200) throw new Error('Diner UI login failed.');
  await page.waitForURL(`${base}/`);
  await page.getByTestId('recovery-manager-access').waitFor();
  if (await page.getByTestId('replan-form').count()) throw new Error('A diner account received manager recovery controls.');
  return {
    previewLostResponseSameBodyKey: true, stalePlanRefused: staleProblem.error.code, previewMetricsAndAvailableTableLabels: true,
    applyLostResponseSamePlanBodyKey: true, appliedReservationPreservedTimeAndTerms: true,
    seriesStaleRevisionRetainedForm: true, amendmentLostResponseSameBodyKey: true,
    seriesExceptionPreserved: currentSeries.occurrences[1].exception, cancelledRows: [currentSeries.occurrences[2].reservation.status, currentSeries.occurrences[4].reservation.status],
    layouts, mobileFeedback, keyboardFocus,
  };
}
