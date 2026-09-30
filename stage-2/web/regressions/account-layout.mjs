async (page) => {
  const base = new URL(page.url()).origin;
  const weekdays = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
  const restaurant = {
    id: 'r_visual', name: 'Visual Regression Table', timezone: 'Europe/Berlin',
    slot_minutes: 30, reservation_duration_minutes: 90, cancellation_cutoff_minutes: 120,
    opening_hours: weekdays.map((weekday) => ({ weekday, opens: '18:00', closes: '23:00' })),
    tables: [{ id: 't_d', label: 'D', capacity: 5 }], combinable: [],
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

  const email = `account-${Date.now()}@example.invalid`;
  const password = 'VisualRegression-Only-2026';
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto(`${base}/signup`);
  await page.getByTestId('signup-display-name').fill('Visual Regression');
  await page.getByTestId('signup-email').fill(email);
  await page.getByTestId('signup-password').fill(password);
  const createdResponse = page.waitForResponse((response) => response.url().endsWith('/auth/signup'));
  await page.getByTestId('signup-submit').click();
  if ((await createdResponse).status() !== 201) throw new Error('Initial signup failed.');
  await page.waitForURL(`${base}/`);

  let cases = 0;
  for (const theme of ['light', 'dark']) {
    await page.evaluate((value) => localStorage.setItem('tablekeeper.theme', value), theme);
    await page.reload();
    for (const route of ['/login', '/signup']) {
      for (const [width, height] of [[1280, 720], [1366, 768], [1440, 900], [375, 812]]) {
        await page.setViewportSize({ width, height });
        await page.goto(`${base}${route}`);
        const layout = await page.evaluate(() => {
          const root = document.documentElement;
          const image = document.querySelector('.auth-art > img');
          const imageBox = image.getBoundingClientRect();
          const copyBox = document.querySelector('.auth-art > div').getBoundingClientRect();
          return {
            width: innerWidth, height: innerHeight, scrollWidth: root.scrollWidth, scrollHeight: root.scrollHeight,
            theme: root.dataset.theme,
            fonts: [...document.querySelectorAll('body,h1,h2,h3,.brand,.site-header nav')].map((el) => getComputedStyle(el).fontFamily),
            fontLoaded: document.fonts.check('16px "Source Sans 3"'),
            palette: ['--page', '--surface', '--ink', '--rust'].map((name) => getComputedStyle(root).getPropertyValue(name).trim()),
            image: [image.naturalWidth, image.naturalHeight, imageBox.width, imageBox.height, getComputedStyle(image).objectFit],
            copyBelowImage: copyBox.top >= imageBox.bottom,
          };
        });
        if (layout.width !== width || layout.height !== height || layout.scrollWidth > width) throw new Error(`${route} overflows at ${width}x${height}.`);
        if (width >= 1280 && layout.scrollHeight > height) throw new Error(`${route} exceeds ${height}px at ${width}px width.`);
        if (layout.theme !== theme || !layout.fontLoaded || layout.fonts.some((font) => !font.includes('Source Sans 3') || /Georgia|Times New Roman|,\s*serif\b/i.test(font))) throw new Error(`${route} typography/theme failed at ${width}x${height} (${theme}): ${JSON.stringify(layout)}`);
        const expectedPalette = theme === 'light' ? ['#f8f5ef', '#fffdf8', '#303d33', '#9a4f39'] : ['#1c211a', '#262c23', '#ecebdd', '#e99a7c'];
        if (JSON.stringify(layout.palette) !== JSON.stringify(expectedPalette)) throw new Error(`${route} palette mismatch (${theme}).`);
        const [naturalWidth, naturalHeight, imageWidth, imageHeight, fit] = layout.image;
        if (fit !== 'contain' || Math.abs(naturalWidth / naturalHeight - imageWidth / imageHeight) > 0.01 || !layout.copyBelowImage) throw new Error(`${route} artwork crops, distorts, or overlaps its copy at ${width}px.`);
        cases += 1;
      }
    }
  }

  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(`${base}/signup`);
  await page.getByTestId('signup-display-name').fill('Visual Regression');
  await page.getByTestId('signup-email').fill(email);
  await page.getByTestId('signup-password').fill(password);
  const duplicateResponse = page.waitForResponse((response) => response.url().endsWith('/auth/signup'));
  await page.getByTestId('signup-submit').click();
  if ((await duplicateResponse).status() !== 409) throw new Error('Duplicate signup was not refused.');
  const signupAlert = page.getByTestId('auth-error');
  await signupAlert.waitFor();
  const visible = await signupAlert.evaluate((alert) => {
    const box = alert.getBoundingClientRect();
    return [innerHeight, scrollY, box.top, box.bottom, document.activeElement === alert, getComputedStyle(alert).outlineWidth];
  });
  if (visible[2] < 65 || visible[3] > visible[0] || !visible[4] || visible[5] !== '2px') throw new Error('Duplicate-signup alert is not fully visible and focused on mobile.');

  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto(`${base}/login`);
  await page.getByTestId('login-email').fill(email);
  await page.getByTestId('login-password').fill('wrong-password');
  const loginResponse = page.waitForResponse((response) => response.url().endsWith('/auth/login'));
  await page.getByTestId('login-submit').click();
  if ((await loginResponse).status() !== 401) throw new Error('Invalid login was not refused.');
  const loginAlert = page.getByTestId('auth-error');
  await loginAlert.waitFor();
  if (!(await loginAlert.evaluate((alert) => document.activeElement === alert && alert.getBoundingClientRect().bottom <= innerHeight))) throw new Error('Login refusal did not focus the visible alert.');
  await page.getByTestId('login-email').focus();
  await page.keyboard.press('Tab');
  if (!(await page.evaluate(() => document.activeElement.matches(':focus-visible') && getComputedStyle(document.activeElement).outlineWidth === '3px'))) throw new Error('Keyboard focus indicator is missing.');
  return { viewportThemeCases: cases, duplicateSignupVisible: true, loginFailureFocused: true, keyboardFocusVisible: true };
}
