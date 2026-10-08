/* Real-browser checks for both self-contained widgets. All requests are intercepted. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test, before, after } = require('node:test');
const { chromium } = require(process.env.WIDGET_PLAYWRIGHT_MODULE || 'playwright');

const root = path.resolve(__dirname, '..');
const files = ['index.html', 'snippets/etualy-advisor.liquid'];
const stateKey = 'etualy_chat_state_v1';
const attack = '\"><img src=x onerror="window.__xss=1"><script>window.__xss=2</script>';
let browser;

function source(file) {
  return fs.readFileSync(path.join(root, file), 'utf8');
}

function script(file) {
  const match = source(file).match(/<script>([\s\S]*?)<\/script>/);
  assert.ok(match, `${file}: widget script must exist`);
  return match[1];
}

function instrumentedHtml(file) {
  const original = script(file);
  const hooks = `window.__widgetTest = {
    safeHttpUrl, normalizeProduct, normalizeMessage, renderMarkdownText,
    createProductCard, appendChatRecord, renderOptions, saveChatState,
    restoreChatState, session: () => sessionId,
    records: () => chatMessages
  };`;
  const instrumented = file.endsWith('.liquid')
    ? original.replace(/\}\)\(\);\s*$/, `${hooks}\n})();`)
    : original + '\n' + hooks;
  assert.ok(instrumented.includes(hooks));
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
      return route.fulfill({ status: response.status, contentType: 'application/json',
        headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify(response.body) });
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
  return JSON.stringify({ version: 1, session_id: 'sess_security', messages,
    options, step: 2, last_message: 'iris' });
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

test('Both widgets contain the same safe renderer', () => {
  const block = (file) => script(file).split('// BEGIN WIDGET SAFE RENDERING')[1]
    .split('// END WIDGET SAFE RENDERING')[0].trim();
  assert.equal(block(files[0]), block(files[1]));
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
    assert.equal(await page.locator('#oaMessages .oa-card-title-link').getAttribute('href'), 'https://shop.test/products/iris');
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

  test(`${file}: JSON history and option actions survive page navigation`, async (t) => {
    const { page, requests } = await fixture(t, file);
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
    assert.equal(saved.version, 1);
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
}
