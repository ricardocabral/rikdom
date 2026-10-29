// Exercise the shipped offline controller with real calculator output.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.env.RIKDOM_PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const planning = payload.sections.income.planning;
  // Copy editing the audit message must not change the localized decision.
  planning.yield_on_cost[0].reason = 'Editorially revised audit message!';
  for (const code of ['future_reason', 'toString', '__proto__', null]) {
    const row = {...planning.yield_on_cost[0], id:`unknown-${code}`,
      reason:`<img src=x onerror="window.RIKDOM_XSS=true"> ${code} original`};
    if (code === null) delete row.reason_code;
    else row.reason_code = code;
    planning.yield_on_cost.push(row);
  }
  const browser = await chromium.launch({headless:true});
  try {
    const context = await browser.newContext({serviceWorkers:'block'});
    await context.route('**/*', route => route.abort());
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setContent('<div id="fallback-app"></div>');
    await page.evaluate(data => {window.RIKDOM_REPORT_DATA = data;}, payload);
    await page.addScriptTag({path:'plugins/quarto-portfolio-report/templates/report-runtime.js'});
    await page.evaluate(() => window.RIKDOM_REPORT.mountFallback());
    await page.locator('#report-language').selectOption('pt');
    let text = await page.locator('#planning-view').innerText();
    assert.match(text, /A cobertura dos rendimentos não está completa/);
    assert.doesNotMatch(text, /Editorially revised/);
    for (const code of ['future_reason', 'toString', '__proto__', null]) {
      assert.ok(text.includes(`Texto original da fonte: <img src=x onerror="window.RIKDOM_XSS=true"> ${code} original`));
    }
    assert.equal(await page.locator('img').count(), 0);
    assert.equal(await page.evaluate(() => window.RIKDOM_XSS), undefined);
    await page.locator('#report-language').selectOption('en');
    assert.match(await page.locator('#planning-view').innerText(), /Editorially revised audit message!/);
    // A linked payment precedes its announcement; the browser cannot recompute it.
    await page.locator('#report-language').selectOption('pt');
    await page.locator('#report-start').fill('2026-02-02');
    text = await page.locator('#planning-view').innerText();
    assert.match(text, /As datas selecionadas excluem pagamentos recebidos vinculados/);
    assert.match(text, /As datas selecionadas não abrangem todo o período do custo declarado/);
    await page.locator('#report-reset').click();
    assert.match(await page.locator('#planning-view').innerText(), /A cobertura dos rendimentos não está completa/);
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
