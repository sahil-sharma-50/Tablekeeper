async (page) => {
  const base = new URL(page.url()).origin;
  const cases = [];
  for (const theme of ['light', 'dark']) {
    await page.evaluate((value) => localStorage.setItem('tablekeeper.theme', value), theme);
    for (const route of ['/login', '/signup']) {
      for (const [width, height] of [[640, 360], [683, 384], [720, 450]]) {
        await page.setViewportSize({ width, height });
        await page.goto(`${base}${route}`);
        const layout = await page.evaluate(() => {
          const root = document.documentElement;
          const image = document.querySelector('.auth-art img');
          const imageBox = image.getBoundingClientRect();
          const card = document.querySelector('.auth-card').getBoundingClientRect();
          const controls = [...document.querySelectorAll('.auth-card input, .auth-card button')].map((control) => {
            const box = control.getBoundingClientRect();
            return [box.left, box.right, box.height];
          });
          return {
            width: innerWidth, height: innerHeight, scrollWidth: root.scrollWidth,
            theme: root.dataset.theme, fontLoaded: document.fonts.check('16px "Source Sans 3"'),
            card: [card.left, card.right], controls,
            image: [image.naturalWidth, image.naturalHeight, imageBox.width, imageBox.height, getComputedStyle(image).objectFit],
          };
        });
        if (layout.width !== width || layout.height !== height || layout.scrollWidth > width) throw new Error(`${route} overflows at zoom-equivalent ${width}x${height}.`);
        if (layout.theme !== theme || !layout.fontLoaded) throw new Error(`${route} theme/font failed at zoom-equivalent ${width}x${height}.`);
        if (layout.card[0] < 0 || layout.card[1] > width || layout.controls.some(([left, right, height]) => left < 0 || right > width || height < 44)) throw new Error(`${route} card or controls are clipped/reduced at zoom-equivalent ${width}x${height}.`);
        const [naturalWidth, naturalHeight, imageWidth, imageHeight, fit] = layout.image;
        if (fit !== 'contain' || Math.abs(naturalWidth / naturalHeight - imageWidth / imageHeight) > 0.01) throw new Error(`${route} artwork crops or distorts at zoom-equivalent ${width}x${height}.`);
        cases.push({ route, theme, width, height });
      }
    }
  }
  return { zoomEquivalentCases: cases.length, effectiveViewports: [[640, 360], [683, 384], [720, 450]] };
}
