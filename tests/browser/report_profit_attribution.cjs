// Exercise the shared offline controller with precomputed financial facts.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.env.RIKDOM_PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const browser = await chromium.launch({headless:true});
  try {
    for (const width of [1440, 390]) {
      const context = await browser.newContext({viewport:{width,height:900},serviceWorkers:'block'});
      await context.route('**/*', route => route.abort());
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.setContent('<div id="fallback-app"></div>');
      await page.evaluate(data => {window.RIKDOM_REPORT_DATA = data;}, payload);
      await page.addScriptTag({path:'plugins/quarto-portfolio-report/templates/report-runtime.js'});
      await page.evaluate(() => window.RIKDOM_REPORT.mountFallback());
      assert.match(await page.title(), /rikdom/);
      assert.match(await page.locator('h1').innerText(), /Report/);
      let text = await page.locator('#performance-view').innerText();
      assert.match(text, /21/);
      assert.match(text, /Linked subperiod TWR/g);
      assert.match(text, /Annualized/);
      assert.match(text, /Investment result/);
      assert.match(text, /26/);
      assert.match(text, /<img src=x onerror/);
      assert.equal(await page.locator('#performance-view img').count(), 0);
      await page.locator('#report-start').fill('2026-07-02');
      await page.locator('#report-start').dispatchEvent('change');
      assert.doesNotMatch(await page.locator('#performance-view').innerText(), /Linked subperiod TWR/g);
      await page.locator('#report-reset').click();
      assert.match(await page.locator('#performance-view').innerText(), /Linked subperiod TWR/g);
      await page.locator('#report-language').selectOption('pt');
      text = await page.locator('#performance-view').innerText();
      assert.match(text, /Resultado dos investimentos/);
      assert.match(text, /21/);
      await page.screenshot({path:`/tmp/rikdom-performance-${width}.png`,fullPage:true});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.deepEqual(errors, []);
      await context.close();
    }
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode=1;});
