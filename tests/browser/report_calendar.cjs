// Regression checks for source-calendar dates and opaque report identifiers.
const assert = require('node:assert/strict');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.env.RIKDOM_PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const root = path.resolve(process.argv[2]);
  const fallback = process.argv[3] === 'fallback';
  const browser = await chromium.launch({headless:true});
  try {
    for (const timezoneId of ['UTC','America/Sao_Paulo']) {
      const context = await browser.newContext({viewport:{width:390,height:900},timezoneId,locale:'en-US',serviceWorkers:'block'});
      await context.route('**/*', route => /^(file:|data:)/.test(route.request().url()) ? route.continue() : route.abort());
      for (const filename of ['portfolio-report.html','dashboard.html']) {
        const page = await context.newPage();
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        await page.goto(pathToFileURL(path.join(root,filename)).href);
        if (!fallback && filename === 'portfolio-report.html') {
          assert.match(await page.locator('.rk-signed').innerText(), /\+\$200\.00/, 'Displayed historical change follows Python timestamp order');
          const coordinates = (await page.locator('.rk-chart-shell svg path').getAttribute('d')).match(/-?\d+(?:\.\d+)?/g).map(Number);
          assert.ok(coordinates[1] > coordinates.at(-1), 'Reversed input renders a chronological rising chart');
        }
        await page.locator('#report-language').selectOption('pt');
        const text = await page.locator('body').innerText();
        assert.doesNotMatch(text,/ação_options/, 'Opaque custom asset type is never substring-translated');
        if (!fallback && filename === 'portfolio-report.html') {
          assert.equal(await page.locator('.rk-list .name').filter({hasText:/^stock_options$/}).count(),1);
          assert.equal(await page.locator('.rk-list .name').filter({hasText:/^ação$/}).count(),1,'Known stock enum still translates');
        }
        const scope = page.locator('#report-scope option[value="asset_type_id:stock_options"]');
        assert.match(await scope.innerText(),/stock_options$/);
        for (const language of ['en','pt']) {
          await page.locator('#report-language').selectOption(language);
          for (const [day, expected] of [['2026-02-01',200],['2026-02-02',300]]) {
            await page.locator('#report-start').fill(day);
            await page.locator('#report-end').fill(day);
            assert.equal(await page.locator('[data-snapshot-count]').innerText(),'1');
            const history = fallback ? page.locator('#fallback-app h2').filter({hasText:/Historical snapshot|Avaliação histórica/}).locator('xpath=following-sibling::p[1]') : filename === 'dashboard.html' ? page.locator('#historical-context') : page.locator('.rk-footnote').filter({hasText:/Historical snapshot|Avaliação histórica/});
            const label = await history.innerText();
            const expectedDate = new Intl.DateTimeFormat(language === 'pt' ? 'pt-BR' : 'en-US',{year:'numeric',month:'short',day:'2-digit',timeZone:'UTC'}).format(new Date(day+'T12:00:00Z'));
            assert.ok(label.replace(/\b0([1-9])\b/g,'$1').includes(expectedDate.replace(/\b0([1-9])\b/g,'$1')), `${filename} ${timezoneId} ${language}: ${label} must use source day ${expectedDate}`);
            assert.match(label,new RegExp(String(expected)));
            if (!fallback && filename === 'portfolio-report.html' && day === '2026-02-02') assert.match(label,/00:15:00\+03:00/,'Source time and explicit offset are preserved');
          }
          await page.locator('#report-reset').click();
        }
        assert.deepEqual(errors,[]);
        await page.close();
      }
      await context.close();
    }
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
