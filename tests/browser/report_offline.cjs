// Optional real-browser checks; see docs/how-to/report-browser-qa.md.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {fileURLToPath, pathToFileURL} = require('node:url');
const {chromium} = require(process.env.RIKDOM_PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const root = path.resolve(process.argv[2]);
  const fallback = process.argv[3] === 'fallback';
  const browser = await chromium.launch({headless: true});
  const failures = [];
  try {
    for (const width of [1440, 390, 320]) {
      for (const filename of ['dashboard.html', 'portfolio-report.html']) {
        const context = await browser.newContext({viewport: {width, height: 900}, isMobile: width < 500, hasTouch: width < 500, locale: 'en-US', serviceWorkers: 'block'});
        const page = await context.newPage();
        const errors = [];
        const remote = [];
        const missing = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('console', message => {
          if (['error', 'warning'].includes(message.type())) errors.push(message.text());
        });
        await context.route('**/*', route => {
          const url = route.request().url();
          if (url.startsWith('file:')) {
            const file = fileURLToPath(url.split('#')[0].split('?')[0]);
            if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) missing.push(url);
            return route.continue();
          }
          if (url.startsWith('data:')) return route.continue();
          remote.push(url);
          return route.abort();
        });
        const check = (name, fn) => {
          try { fn(); } catch (error) { failures.push(`${filename} ${width}px ${name}: ${error.message}`); }
        };
        await page.goto(pathToFileURL(path.join(root, filename)).href);
        check('identity', () => assert.equal(path.basename(fileURLToPath(page.url())), filename));
        const title = await page.title();
        check('meaningful title', () => assert.match(title, /rikdom|Portfolio Report/));
        const text = await page.locator('body').innerText();
        check('nonblank content', () => assert.match(text, /Current valuation/i));
        check('quality', () => assert.match(text, /Data quality/i));
        check('no overlay', () => assert.doesNotMatch(text, /Internal Server Error|Build failed|Unhandled Runtime Error/));
        check('fallback status', () => assert.equal(text.includes('Fallback Portfolio Report'), fallback));
        const viewport = await page.evaluate(() => ({width: innerWidth, scroll: document.documentElement.scrollWidth}));
        check('viewport and page overflow', () => assert.ok(viewport.width === width && viewport.scroll <= width + 1, JSON.stringify(viewport)));
        if (!fallback) {
          const current = filename === 'dashboard.html' ? page.locator('#total') : page.locator('.rk-hero-value');
          const amount = await current.innerText();
          check('current valuation', () => assert.equal(amount, 'R$165,830.00'));
          const chart = filename === 'dashboard.html' ? page.locator('#line path') : page.locator('.rk-chart-shell svg path');
          const pathCount = await chart.count();
          check('historical chart path', () => assert.ok(pathCount > 0));
          if (pathCount) {
            const geometry = await chart.first().evaluate(element => ({
              length: element.getTotalLength(), path: element.getAttribute('d'),
            }));
            check('historical chart geometry', () => assert.ok(geometry.length > 0 && !/NaN|Infinity/.test(geometry.path)));
          }
          const allocations = filename === 'dashboard.html' ? page.locator('#asset-donut circle') : page.locator('.rk-donut');
          const allocationCount = await allocations.count();
          check('allocation chart', () => assert.equal(allocationCount, filename === 'dashboard.html' ? 7 : 3));
          if (filename === 'dashboard.html') {
            const codesStayTogether = await page.locator('#currency-legend .legend-label').evaluateAll(labels => labels.every(label => {
              const range = document.createRange();
              range.setStart(label.firstChild, 0);
              range.setEnd(label.firstChild, 3);
              return range.getClientRects().length === 1;
            }));
            check('currency codes remain readable', () => assert.ok(codesStayTogether));
          }
          if (filename === 'portfolio-report.html') {
            const table = page.getByRole('region', {name: 'Top holdings table'});
            const tableCount = await table.count();
            check('holdings accessible scroll region', () => assert.equal(tableCount, 1));
            if (tableCount) {
              await table.focus();
              const focused = await table.evaluate(element => document.activeElement === element);
              check('holdings focus', () => assert.ok(focused));
              const outline = await table.evaluate(element => getComputedStyle(element).outlineStyle);
              check('holdings visible focus', () => assert.notEqual(outline, 'none'));
              const scroll = await table.evaluate(element => ({
                width: element.clientWidth, content: element.scrollWidth,
                overflow: getComputedStyle(element).overflowX,
              }));
              if (scroll.content > scroll.width) {
                check('holdings scroll enabled', () => assert.match(scroll.overflow, /auto|scroll/));
                await page.keyboard.press('ArrowRight');
                await page.waitForTimeout(200);
                const left = await table.evaluate(element => element.scrollLeft);
                check('keyboard scroll reveals clipped columns', () => assert.ok(left > 0));
                await table.evaluate(element => element.scrollLeft = element.scrollWidth);
                const last = await page.locator('.rk-holdings th').last().boundingBox();
                const bounds = await table.boundingBox();
                check('last column reachable', () => assert.ok(last.x + last.width <= bounds.x + bounds.width + 1));
              }
              await page.reload();
            }
          }
        }
        // Alongside table scrolling, the report controls are local navigation and trust links.
        const target = filename === 'dashboard.html' ? 'portfolio-report.html' : 'dashboard.html';
        const nav = page.locator(`a[href="${target}"]`);
        const navCount = await nav.count();
        check('sibling navigation', () => assert.equal(navCount, 1));
        if (navCount) {
          // Reach the navigation through actual keyboard traversal, then activate it.
          await page.evaluate(() => document.activeElement.blur());
          let reached = false;
          for (let i = 0; i < 15; i++) {
            await page.keyboard.press('Tab');
            reached = await nav.evaluate(element => element === document.activeElement);
            if (reached) break;
          }
          check('keyboard reaches navigation', () => assert.ok(reached));
          if (reached) {
            const focus = await nav.evaluate(element => getComputedStyle(element).outlineStyle);
            check('visible focus', () => assert.notEqual(focus, 'none'));
            await page.keyboard.press('Enter');
            await page.waitForURL(`**/${target}`);
            check('keyboard navigation result', () => assert.ok(page.url().endsWith(target)));
            await page.goBack();
          }
        }
        for (const name of ['holding_trust.json', 'reconciliation.json', 'holding_trust.md', 'reconciliation.md']) {
          const link = page.locator(`a[href="${name}"]`);
          const count = await link.count();
          check('local artifact link ' + name, () => assert.equal(count, 1));
          if (count) {
            await link.click();
            await page.waitForURL(`**/${name}`);
            const artifact = await page.locator('body').innerText();
            check('artifact loads ' + name, () => assert.ok(artifact.length > 20));
            await page.goBack();
          }
        }
        if (process.env.RIKDOM_QA_SCREENSHOTS) {
          fs.mkdirSync(process.env.RIKDOM_QA_SCREENSHOTS, {recursive: true});
          await page.screenshot({path: path.join(process.env.RIKDOM_QA_SCREENSHOTS, `${fallback ? 'fallback' : 'quarto'}-${filename}-${width}.png`), fullPage: true});
        }
        check('remote requests', () => assert.deepEqual(remote, []));
        check('missing local assets', () => assert.deepEqual(missing, []));
        check('console and runtime', () => assert.deepEqual(errors, []));
        console.log(`${fallback ? 'fallback' : 'quarto'} ${filename} ${width}px checked`);
        await context.close();
      }
    }
  } finally { await browser.close(); }
  assert.equal(failures.length, 0, failures.join('\n'));
})().catch(error => {console.error(error); process.exitCode = 1;});
