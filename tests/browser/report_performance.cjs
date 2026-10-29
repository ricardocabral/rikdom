// Exercise financial output from Python through the actual offline controller.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.env.RIKDOM_PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  payload.sections.performance.warnings.push('<img src=x onerror="window.RIKDOM_XSS=true"> audit warning');
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage();
    await page.route('**/*', route => route.abort());
    await page.setContent('<div id="fallback-app"></div>');
    await page.evaluate(data => {window.RIKDOM_REPORT_DATA = data;}, payload);
    await page.addScriptTag({path:'plugins/quarto-portfolio-report/templates/report-runtime.js'});
    await page.evaluate(() => window.RIKDOM_REPORT.mountFallback());
    const section = page.locator('#performance-view');
    assert.match(await section.innerText(), /20\.8%/);
    assert.match(await section.innerText(), /modified_dietz|Modified Dietz/);
    assert.match(await section.innerText(), /XIRR|xirr/);
    assert.match(await section.innerText(), /Annualized|annualized/);
    assert.match(await section.innerText(), /\$26\.00/);
    assert.match(await section.innerText(), /Jan 01, 2026/);
    assert.match(await section.innerText(), /Jan 11, 2026/);
    assert.match(await section.innerText(), /not separately calculated/);
    assert.match(await section.innerText(), /audit warning/);
    assert.equal(await section.locator('img').count(), 0);
    assert.equal(await page.evaluate(() => window.RIKDOM_XSS), undefined);
    await page.locator('#report-language').selectOption('pt');
    assert.match(await section.innerText(), /20,8%/);
    assert.match(await section.innerText(), /anualizad/i);
    await page.locator('#report-start').fill('2026-01-02');
    assert.doesNotMatch(await section.innerText(), /20,8%|26,00/);
    assert.match(await section.innerText(), /indisponíve/i);
    await page.locator('#report-reset').click();
    assert.match(await section.innerText(), /20,8%/);
    await page.locator('#report-scope').selectOption('account_id:a');
    assert.doesNotMatch(await section.innerText(), /20,8%|26,00/);
    assert.match(await section.innerText(), /indisponíve/i);
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
