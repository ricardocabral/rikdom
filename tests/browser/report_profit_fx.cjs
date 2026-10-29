const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.env.RIKDOM_PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const browser = await chromium.launch({headless:true});
  try {
    for (const width of [1440, 390]) {
      for (const mode of ['full', 'fallback']) {
        const page = await browser.newPage({viewport:{width,height:900}});
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        await page.route('**/*', route => route.abort());
        await page.setContent(`<div id="${mode === 'full' ? 'rk-app' : 'fallback-app'}"></div>`);
        await page.evaluate(data => {window.RIKDOM_REPORT_DATA = data;}, payload);
        await page.addScriptTag({path:'plugins/quarto-portfolio-report/templates/report-runtime.js'});
        await page.evaluate(mode => mode === 'full' ? window.RIKDOM_REPORT.mount(() => {}) : window.RIKDOM_REPORT.mountFallback(), mode);
        let text = await page.locator('#performance-view').innerText();
        assert.match(text, /Cash currency effect/);
        assert.match(text, /FX conversion result/);
        assert.match(text, /Explained period result/);
        assert.match(text, /Reconciliation difference/);
        let details = await page.locator('#profit-fx-breakdown').innerText();
        for (const label of ['Realized price result', 'Realized currency effect', 'Unrealized price change', 'Unrealized currency change']) assert.ok(details.includes(label));
        assert.match(details, /7[.,]00/);
        assert.match(details, /9[.,]00/);
        await page.locator('#report-language').selectOption('pt');
        text = await page.locator('#performance-view').innerText();
        assert.match(text, /Efeito cambial do caixa/);
        assert.match(text, /Resultado da conversão de moedas/);
        details = await page.locator('#profit-fx-breakdown').innerText();
        assert.match(details, /Resultado realizado de preço/);
        assert.match(details, /Variação cambial não realizada/);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        assert.deepEqual(errors, []);
        await page.evaluate(mode => {
          const data = window.RIKDOM_REPORT_DATA;
          data.sections.performance.profit_attribution.decomposition.status = 'unavailable';
          data.sections.performance.profit_attribution.diagnostics = ['Missing historical FX'];
          document.body.innerHTML = `<div id="${mode === 'full' ? 'rk-app' : 'fallback-app'}"></div>`;
          if (mode === 'full') window.RIKDOM_REPORT.mount(() => {});
          else window.RIKDOM_REPORT.mountFallback();
        }, mode);
        assert.equal(await page.locator('#profit-fx-breakdown').count(), 0);
        assert.match(await page.locator('#performance-view').innerText(), /Missing historical FX/);
        await page.close();
      }
    }
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
