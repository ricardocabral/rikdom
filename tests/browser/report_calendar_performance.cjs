const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.env.RIKDOM_PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const browser = await chromium.launch({headless:true});
  try {
    for (const id of ['rk-app', 'fallback-app']) {
      const page = await browser.newPage({viewport:{width:390,height:900}});
      await page.route('**/*', route => route.abort());
      await page.setContent(`<div id="${id}"></div>`);
      await page.evaluate(data => {window.RIKDOM_REPORT_DATA = data;}, payload);
      await page.addScriptTag({path:'plugins/quarto-portfolio-report/templates/report-runtime.js'});
      await page.evaluate(id => id === 'fallback-app' ? window.RIKDOM_REPORT.mountFallback() : window.RIKDOM_REPORT.mount(() => {}), id);
      const panel = page.locator('#calendar-performance');
      let text = await panel.innerText();
      assert.match(text, /Monthly performance/);
      assert.match(text, /Yearly performance/);
      assert.match(text, /2024-01/);
      assert.match(text, /Complete/);
      assert.match(text, /Partial/);
      assert.match(text, /Unavailable/);
      assert.match(text, /13.25/);
      assert.doesNotMatch(text, /888/);
      assert.match(text, /Modified Dietz/);
      assert.match(text, /Annualized XIRR/);
      assert.equal(await panel.locator('img').count(), 0);
      await page.locator('#report-language').selectOption('pt');
      text = await panel.innerText();
      assert.match(text, /Rentabilidade mensal/);
      assert.match(text, /Rentabilidade anual/);
      assert.match(text, /Parcial/);
      await page.locator('#report-start').fill('2024-01-15');
      await page.locator('#report-start').dispatchEvent('change');
      assert.equal(await panel.count(), 0);
      await page.locator('#report-reset').click();
      assert.equal(await panel.count(), 1);
      await page.locator('#report-scope').selectOption('account_id:a');
      assert.equal(await panel.count(), 0);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode=1;});
