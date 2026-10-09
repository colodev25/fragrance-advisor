/* Real-browser checks for both self-contained widgets. All requests are intercepted. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const vm = require('node:vm');
const { test, before, after } = require('node:test');
const widgetTestRequire = createRequire(path.resolve(__dirname, '../tools/widget-tests/package.json'));
const { chromium } = widgetTestRequire(process.env.WIDGET_PLAYWRIGHT_MODULE || 'playwright');

const root = path.resolve(__dirname, '..');
const files = ['index.html', 'snippets/etualy-advisor.liquid'];
if (fs.existsSync(path.join(root, 'snippet.txt'))) files.push('snippet.txt');
const stateKey = 'etualy_chat_state_v1';
const attack = '\"><img src=x onerror="window.__xss=1"><script>window.__xss=2</script>';
let browser;

function source(file) {
  return fs.readFileSync(path.join(root, file), 'utf8');
}

function script(file) {
  if (file.endsWith('.txt')) return source(file);
  const match = source(file).match(/<script>([\s\S]*?)<\/script>/);
  assert.ok(match, `${file}: widget script must exist`);
  return match[1];
}

function instrumentedScript(file) {
  const original = script(file);
  const hooks = `window.__widgetTest = {
    safeHttpUrl, normalizeProduct, normalizeMessage, renderMarkdownText,
    createProductCard, appendChatRecord, renderOptions, saveChatState,
    restoreChatState, session: () => sessionId,
    records: () => chatMessages, sendUserMessage,
    active: () => activeRequest !== null
  };`;
  const instrumented = file.endsWith('.txt')
    ? original.replace('    restoreChatState();', `${hooks}\n    restoreChatState();`)
    : file.endsWith('.liquid')
    ? original.replace(/\}\)\(\);\s*$/, `${hooks}\n})();`)
    : original + '\n' + hooks;
  assert.ok(instrumented.includes(hooks));
  return instrumented;
}

function instrumentedHtml(file) {
  const original = script(file);
  const instrumented = instrumentedScript(file);
  if (file.endsWith('.txt')) {
    return '<!doctype html><html><head></head><body><script>' + instrumented + '</script></body></html>';
  }
  return source(file).replace(original, instrumented)
    .replace(/{% comment %}[\s\S]*?{% endcomment %}/g, '');
}

before(async () => {
  const options = { headless: true };
  if (process.env.WIDGET_BROWSER_EXECUTABLE) options.executablePath = process.env.WIDGET_BROWSER_EXECUTABLE;
  browser = await chromium.launch(options);
});

after(async () => {
  if (browser) await browser.close();
});

async function fixture(t, file, seed = {}) {
  const revisions = new Map();
  const context = await browser.newContext({ serviceWorkers: 'block' });
  t.after(() => context.close());
  const errors = [];
  const requests = [];
  const responses = [];
  const page = await context.newPage();
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('dialog', (dialog) => { errors.push('Unexpected browser dialog'); dialog.dismiss(); });
  await context.addInitScript((initial) => {
    window.__xss = 0;
    window.__opened = [];
    window.open = (...args) => { window.__opened.push(args); return null; };
    if (!sessionStorage.getItem('__test_seeded')) {
      sessionStorage.setItem('__test_seeded', '1');
      sessionStorage.setItem('etualy_advisor_session_id', 'sess_security');
      sessionStorage.setItem('etualy_advisor_session_key', 'b'.repeat(64));
      Object.entries(initial).forEach(([key, value]) => sessionStorage.setItem(key, value));
    }
  }, seed);
  await context.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin === 'https://widget.test' && url.pathname === '/widget') {
      return route.fulfill({ contentType: 'text/html; charset=utf-8', body: instrumentedHtml(file) });
    }
    if (url.origin === 'https://fragrance-advisor-api.onrender.com') {
      if (request.method() === 'OPTIONS') {
        return route.fulfill({ status: 204, headers: {
          'access-control-allow-origin': '*', 'access-control-allow-methods': 'POST',
          'access-control-allow-headers': 'content-type',
        } });
      }
      requests.push({ path: url.pathname, body: request.postDataJSON() });
      const response = responses.shift() || { status: 200, body: {
        reply: 'Risposta **sicura**', products: [], options: ['Per Lui'], step: 2,
      } };
      if (response.status === 200 && url.pathname === '/chat' && !response.raw) {
        const body = request.postDataJSON();
        const revision = (body.session_context?.revision || revisions.get(body.session_id) || 0) + 1;
        revisions.set(body.session_id, revision);
        response.body.session_context ||= {
          token: body.session_context?.token || 'a'.repeat(32), revision,
          expires_at: Date.parse('2099-01-01T00:00:00Z'),
        };
      }
      return route.fulfill({ status: response.status, contentType: 'application/json',
        headers: { 'access-control-allow-origin': '*', 'access-control-expose-headers': 'Retry-After',
          ...response.headers }, body: JSON.stringify(response.body) });
    }
    if (url.origin === 'https://images.test') {
      return route.fulfill({ contentType: 'image/png', body: Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aF1sAAAAASUVORK5CYII=', 'base64') });
    }
    // Includes fonts, images and any injected resource: no real network access.
    return route.abort();
  });
  await page.goto('https://widget.test/widget', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => Boolean(window.__widgetTest));
  await page.locator('#oaLauncher').click();
  t.after(() => assert.deepEqual(errors, [], 'No JavaScript errors or unexpected dialogs'));
  return { page, requests, responses };
}

function stored(messages, options = []) {
  return JSON.stringify({ version: 3, session_id: 'sess_security', session_key: 'b'.repeat(64), session_context: {
    token: 'a'.repeat(32), revision: 1, expires_at: Date.parse('2099-01-01T00:00:00Z'),
  }, messages,
    options, step: 2, last_message: 'iris' });
}

async function controlledFetch(page) {
  await page.evaluate(() => {
    const original = window.fetch;
    window.__pending = [];
    window.fetch = (url, options) => {
      if (new URL(url).pathname !== '/chat') return original(url, options);
      // Ignora volutamente abort: verifica anche risposte tardive che non si possono cancellare.
      return new Promise((resolve, reject) => {
        window.__pending.push({ body: JSON.parse(options.body), signal: options.signal, resolve, reject });
      });
    };
  });
}

async function resolvePending(page, index, data = { reply: 'Risposta completata', products: [], options: ['Per Lui'], step: 2 }) {
  await page.evaluate(({ index, data }) => {
    const expected = window.__pending[index].body.session_context;
    data.session_context ||= {
      token: expected?.token || 'a'.repeat(32), revision: (expected?.revision || 0) + 1,
      expires_at: Date.now() + 86400000,
    };
    window.__pending[index].resolve(new Response(JSON.stringify(data), { status: 200 }));
  }, { index, data });
}

async function assertSafe(page) {
  const result = await page.evaluate(() => ({
    executed: window.__xss,
    scripts: document.querySelectorAll('#oaMessages script, #oaChips script').length,
    inlineHandlers: [...document.querySelectorAll('#oaMessages *, #oaChips *')]
      .flatMap((element) => [...element.attributes])
      .filter((attribute) => /^on/i.test(attribute.name)).map((attribute) => attribute.name),
  }));
  assert.equal(result.executed, 0);
  assert.equal(result.scripts, 0);
  assert.deepEqual(result.inlineHandlers, []);
}

test('Available widget variants contain the same safe renderer', () => {
  const block = (file) => script(file).split('// BEGIN WIDGET SAFE RENDERING')[1]
    .split('// END WIDGET SAFE RENDERING')[0].trim();
  files.slice(1).forEach((file) => assert.equal(block(files[0]), block(file)));
});

test('Available widget variants contain the same request coordination', () => {
  const block = (file) => script(file).split('// BEGIN WIDGET REQUEST FLOW')[1]
    .split('// END WIDGET REQUEST FLOW')[0].trim();
  files.slice(1).forEach((file) => assert.equal(block(files[0]), block(file)));
});

for (const file of files) {
  test(`${file}: complete script has valid syntax`, () => {
    assert.doesNotThrow(() => new vm.Script(script(file), { filename: file }));
  });

  test(`${file}: startup and initial actions work`, async (t) => {
    const { page, requests } = await fixture(t, file);
    assert.equal(await page.locator('#oaChips button').count(), 2);
    await page.locator('#oaChips button').first().click();
    await page.waitForFunction(() => document.querySelector('#oaChips')?.textContent === 'Per Lui');
    assert.equal(requests.length, 1);
    assert.equal(requests[0].body.message, '🎯 Guidami nella scelta');
    await assertSafe(page);
  });

  test(`${file}: URL validation rejects unsafe schemes and attribute delimiters`, async (t) => {
    const { page } = await fixture(t, file);
    const invalid = ['javascript:alert(1)', 'data:text/html,test', 'file:///test',
      '//evil.test', '/relative', 'https://user:pass@evil.test/',
      'https://example.test/\"onmouseover=alert(1)', "https://example.test/'x",
      'https://example.test/<img>', 'https://example.test/a b',
      'https://example.test/\npath', 'https://example.test/\\path', {}, null];
    const values = await page.evaluate((values) => values.map(window.__widgetTest.safeHttpUrl), invalid);
    assert.deepEqual(values, invalid.map(() => ''));
    assert.equal(await page.evaluate(() => window.__widgetTest.safeHttpUrl('https://example.test/a?q=iris&size=50')), 'https://example.test/a?q=iris&size=50');
    assert.equal(await page.evaluate(() => window.__widgetTest.safeHttpUrl('http://example.test/')), 'http://example.test/');
  });

  test(`${file}: markdown preserves formatting without executing HTML`, async (t) => {
    const { page } = await fixture(t, file);
    await page.evaluate((payload) => {
      window.__widgetTest.appendChatRecord({ kind: 'bot', products: [],
        reply: payload + '\n\n**Iris**\n[sito](https://example.test/) [rischio](javascript:evil)' });
    }, attack);
    const message = page.locator('#oaMessages .oa-msg').last();
    assert.ok((await message.textContent()).includes(attack));
    assert.equal(await message.locator('strong').textContent(), 'Iris');
    assert.equal(await message.locator('p').count(), 2);
    assert.equal(await message.locator('br').count(), 1);
    assert.equal(await message.locator('a').count(), 1);
    assert.equal(await message.locator('a').getAttribute('rel'), 'noopener noreferrer');
    assert.equal(await message.locator('a').getAttribute('href'), 'https://example.test/');
    await assertSafe(page);
  });

  test(`${file}: hostile product fields remain text and invalid URLs are inactive`, async (t) => {
    const { page } = await fixture(t, file);
    await page.evaluate((payload) => {
      const product = window.__widgetTest.normalizeProduct({ name: payload, brand: payload,
        family: payload, story: payload, traits: payload, key_notes: [payload], card_type: 'slideover',
        product_page_url: 'javascript:evil', add_to_cart_url: 'data:text/html,evil',
        image_url: 'https://images.test/x\"onerror=evil', price: 90 });
      window.__widgetTest.appendChatRecord({ kind: 'bot', reply: 'Scheda', products: [product] });
    }, attack);
    const card = page.locator('#oaMessages .oa-product-card');
    assert.ok((await card.textContent()).includes(attack));
    assert.equal(await card.locator('a').count(), 0);
    assert.equal(await card.locator('img').count(), 0);
    assert.equal(await card.locator('.oa-card-placeholder').count(), 1);
    assert.equal(await card.locator('.oa-card-cart-btn').isDisabled(), true);
    assert.equal(await card.locator('.oa-card-title-link').first().getAttribute('title'), 'Visualizza ' + attack + ' su Etualy');
    await card.locator('.oa-card-info-btn').click();
    assert.equal(await card.evaluate((element) => element.classList.contains('is-open')), true);
    await card.locator('.oa-slide-back-btn').click();
    assert.equal(await card.evaluate((element) => element.classList.contains('is-open')), false);
    await assertSafe(page);
  });

  test(`${file}: product links, image loading and cart actions remain functional`, async (t) => {
    const { page } = await fixture(t, file);
    await page.evaluate((payload) => {
      const product = window.__widgetTest.normalizeProduct({ name: payload, brand: 'Etualy', price: 90,
        product_page_url: 'https://shop.test/products/iris', add_to_cart_url: 'https://shop.test/cart/1:1',
        image_url: 'https://images.test/iris.png', key_notes: ['Iris'] });
      window.__widgetTest.appendChatRecord({ kind: 'bot', reply: 'Scheda', products: [product] });
    }, 'Iris "speciale" <edizione>');
    await page.waitForFunction(() => document.querySelector('#oaMessages img')?.classList.contains('is-loaded'));
    assert.equal(await page.locator('#oaMessages img').getAttribute('alt'), 'Iris "speciale" <edizione>');
    assert.equal(await page.locator('#oaMessages .oa-card-front .oa-card-title-link').getAttribute('href'), 'https://shop.test/products/iris');
    await page.locator('#oaMessages .oa-card-cart-btn').click();
    await page.waitForFunction(() => window.__opened.length === 1);
    assert.deepEqual(await page.evaluate(() => window.__opened[0]), ['https://shop.test/cart/1:1', '_blank', 'noopener,noreferrer']);
    await assertSafe(page);
  });

  test(`${file}: image failures show the safe placeholder`, async (t) => {
    const { page } = await fixture(t, file);
    await page.evaluate(() => {
      window.__widgetTest.appendChatRecord({ kind: 'bot', reply: '', products: [
        window.__widgetTest.normalizeProduct({ name: 'Iris', image_url: 'https://blocked.test/missing.png' }),
      ] });
    });
    await page.waitForFunction(() => Boolean(document.querySelector('#oaMessages .oa-card-placeholder')));
    assert.equal(await page.locator('#oaMessages img').count(), 0);
    await assertSafe(page);
  });

  for (const cardType of ['standard', 'slideover']) {
    test(`${file}: ${cardType} details distinguish pyramid and additional notes`, async (t) => {
      const { page } = await fixture(t, file);
      await page.evaluate((card_type) => {
        window.__widgetTest.appendChatRecord({ kind: 'bot', reply: 'Scheda di esempio', products: [{
          name: 'Fragranza di esempio', brand: 'Etualy', card_type, price: 90,
          key_notes: ['Bergamotto', 'Limone', 'Iris', 'Sandalo', 'Cacao', 'Sale'],
          olfactory_pyramid: { top: ['Bergamotto', 'Limone', 'Thé', 'THÉ'], heart: ['Iris'], base: ['Sandalo'] },
          unpositioned_notes: [' iris ', 'Thé', 'Cacao', 'Sale', 'SALE'],
        }] });
      }, cardType);
      const card = page.locator('#oaMessages .oa-product-card');
      await card.locator('.oa-card-info-btn').click();
      assert.deepEqual(await card.locator('.oa-pyramid-stage').allTextContents(), ['Testa', 'Cuore', 'Fondo']);
      assert.deepEqual(await card.locator('.oa-pyramid-row').first().locator('.oa-note-pill').allTextContents(),
        ['Bergamotto', 'Limone', 'Thé']);
      assert.deepEqual(await card.locator('.oa-unpositioned-notes .oa-note-pill').allTextContents(), ['Cacao', 'Sale']);
      assert.equal(await card.locator('.oa-unpositioned-notes .oa-slide-notes-label').textContent(), 'Altre note riportate');
      assert.equal(await card.locator('.oa-notes-caption').textContent(), 'Posizione nella piramide non specificata');
      assert.equal(await card.locator('.oa-card-info-btn').getAttribute('aria-expanded'), 'true');
      assert.equal(await card.locator('.oa-card-front').evaluate((node) => node.inert), true);
      assert.equal(await card.locator('.oa-card-slideover').evaluate((node) => node.inert), false);
      if (file === 'index.html' && cardType === 'slideover' && process.env.WIDGET_SCREENSHOT_DIR) {
        fs.mkdirSync(process.env.WIDGET_SCREENSHOT_DIR, { recursive: true });
        await card.screenshot({ path: path.join(process.env.WIDGET_SCREENSHOT_DIR, 'fragrance-advisor-point7-card.png') });
      }
      await card.locator('.oa-slide-back-btn').click();
      assert.equal(await card.locator('.oa-card-info-btn').getAttribute('aria-expanded'), 'false');
      assert.equal(await card.locator('.oa-card-slideover').evaluate((node) => node.inert), true);
      assert.equal(await card.locator('.oa-card-info-btn').evaluate((node) => node === document.activeElement), true);
      await assertSafe(page);
    });
  }

  test(`${file}: notes without a pyramid persist in standard-card details after navigation`, async (t) => {
    const { page } = await fixture(t, file, { [stateKey]: stored([{ kind: 'welcome' }]) });
    await page.evaluate(() => {
      window.__widgetTest.appendChatRecord({ kind: 'bot', reply: '', products: [{ name: 'Esempio',
        card_type: 'standard', unpositioned_notes: ['Iris', 'Vaniglia', 'Sale'], key_notes: ['Iris', 'Vaniglia', 'Sale'] }] });
    });
    await page.locator('.oa-card-info-btn').click();
    await page.goto('https://widget.test/widget?next=1', { waitUntil: 'domcontentloaded' });
    await page.locator('#oaLauncher').click();
    const card = page.locator('#oaMessages .oa-product-card');
    assert.equal(await card.evaluate((node) => node.classList.contains('is-open')), true);
    assert.equal(await card.locator('.oa-pyramid-notes').count(), 0);
    assert.equal(await card.locator('.oa-unpositioned-notes .oa-slide-notes-label').textContent(), 'Note riportate');
    assert.deepEqual(await card.locator('.oa-unpositioned-notes .oa-note-pill').allTextContents(), ['Iris', 'Vaniglia', 'Sale']);
    const saved = await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key)), stateKey);
    assert.deepEqual(saved.messages.at(-1).products[0].unpositioned_notes, ['Iris', 'Vaniglia', 'Sale']);
    await card.locator('.oa-slide-close-btn').click();
    await assertSafe(page);
  });

  test(`${file}: partial pyramids omit empty stages`, async (t) => {
    const { page } = await fixture(t, file);
    await page.evaluate(() => {
      window.__widgetTest.appendChatRecord({ kind: 'bot', reply: '', products: [{ name: 'Esempio',
        olfactory_pyramid: { top: [], heart: ['Iris'], base: [] }, unpositioned_notes: ['Sale'] }] });
    });
    await page.locator('.oa-card-info-btn').click();
    assert.deepEqual(await page.locator('.oa-pyramid-stage').allTextContents(), ['Cuore']);
    assert.equal(await page.locator('.oa-unpositioned-notes .oa-slide-notes-label').textContent(), 'Altre note riportate');
  });

  for (const restored of [false, true]) {
    test(`${file}: ${restored ? 'saved' : 'received'} profiles separate type and recipient and hide derivation`, async (t) => {
      const product = { name: 'Esempio', ptype: 'Eau de parfum, unisex',
        traits: 'Eau de parfum, unisex • Unisex • Primavera / Estate (dedotta)',
        key_notes: ['Iris'], card_type: 'standard' };
      const messages = [{ kind: 'welcome' }];
      if (restored) messages.push({ kind: 'bot', reply: 'Esempio', products: [product] });
      const { page, responses } = await fixture(t, file, { [stateKey]: stored(messages) });
      if (!restored) {
        responses.push({ status: 200, body: { reply: 'Esempio', products: [product], options: [], step: null, mode: 'free' } });
        await page.evaluate(() => { void window.__widgetTest.sendUserMessage('Parlami di Esempio'); });
      }
      await page.locator('.oa-card-info-btn').click();
      assert.equal(await page.locator('.oa-slide-traits').textContent(), 'Eau de Parfum • Unisex • Primavera / Estate');
      assert.equal(await page.locator('.oa-card-badge').textContent(), 'Eau de Parfum');
      const saved = await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key)), stateKey);
      assert.equal(saved.messages.at(-1).products[0].ptype, 'Eau de Parfum');
      assert.equal(saved.messages.at(-1).products[0].traits, 'Eau de Parfum • Unisex • Primavera / Estate');
      assert.equal(await page.locator('.oa-legacy-notes .oa-slide-notes-label').textContent(), 'Accordi salienti');
      await assertSafe(page);
    });
  }

  test(`${file}: missing notes show a short message and old summaries remain unclassified`, async (t) => {
    const { page } = await fixture(t, file);
    await page.evaluate(() => {
      window.__widgetTest.appendChatRecord({ kind: 'bot', reply: '', products: [
        { name: 'Senza note', family: 'Floreale' }, { name: 'Scheda precedente', key_notes: ['Iris'] },
      ] });
    });
    const cards = page.locator('#oaMessages .oa-product-card');
    await cards.nth(0).locator('.oa-card-info-btn').click();
    assert.equal(await cards.nth(0).locator('.oa-notes-empty').textContent(), 'Note olfattive non disponibili.');
    assert.equal(await cards.nth(0).locator('.oa-pyramid-notes, .oa-unpositioned-notes').count(), 0);
    await cards.nth(1).locator('.oa-card-info-btn').click();
    assert.equal(await cards.nth(1).locator('.oa-legacy-notes .oa-note-pill').textContent(), 'Iris');
    assert.equal(await cards.nth(1).locator('.oa-pyramid-notes, .oa-unpositioned-notes').count(), 0);
  });

  test(`${file}: hostile structured notes remain bounded plain text`, async (t) => {
    const { page } = await fixture(t, file);
    await page.evaluate((payload) => {
      const product = window.__widgetTest.normalizeProduct({ name: 'Esempio',
        olfactory_pyramid: { top: [payload, { html: payload }, '', ' '], heart: 'Iris', base: null, onclick: payload },
        unpositioned_notes: [payload, 'Sale', { html: payload }, false, ' ', 'SALE'] });
      window.__widgetTest.appendChatRecord({ kind: 'bot', reply: '', products: [product] });
    }, attack);
    await page.locator('.oa-card-info-btn').click();
    assert.equal(await page.locator('.oa-pyramid-notes .oa-note-pill').textContent(), attack);
    assert.deepEqual(await page.locator('.oa-unpositioned-notes .oa-note-pill').allTextContents(), ['Sale']);
    const value = await page.evaluate(() => window.__widgetTest.normalizeProduct({
      olfactory_pyramid: ["wrong"], unpositioned_notes: Array.from({ length: 100 }, (_, i) => 'x'.repeat(600) + i) }));
    assert.deepEqual(value.olfactory_pyramid, { top: [], heart: [], base: [] });
    assert.ok(value.unpositioned_notes.length <= 32);
    assert.ok(value.unpositioned_notes.every((note) => note.length <= 500));
    await assertSafe(page);
  });

  test(`${file}: long details scroll on mobile while the close actions remain reachable`, async (t) => {
    const { page } = await fixture(t, file);
    await page.setViewportSize({ width: 360, height: 740 });
    await page.evaluate(() => {
      const notes = Array.from({ length: 32 }, (_, i) => 'Accordo lungo ' + i + 'x'.repeat(100));
      window.__widgetTest.appendChatRecord({ kind: 'bot', reply: '', products: [{ name: 'Esempio',
        olfactory_pyramid: { top: notes, heart: notes, base: notes }, unpositioned_notes: ['Sale'] }] });
    });
    await page.locator('.oa-card-info-btn').click();
    const card = page.locator('#oaMessages .oa-product-card');
    const dimensions = await card.locator('.oa-slide-body').evaluate((node) => ({
      scroll: node.scrollHeight, height: node.clientHeight, width: node.clientWidth, scrollWidth: node.scrollWidth,
    }));
    assert.ok(dimensions.scroll > dimensions.height, 'Long note lists must scroll');
    assert.ok(dimensions.scrollWidth <= dimensions.width + 1, 'Notes must wrap inside the panel');
    assert.ok((await card.boundingBox()).height <= 423, 'Expanded height must stay bounded');
    await card.locator('.oa-slide-back-btn').click();
    assert.equal(await card.evaluate((node) => node.classList.contains('is-open')), false);
    await assertSafe(page);
  });

  for (const viewport of [{ width: 1280, height: 900 }, { width: 360, height: 740 },
    { width: 360, height: 520 }, { width: 360, height: 520, reducedMotion: 'reduce' }]) {
    test(`${file}: selected details stay above the input at ${viewport.width}x${viewport.height} (${viewport.reducedMotion || 'normal motion'})`, async (t) => {
      const { page } = await fixture(t, file);
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      if (viewport.reducedMotion) await page.emulateMedia({ reducedMotion: viewport.reducedMotion });
      await page.evaluate(() => {
        const notes = Array.from({ length: 32 }, (_, i) => 'Nota lunga ' + i + 'x'.repeat(80));
        window.__widgetTest.appendChatRecord({ kind: 'bot', reply: 'Tre proposte', products:
          Array.from({ length: 3 }, (_, i) => ({ name: 'Profumo ' + i,
            olfactory_pyramid: { top: notes, heart: notes, base: notes } })) });
      });
      const cards = page.locator('#oaMessages .oa-product-card');
      const pageScroll = await page.evaluate(() => window.scrollY);
      for (const index of [0, 1, 2, 0, 1, 2, 0]) {
        const card = cards.nth(index);
        await card.locator('.oa-card-info-btn').click();
        try { await page.waitForFunction((i) => {
          const container = document.getElementById('oaMessages');
          const selected = container.querySelectorAll('.oa-product-card')[i];
          const bounds = container.getBoundingClientRect();
          const box = selected.getBoundingClientRect();
          return box.top >= bounds.top - 1 && box.bottom <= bounds.bottom + 1;
        }, index, { timeout: 5000 }); } catch (error) {
          const geometry = await card.evaluate((node) => {
            const container = document.getElementById('oaMessages');
            return { card: node.getBoundingClientRect().toJSON(), container: container.getBoundingClientRect().toJSON(),
              top: container.scrollTop, height: container.scrollHeight, detailHeight: node.style.getPropertyValue('--oa-detail-height') };
          });
          throw new Error(`Card ${index}: ${JSON.stringify(geometry)}`, { cause: error });
        }
        const dimensions = await card.locator('.oa-slide-body').evaluate((node) => ({
          height: node.clientHeight, scroll: node.scrollHeight,
        }));
        assert.ok(dimensions.height > 0 && dimensions.scroll > dimensions.height);
        assert.equal(await page.evaluate(() => window.scrollY), pageScroll, 'Only the chat should scroll');
        await card.locator('.oa-slide-back-btn').click();
      }
      await assertSafe(page);
    });
  }

  test(`${file}: JSON history and option actions survive page navigation`, async (t) => {
    const { page, requests } = await fixture(t, file, { [stateKey]: stored([{ kind: 'welcome' }]) });
    await page.evaluate((payload) => {
      window.__widgetTest.appendChatRecord({ kind: 'user', text: payload });
      window.__widgetTest.appendChatRecord({ kind: 'bot', reply: '**Iris**', products: [
        window.__widgetTest.normalizeProduct({ name: 'Iris', card_type: 'slideover',
          product_page_url: 'https://shop.test/iris', add_to_cart_url: 'https://shop.test/cart/1:1' }),
      ] });
      window.__widgetTest.renderOptions(['Per Lei', payload]);
      window.__widgetTest.saveChatState(2);
    }, attack);
    await page.locator('.oa-card-info-btn').click();
    await page.goto('https://widget.test/widget?next=1', { waitUntil: 'domcontentloaded' });
    await page.locator('#oaLauncher').click();
    assert.equal(await page.locator('.oa-msg-user').textContent(), attack);
    assert.equal(await page.locator('#oaChips button').count(), 2);
    assert.equal(await page.locator('.oa-product-card').evaluate((element) => element.classList.contains('is-open')), true);
    assert.equal(await page.locator('#oaProgress').evaluate((element) => element.style.width), '50%');
    await page.locator('#oaChips button').first().click();
    await page.waitForFunction(() => document.querySelector('#oaChips')?.textContent === 'Per Lui');
    assert.equal(requests[0].body.message, 'Per Lei');
    assert.equal(requests[0].body.session_id, 'sess_security');
    await assertSafe(page);
  });

  test(`${file}: malicious saved JSON is normalized without execution`, async (t) => {
    const { page } = await fixture(t, file, { [stateKey]: stored([
      { kind: 'welcome' }, { kind: 'bot', reply: attack, products: [{ name: attack,
        product_page_url: 'javascript:evil', image_url: 'data:text/html,evil',
        key_notes: [attack, { html: attack }], onclick: 'window.__xss=1' }] },
    ], [attack]) });
    assert.ok((await page.locator('#oaMessages').textContent()).includes(attack));
    assert.equal(await page.locator('#oaChips button').textContent(), attack);
    assert.equal(await page.locator('#oaMessages a, #oaMessages img').count(), 0);
    const saved = await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key)), stateKey);
    assert.equal(saved.messages[1].products[0].onclick, undefined);
    assert.deepEqual(saved.messages[1].products[0].key_notes, [attack]);
    await assertSafe(page);
  });

  test(`${file}: legacy HTML is discarded without parsing or execution`, async (t) => {
    const { page, requests } = await fixture(t, file, {
      etualy_chat_messages: attack, etualy_chat_chips: attack,
      etualy_chat_step: '3', etualy_last_user_message: attack,
    });
    assert.notEqual(await page.evaluate(() => window.__widgetTest.session()), 'sess_security');
    assert.equal(await page.locator('#oaMessages .oa-msg').count(), 1);
    assert.equal(await page.locator('#oaChips button').count(), 2);
    assert.equal(await page.evaluate(() => sessionStorage.getItem('etualy_chat_messages')), null);
    assert.equal(requests.length, 0);
    await assertSafe(page);
  });

  test(`${file}: malformed state starts a fresh local session`, async (t) => {
    const { page } = await fixture(t, file, { [stateKey]: '{invalid json' });
    assert.notEqual(await page.evaluate(() => window.__widgetTest.session()), 'sess_security');
    assert.equal(await page.locator('#oaMessages .oa-msg').count(), 1);
    const saved = await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key)), stateKey);
    assert.equal(saved.version, 3);
    assert.deepEqual(saved.messages, [{ kind: 'welcome' }]);
    await assertSafe(page);
  });

  test(`${file}: remote errors and restored retry controls render safely`, async (t) => {
    const { page, requests, responses } = await fixture(t, file);
    responses.push({ status: 503, body: { error: { message: attack } } });
    await page.locator('#oaInput').fill('iris');
    await page.locator('#oaForm').evaluate((form) => form.requestSubmit());
    await page.locator('.oa-msg-error').waitFor();
    assert.equal(await page.locator('.oa-error-text').textContent(), attack);
    await assertSafe(page);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.locator('#oaLauncher').click();
    await page.locator('.oa-retry-btn').click();
    await page.waitForFunction(() => !document.querySelector('.oa-msg-error') &&
      document.querySelector('#oaMessages .oa-msg:last-child strong')?.textContent === 'sicura');
    assert.equal(requests.length, 2);
    assert.equal(requests[1].body.message, 'iris');
    assert.equal(requests[1].body.request_id, requests[0].body.request_id);
    const saved = await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key)), stateKey);
    assert.equal(saved.messages.some((record) => record.kind === 'error'), false);
    await assertSafe(page);
  });

  test(`${file}: restart clears structured history and resets the previous session`, async (t) => {
    const { page, requests } = await fixture(t, file);
    await page.evaluate(() => {
      window.__widgetTest.appendChatRecord({ kind: 'user', text: 'iris' });
      window.__widgetTest.saveChatState(3);
    });
    await page.locator('#oaRestartBtn').click();
    await page.waitForFunction(() => window.__widgetTest.session() !== 'sess_security');
    await page.waitForTimeout(100);
    assert.equal(requests[0].path, '/reset');
    assert.equal(requests[0].body.session_id, 'sess_security');
    const saved = await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key)), stateKey);
    assert.equal(saved.step, null);
    assert.equal(saved.last_message, '');
    assert.deepEqual(saved.messages, [{ kind: 'welcome' }]);
    await assertSafe(page);
  });

  test(`${file}: simultaneous sends produce one request and keep controls blocked until completion`, async (t) => {
    const { page } = await fixture(t, file);
    await controlledFetch(page);
    await page.evaluate(() => {
      void window.__widgetTest.sendUserMessage('iris');
      void window.__widgetTest.sendUserMessage('rosa');
      document.querySelector('#oaInput').value = 'secondo invio';
      document.querySelector('#oaForm').dispatchEvent(new Event('submit', { cancelable: true }));
    });
    assert.equal(await page.evaluate(() => window.__pending.length), 1);
    assert.equal(await page.locator('#oaInput').isDisabled(), true);
    assert.equal(await page.locator('#oaForm button[type="submit"]').isDisabled(), true);
    assert.equal(await page.locator('#oaRestartBtn').isDisabled(), false);
    assert.equal(await page.locator('.oa-msg-user').count(), 1);
    assert.equal(await page.locator('#oaInput').inputValue(), 'secondo invio');
    assert.match(await page.evaluate(() => window.__pending[0].body.request_id), /^req_[A-Za-z0-9_-]+$/);
    await resolvePending(page, 0);
    await page.waitForFunction(() => !window.__widgetTest.active());
    assert.equal(await page.locator('#oaInput').isDisabled(), false);
    assert.equal(await page.locator('#oaChips button').isDisabled(), false);
    assert.equal(await page.locator('#oaMessages').getAttribute('aria-busy'), 'false');
  });

  for (const outcome of ['success', 'failure']) {
    test(`${file}: late ${outcome} after reset cannot affect the new pending conversation`, async (t) => {
      const { page, requests } = await fixture(t, file);
      await controlledFetch(page);
      await page.evaluate(() => { void window.__widgetTest.sendUserMessage('iris'); });
      await page.locator('#oaRestartBtn').click();
      assert.equal(await page.evaluate(() => window.__pending[0].signal.aborted), true);
      assert.equal(await page.locator('.oa-msg-user').count(), 0);
      await page.evaluate(() => { void window.__widgetTest.sendUserMessage('rosa'); });
      assert.equal(await page.evaluate(() => window.__pending.length), 2);
      assert.notEqual(await page.evaluate(() => window.__pending[1].body.session_id), 'sess_security');
      if (outcome === 'success') {
        await resolvePending(page, 0, { reply: 'RISPOSTA VECCHIA', products: [], options: ['vecchie'], step: 4 });
      } else {
        await page.evaluate(() => window.__pending[0].reject(new TypeError('ERRORE VECCHIO')));
      }
      assert.equal(await page.evaluate(() => window.__widgetTest.active()), true);
      assert.equal(await page.locator('#oaInput').isDisabled(), true);
      assert.equal(await page.locator('#oaTypingIndicator').count(), 1);
      assert.equal(await page.locator('.oa-msg-error').count(), 0);
      assert.equal((await page.locator('#oaMessages').textContent()).includes('VECCH'), false);
      await resolvePending(page, 1);
      await page.waitForFunction(() => !window.__widgetTest.active());
      assert.equal(await page.locator('.oa-msg-user').textContent(), 'rosa');
      assert.equal(await page.locator('#oaProgress').evaluate((element) => element.style.width), '50%');
      assert.equal(await page.locator('#oaTypingIndicator').count(), 0);
      await page.waitForFunction(() => document.querySelector('#oaChips')?.textContent === 'Per Lui');
      assert.equal(requests.find((request) => request.path === '/reset').body.session_id, 'sess_security');
      const state = await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key)), stateKey);
      assert.equal(state.pending_request, null);
      assert.equal(state.messages.some((record) => JSON.stringify(record).includes('VECCH')), false);
    });
  }

  test(`${file}: retry uses its saved message identity even if the global last message differs`, async (t) => {
    const { page, requests, responses } = await fixture(t, file);
    responses.push({ status: 503, body: { error: { message: 'Errore temporaneo' } } });
    await page.evaluate(() => { void window.__widgetTest.sendUserMessage('iris'); });
    await page.locator('.oa-msg-error').waitFor();
    await page.evaluate((key) => {
      const state = JSON.parse(sessionStorage.getItem(key));
      state.last_message = 'rosa';
      sessionStorage.setItem(key, JSON.stringify(state));
    }, stateKey);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.locator('#oaLauncher').click();
    await page.locator('.oa-retry-btn').click();
    await page.waitForFunction(() => !window.__widgetTest.active() && !document.querySelector('.oa-msg-error'));
    assert.equal(requests.length, 2);
    assert.deepEqual(requests[1].body, requests[0].body);
    assert.equal(await page.locator('.oa-msg-user').count(), 1);
  });

  test(`${file}: double retry reuses one request without another user bubble`, async (t) => {
    const { page, responses } = await fixture(t, file);
    responses.push({ status: 503, body: { error: { message: 'Errore temporaneo' } } });
    await page.evaluate(() => { void window.__widgetTest.sendUserMessage('iris'); });
    await page.locator('.oa-msg-error').waitFor();
    const original = await page.evaluate(() => window.__widgetTest.records().at(-1).request);
    await controlledFetch(page);
    await page.locator('.oa-retry-btn').evaluate((button) => { button.click(); button.click(); });
    assert.equal(await page.evaluate(() => window.__pending.length), 1);
    assert.deepEqual(await page.evaluate(() => window.__pending[0].body), original);
    assert.equal(await page.locator('.oa-msg-user').count(), 1);
    await resolvePending(page, 0);
    await page.waitForFunction(() => !window.__widgetTest.active());
    assert.equal(await page.locator('.oa-msg-error').count(), 0);
  });

  test(`${file}: navigation during a pending request preserves its identity for recovery`, async (t) => {
    const { page, requests } = await fixture(t, file);
    await controlledFetch(page);
    await page.evaluate(() => { void window.__widgetTest.sendUserMessage('iris'); });
    const original = await page.evaluate(() => window.__pending[0].body);
    const pending = await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key)).pending_request, stateKey);
    assert.deepEqual(pending, original);
    await page.goto('https://widget.test/widget?pending=1', { waitUntil: 'domcontentloaded' });
    await page.locator('#oaLauncher').click();
    assert.equal(await page.locator('.oa-msg-user').textContent(), 'iris');
    assert.equal(await page.locator('.oa-retry-btn').count(), 1);
    assert.equal(requests.length, 0, 'Recovery waits for the customer to retry');
    await page.locator('.oa-retry-btn').click();
    await page.waitForFunction(() => !window.__widgetTest.active() && !document.querySelector('.oa-msg-error'));
    assert.deepEqual(requests[0].body, original);
    assert.equal(await page.locator('.oa-msg-user').count(), 1);
    assert.equal(await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key)).pending_request, stateKey), null);
  });

  test(`${file}: a new message retires older retries and uses a new identifier`, async (t) => {
    const { page, requests, responses } = await fixture(t, file);
    responses.push({ status: 503, body: { error: { message: 'Errore temporaneo' } } });
    await page.evaluate(() => { void window.__widgetTest.sendUserMessage('iris'); });
    await page.locator('.oa-retry-btn').waitFor();
    await page.evaluate(() => { void window.__widgetTest.sendUserMessage('rosa'); });
    await page.waitForFunction(() => !window.__widgetTest.active() && document.querySelector('#oaChips')?.textContent === 'Per Lui');
    assert.notEqual(requests[0].body.request_id, requests[1].body.request_id);
    assert.equal(await page.locator('.oa-retry-btn').count(), 0);
    await page.reload({ waitUntil: 'domcontentloaded' });
    assert.equal(await page.locator('.oa-retry-btn').count(), 0);
    assert.equal(await page.locator('.oa-msg-user').count(), 2);
  });

  test(`${file}: legacy errors without request identifiers remain visible without an unsafe retry`, async (t) => {
    const { page } = await fixture(t, file, { [stateKey]: stored([
      { kind: 'welcome' }, { kind: 'user', text: 'iris' },
      { kind: 'error', text: 'Errore precedente', retryable: true },
    ]) });
    assert.equal(await page.locator('.oa-msg-error').count(), 1);
    assert.equal(await page.locator('.oa-retry-btn').count(), 0);
    assert.equal(await page.locator('#oaInput').isDisabled(), false);
  });

  test(`${file}: conflicting or expired results do not offer retry and unlock the input`, async (t) => {
    const { page, responses } = await fixture(t, file);
    responses.push({ status: 409, body: { error: { code: 'request_result_expired', message: 'Invia un nuovo messaggio' } } });
    await page.evaluate(() => { void window.__widgetTest.sendUserMessage('iris'); });
    await page.locator('.oa-msg-error').waitFor();
    assert.equal(await page.locator('.oa-retry-btn').count(), 0);
    assert.equal(await page.locator('#oaInput').isDisabled(), false);
    assert.equal(await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key)).pending_request, stateKey), null);
  });

  test(`${file}: request deadline ends the wait and retry retains the message identity`, async (t) => {
    const { page } = await fixture(t, file);
    await page.clock.install();
    await controlledFetch(page);
    await page.evaluate(() => { void window.__widgetTest.sendUserMessage('iris'); });
    const original = await page.evaluate(() => window.__pending[0].body);
    await page.clock.runFor(60001);
    assert.equal(await page.evaluate(() => window.__widgetTest.active()), false);
    assert.equal(await page.evaluate(() => window.__pending[0].signal.aborted), true);
    assert.equal(await page.locator('.oa-retry-btn').count(), 1);
    assert.equal(await page.locator('#oaTypingIndicator').count(), 0);
    assert.equal(await page.locator('#oaInput').isDisabled(), false);
    await page.locator('.oa-retry-btn').click();
    assert.deepEqual(await page.evaluate(() => window.__pending[1].body), original);
    await resolvePending(page, 0, { reply: 'VECCHIA RISPOSTA', products: [], options: ['vecchia'] });
    assert.equal(await page.evaluate(() => window.__widgetTest.active()), true);
    assert.equal((await page.locator('#oaMessages').textContent()).includes('VECCHIA'), false);
    await resolvePending(page, 1);
    await page.waitForFunction(() => !window.__widgetTest.active());
    assert.equal(await page.locator('.oa-msg-user').count(), 1);
  });

  test(`${file}: deadline also covers a response body that never completes`, async (t) => {
    const { page } = await fixture(t, file);
    await page.clock.install();
    await controlledFetch(page);
    await page.evaluate(() => {
      void window.__widgetTest.sendUserMessage('iris');
      window.__pending[0].resolve({ ok: true, json: () => new Promise(() => {}) });
    });
    await page.clock.runFor(60001);
    assert.equal(await page.evaluate(() => window.__widgetTest.active()), false);
    assert.equal(await page.locator('.oa-retry-btn').count(), 1);
    assert.match(await page.locator('.oa-error-text').textContent(), /troppo tempo/);
  });

  test(`${file}: numeric Retry-After blocks sends and counts down until retry is allowed`, async (t) => {
    const { page, responses, requests } = await fixture(t, file);
    await page.clock.install();
    responses.push({ status: 503, headers: { 'Retry-After': '5' },
      body: { error: { code: 'llm_rate_limit', message: 'Attendi' } } });
    await page.evaluate(() => { void window.__widgetTest.sendUserMessage('iris'); });
    await page.locator('.oa-retry-btn').waitFor();
    await page.waitForFunction(() => !window.__widgetTest.active());
    assert.equal(await page.locator('.oa-retry-btn').isDisabled(), true);
    assert.equal(await page.locator('#oaInput').isDisabled(), true);
    assert.match(await page.locator('.oa-retry-btn').textContent(), /Riprova tra 5 s/);
    await page.evaluate(() => {
      void window.__widgetTest.sendUserMessage('rosa');
      document.querySelector('#oaForm').dispatchEvent(new Event('submit', { cancelable: true }));
      document.querySelector('.oa-retry-btn').click();
    });
    assert.equal(requests.length, 1);
    await page.clock.runFor(2000);
    assert.match(await page.locator('.oa-retry-btn').textContent(), /Riprova tra 3 s/);
    await page.clock.runFor(3001);
    assert.equal(await page.locator('.oa-retry-btn').isDisabled(), false);
    assert.equal(await page.locator('#oaInput').isDisabled(), false);
    await page.locator('.oa-retry-btn').click();
    await page.waitForFunction(() => !window.__widgetTest.active() && !document.querySelector('.oa-msg-error'));
    assert.deepEqual(requests[1].body, requests[0].body);
  });

  test(`${file}: cooldown and retry identity survive navigation`, async (t) => {
    const { page, requests, responses } = await fixture(t, file);
    await page.clock.install();
    responses.push({ status: 429, headers: { 'Retry-After': '10' },
      body: { error: { message: 'Troppe richieste' } } });
    await page.evaluate(() => { void window.__widgetTest.sendUserMessage('iris'); });
    await page.waitForFunction(() => !window.__widgetTest.active() && Boolean(document.querySelector('.oa-retry-btn')));
    const deadline = await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key)).retry_until, stateKey);
    await page.clock.runFor(3000);
    await page.goto('https://widget.test/widget?cooldown=1', { waitUntil: 'domcontentloaded' });
    await page.locator('#oaLauncher').click();
    assert.equal(await page.locator('.oa-retry-btn').isDisabled(), true);
    assert.equal(await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key)).retry_until, stateKey), deadline);
    await page.clock.runFor(7001);
    assert.equal(await page.locator('.oa-retry-btn').isDisabled(), false);
    await page.locator('.oa-retry-btn').click();
    await page.waitForFunction(() => !window.__widgetTest.active());
    assert.deepEqual(requests[1].body, requests[0].body);
  });

  test(`${file}: restart preserves a server cooldown and unlocks when it expires`, async (t) => {
    const { page, responses } = await fixture(t, file);
    await page.clock.install();
    responses.push({ status: 503, headers: { 'Retry-After': '5' }, body: { error: { message: 'Attendi' } } });
    await page.evaluate(() => { void window.__widgetTest.sendUserMessage('iris'); });
    await page.waitForFunction(() => !window.__widgetTest.active() && Boolean(document.querySelector('.oa-retry-btn')));
    await page.locator('#oaRestartBtn').click();
    assert.equal(await page.locator('.oa-retry-btn').count(), 0);
    assert.equal(await page.locator('#oaInput').isDisabled(), true);
    assert.equal(await page.locator('#oaChips button').first().isDisabled(), true);
    await page.clock.runFor(5001);
    assert.equal(await page.locator('#oaInput').isDisabled(), false);
    assert.equal(await page.locator('#oaChips button').first().isDisabled(), false);
  });

  test(`${file}: HTTP-date Retry-After is understood`, async (t) => {
    const { page, responses } = await fixture(t, file);
    await page.clock.install({ time: new Date('2026-10-08T12:00:00Z') });
    responses.push({ status: 503, headers: { 'Retry-After': 'Thu, 08 Oct 2026 12:00:04 GMT' },
      body: { error: { message: 'Attendi' } } });
    await page.evaluate(() => { void window.__widgetTest.sendUserMessage('iris'); });
    await page.waitForFunction(() => !window.__widgetTest.active() && Boolean(document.querySelector('.oa-retry-btn')));
    assert.equal(await page.locator('.oa-retry-btn').isDisabled(), true);
    await page.clock.runFor(4001);
    assert.equal(await page.locator('.oa-retry-btn').isDisabled(), false);
  });

  for (const invalid of ['non-valido', '-1', '0']) {
    test(`${file}: invalid or elapsed Retry-After (${invalid}) does not block the interface`, async (t) => {
      const { page, responses } = await fixture(t, file);
      responses.push({ status: 503, headers: { 'Retry-After': invalid }, body: { error: { message: 'Riprova' } } });
      await page.evaluate(() => { void window.__widgetTest.sendUserMessage('iris'); });
      await page.waitForFunction(() => !window.__widgetTest.active() && Boolean(document.querySelector('.oa-retry-btn')));
      assert.equal(await page.locator('.oa-retry-btn').isDisabled(), false);
      assert.equal(await page.locator('#oaInput').isDisabled(), false);
    });
  }

  test(`${file}: fast success clears the deadline timer and never creates a delayed error`, async (t) => {
    const { page } = await fixture(t, file);
    await page.clock.install();
    await page.evaluate(() => { void window.__widgetTest.sendUserMessage('iris'); });
    await page.waitForFunction(() => !window.__widgetTest.active() && document.querySelector('#oaChips')?.textContent === 'Per Lui');
    await page.clock.runFor(60001);
    assert.equal(await page.locator('.oa-msg-error').count(), 0);
    assert.equal(await page.locator('#oaInput').isDisabled(), false);
  });


  test(`${file}: new replies persist session metadata and following requests carry it`, async (t) => {
    const { page, requests } = await fixture(t, file);
    await page.evaluate(() => { void window.__widgetTest.sendUserMessage('iris'); });
    await page.waitForFunction(() => !window.__widgetTest.active() && document.querySelector('#oaChips')?.textContent === 'Per Lui');
    const context = await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key)).session_context, stateKey);
    assert.equal(context.revision, 1);
    assert.equal(requests[0].body.session_key, 'b'.repeat(64));
    await page.goto('https://widget.test/widget?metadata=1', { waitUntil: 'domcontentloaded' });
    await page.locator('#oaLauncher').click();
    await page.evaluate(() => { void window.__widgetTest.sendUserMessage('quanto costa?'); });
    await page.waitForFunction(() => !window.__widgetTest.active() && document.querySelector('#oaChips')?.textContent === 'Per Lui');
    assert.deepEqual(requests[1].body.session_context, { token: context.token, revision: 1 });
    assert.equal(requests[1].body.session_key, requests[0].body.session_key);
    assert.equal(await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key)).session_context.revision, stateKey), 2);
  });

  for (const code of ['session_expired', 'session_out_of_sync', 'session_access_denied', 'session_context_required', 'session_migration_required']) {
    test(`${file}: ${code} restarts locally and keeps the unsent message without auto-resending`, async (t) => {
      const { page, requests, responses } = await fixture(t, file);
      await page.evaluate(() => { void window.__widgetTest.sendUserMessage('iris'); });
      await page.waitForFunction(() => !window.__widgetTest.active() && document.querySelector('#oaChips')?.textContent === 'Per Lui');
      const sid = await page.evaluate(() => window.__widgetTest.session());
      responses.push({ status: code === 'session_access_denied' ? 403 : 409, body: { error: { code, message: 'Ripartiamo' } } });
      await page.evaluate(() => { void window.__widgetTest.sendUserMessage('quanto costa?'); });
      await page.waitForFunction((sid) => window.__widgetTest.session() !== sid, sid);
      assert.equal(requests.length, 2);
      assert.equal(await page.locator('.oa-msg-user').count(), 0);
      assert.equal(await page.locator('.oa-retry-btn').count(), 0);
      assert.equal(await page.locator('#oaInput').inputValue(), 'quanto costa?');
      assert.equal(await page.locator('#oaChips button').count(), 2);
      await page.goto('https://widget.test/widget?draft=1', { waitUntil: 'domcontentloaded' });
      await page.locator('#oaLauncher').click();
      assert.equal(await page.locator('#oaInput').inputValue(), 'quanto costa?');
      await page.locator('#oaForm button[type="submit"]').click();
      await page.waitForFunction(() => !window.__widgetTest.active() && document.querySelector('#oaChips')?.textContent === 'Per Lui');
      assert.equal(requests.length, 3);
      assert.notEqual(requests[2].body.session_id, sid);
      assert.notEqual(requests[2].body.request_id, requests[1].body.request_id);
      assert.notEqual(requests[2].body.session_key, requests[1].body.session_key);
      assert.match(requests[2].body.session_key, /^[a-f0-9]{64}$/);
      assert.equal(requests[2].body.session_context, undefined);
    });
  }

  test(`${file}: expired local state resets on navigation and preserves a pending draft`, async (t) => {
    const state = JSON.parse(stored([{ kind: 'welcome' }, { kind: 'user', text: 'iris' }]));
    state.session_context.expires_at = 1;
    state.pending_request = { message: 'quanto costa?', session_id: 'sess_security', session_key: 'b'.repeat(64), request_id: 'req_pending' };
    const { page, requests } = await fixture(t, file, { [stateKey]: JSON.stringify(state) });
    assert.notEqual(await page.evaluate(() => window.__widgetTest.session()), 'sess_security');
    assert.equal(await page.locator('#oaInput').inputValue(), 'quanto costa?');
    assert.equal(requests.length, 0);
    assert.equal(await page.locator('.oa-msg-user').count(), 0);
    assert.match(await page.locator('.oa-error-text').textContent(), /scaduta/);
  });

  test(`${file}: expiry while a page stays open preserves the typed message without sending`, async (t) => {
    const { page, requests } = await fixture(t, file);
    await page.clock.install();
    await page.evaluate(() => { void window.__widgetTest.sendUserMessage('iris'); });
    await page.waitForFunction(() => !window.__widgetTest.active() && document.querySelector('#oaChips')?.textContent === 'Per Lui');
    const sid = await page.evaluate(() => window.__widgetTest.session());
    await page.clock.setSystemTime(new Date('2099-01-01T00:00:01Z'));
    assert.ok(await page.evaluate(() => Date.now() > Date.parse('2099-01-01T00:00:00Z')));
    await page.evaluate(() => { void window.__widgetTest.sendUserMessage('vorrei rosa'); });
    assert.notEqual(await page.evaluate(() => window.__widgetTest.session()), sid);
    assert.equal(await page.locator('#oaInput').inputValue(), 'vorrei rosa');
    assert.equal(requests.length, 1);
  });

  for (const version of [1, 2]) {
  test(`${file}: old schema ${version} is retired with a clear notice and pending draft retained`, async (t) => {
    const state = JSON.parse(stored([{ kind: 'welcome' }]));
    state.version = version;
    state.pending_request = { message: 'iris', session_id: 'sess_security', session_key: 'b'.repeat(64), request_id: 'req_old' };
    const { page, requests } = await fixture(t, file, { [stateKey]: JSON.stringify(state) });
    assert.notEqual(await page.evaluate(() => window.__widgetTest.session()), 'sess_security');
    assert.match(await page.locator('.oa-error-text').textContent(), /aggiornato/);
    assert.equal(await page.locator('#oaInput').inputValue(), 'iris');
    assert.equal(requests.length, 0);
  });
  }

  test(`${file}: a fresh credential is cryptographic, persisted before send and rotated on reset`, async (t) => {
    const { page, requests } = await fixture(t, file, { etualy_advisor_session_key: '' });
    const initial = await page.evaluate(() => ({
      id: window.__widgetTest.session(), key: sessionStorage.getItem('etualy_advisor_session_key'),
    }));
    assert.notEqual(initial.id, 'sess_security');
    assert.match(initial.key, /^[a-f0-9]{64}$/);
    assert.notEqual(initial.key, 'b'.repeat(64));
    await page.evaluate(() => { void window.__widgetTest.sendUserMessage('iris'); });
    await page.waitForFunction(() => !window.__widgetTest.active() && document.querySelector('#oaChips')?.textContent === 'Per Lui');
    assert.equal(requests[0].body.session_key, initial.key);
    assert.equal(await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key)).session_key, stateKey), initial.key);
    assert.equal((await page.locator('#oaMessages').textContent()).includes(initial.key), false);
    await page.locator('#oaRestartBtn').click();
    await page.waitForFunction((key) => sessionStorage.getItem('etualy_advisor_session_key') !== key, initial.key);
    await page.waitForFunction(() => document.querySelector('#oaInput').disabled === false);
    await page.evaluate(() => { void window.__widgetTest.sendUserMessage('rosa'); });
    await page.waitForFunction(() => !window.__widgetTest.active() && document.querySelector('#oaChips')?.textContent === 'Per Lui');
    const reset = requests.find((request) => request.path === '/reset');
    assert.equal(reset.body.session_key, initial.key);
    assert.equal(reset.body.session_id, initial.id);
    const next = requests.filter((request) => request.path === '/chat').at(-1).body;
    assert.notEqual(next.session_key, initial.key);
    assert.notEqual(next.session_id, initial.id);
  });

  test(`${file}: losing a saved credential restarts safely and preserves the interrupted message`, async (t) => {
    const state = JSON.parse(stored([{ kind: 'welcome' }]));
    state.pending_request = { message: 'iris', session_id: 'sess_security', session_key: 'b'.repeat(64), request_id: 'req_pending' };
    const { page, requests } = await fixture(t, file, { [stateKey]: JSON.stringify(state), etualy_advisor_session_key: '' });
    assert.notEqual(await page.evaluate(() => window.__widgetTest.session()), 'sess_security');
    assert.equal(await page.locator('#oaInput').inputValue(), 'iris');
    assert.equal(await page.locator('.oa-retry-btn').count(), 0);
    assert.equal(requests.length, 0);
  });

  test(`${file}: unsent drafts survive navigation without creating requests`, async (t) => {
    const { page, requests } = await fixture(t, file);
    await page.locator('#oaInput').fill('cerco iris');
    await page.goto('https://widget.test/widget?draft=1', { waitUntil: 'domcontentloaded' });
    await page.locator('#oaLauncher').click();
    assert.equal(await page.locator('#oaInput').inputValue(), 'cerco iris');
    assert.equal(requests.length, 0);
  });

  test(`${file}: success without valid session metadata remains retryable`, async (t) => {
    const { page, responses } = await fixture(t, file);
    responses.push({ status: 200, raw: true, body: { reply: 'Non verificata', products: [], options: [] } });
    await page.evaluate(() => { void window.__widgetTest.sendUserMessage('iris'); });
    await page.waitForFunction(() => !window.__widgetTest.active() && Boolean(document.querySelector('.oa-retry-btn')));
    assert.equal((await page.locator('#oaMessages').textContent()).includes('Non verificata'), false);
    assert.equal(await page.locator('.oa-retry-btn').isDisabled(), false);
  });

  test(`${file}: delayed success from another session version cannot replace the conversation`, async (t) => {
    const { page, requests, responses } = await fixture(t, file, { [stateKey]: stored([{ kind: 'welcome' }]) });
    responses.push({ status: 200, raw: true, body: {
      reply: 'CONTESTO ERRATO', products: [], options: [], session_context: {
        token: 'b'.repeat(32), revision: 2, expires_at: Date.parse('2099-01-01T00:00:00Z'),
      },
    } });
    await page.evaluate(() => { void window.__widgetTest.sendUserMessage('iris'); });
    await page.waitForFunction(() => window.__widgetTest.session() !== 'sess_security');
    assert.equal((await page.locator('#oaMessages').textContent()).includes('CONTESTO ERRATO'), false);
    assert.equal(await page.locator('#oaInput').inputValue(), 'iris');
    assert.equal(requests.length, 1);
  });

}

test('snippet.txt: reinserting the preview cleans up the old wait and restores its request',
  { skip: !files.includes('snippet.txt') }, async (t) => {
  const { page } = await fixture(t, 'snippet.txt');
  await controlledFetch(page);
  await page.evaluate(() => { void window.__widgetTest.sendUserMessage('iris'); });
  const original = await page.evaluate(() => window.__pending[0].body);
  await page.addScriptTag({ content: instrumentedScript('snippet.txt') });
  await page.locator('#oaLauncher').click();
  assert.equal(await page.locator('#oaWidget').count(), 1);
  assert.equal(await page.locator('.oa-retry-btn').count(), 1);
  assert.equal(await page.evaluate(() => window.__pending[0].signal.aborted), true);
  assert.deepEqual(await page.evaluate(() => window.__widgetTest.records().at(-1).request), original);
});
