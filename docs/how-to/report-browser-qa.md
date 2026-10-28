# Check reports offline in a browser

Use only the repository's sample portfolio for screenshots and shared test logs.
Reports, `report-data.js`, and the trust artifacts contain portfolio data. Keep
real portfolios and their output private.

## Generate both report modes

From the repository root, with dependencies installed:

```bash
uv run rikdom viz \
  --portfolio tests/fixtures/portfolio.json \
  --snapshots tests/fixtures/snapshots.jsonl \
  --out /tmp/rikdom-report-qa/full/dashboard.html

RIKDOM_DISABLE_QUARTO=1 uv run rikdom viz \
  --portfolio tests/fixtures/portfolio.json \
  --snapshots tests/fixtures/snapshots.jsonl \
  --out /tmp/rikdom-report-qa/fallback/dashboard.html
```

The full run requires Quarto (`quarto --version`); a rendering failure produces
fallback HTML with the reason displayed on the page. A successful CLI exit by
itself does not establish that Quarto rendered successfully. Check that the full
page displays the charts and does **not** say “Fallback Portfolio Report”.

Copy each **whole output directory** to a different location, then open its
`dashboard.html` directly using a `file://` URL. The bundle includes
`portfolio-report.html`, `report-data.js` (data plus the shared local runtime), `quarto-input.json`, four trust
artifacts, and any Quarto-generated `*_files/` directories. Keep these together;
copying a single HTML page is insufficient. No local web server is required.

## Manual desktop and mobile checks

Disconnect networking or configure the browser to deny remote requests. Use a
fresh browser context so cached remote assets cannot hide dependencies. Repeat
these checks at 1440×900, 390×900, and 320×900, with mobile emulation enabled for
the narrow sizes. Also inspect both light and dark system themes.

| Check | Acceptance criterion |
| --- | --- |
| Identity and loading | The tab has a meaningful title; valuation and data quality are visible. No blank screen, missing stylesheet, or framework error overlay. |
| Offline resources | All scripts/styles load locally after moving the bundle. No remote requests, missing local resources, JavaScript errors, or relevant console warnings. |
| Current and historical values | Sample current valuation is BRL 165,830.00. Four historical snapshots render as a trend; the chart is separate from current holdings valuation. |
| Allocation | Full output shows asset and currency charts with readable labels and legends. No single-letter vertical currency codes at 320px. |
| Navigation | Tab to “Open deep-dive report”, check visible focus, press Enter, and reach `portfolio-report.html`. Tab to “Open dashboard quickview” and return. |
| Trust artifacts | Activate all four JSON/Markdown links. Each opens a local artifact with substantive content; Back returns to the report. |
| Mobile overflow | The page itself does not scroll horizontally. Panels, text, and navigation remain visible. |
| Holdings table | All five holdings columns remain reachable by horizontal scroll. Tab to the named “Top holdings table” region, check visible focus, and use Right/Left arrows to scroll on narrow screens. Check touch/swipe scrolling on a real device when available. |
| Filters and languages | Select English/Português, account/type/currency and inclusive dates. Current values use the chosen scope; dates leave current valuation unchanged. Source rows and planning payment dates narrow honestly. Inverted dates show a validation message and no matching source rows. Language survives sibling navigation. |
| Fallback | Clearly says “Fallback Portfolio Report” and gives the rendering reason. Shows valuation, latest historical total, coverage, exclusions, warnings, and working local links. Charts and the detailed holdings table are intentionally unavailable; filters, locale selection and income/planning tables remain available. |

Both modes have a language selector, a single-dimension scope selector, recorded
start/end date inputs and a reset button. Test scope selection before and after
date selection. Dates narrow source records and historical charts while current
valuation/allocation stay current. For account/type/currency scopes, historical
snapshot attribution and investment performance remain explicitly unavailable.
Test an empty result and inverted dates; neither may display unfiltered income.

Planning output keeps announced income, scenario estimates, reviewed matching
and declared-cost yield in separate tables. Scope/payment-date filters select
asserted planning rows. A yield's original period is preserved; selecting only
part of the period makes the yield unavailable. Test both available and unknown
coverage, plus an explicit reviewed link. No automatic payment inference or
annualization belongs in the browser.

For richer data states, repeat with locally constructed anonymous portfolios:
no holdings, no history, missing FX, excluded holdings, long holding names, and
untrusted text. Unknown coverage and missing evidence must remain explicit.
Never interpret zero findings as complete history.

## Optional automated browser regression

The standard Python suite adds no Playwright runtime dependency. For browser QA,
use an already installed Node.js Playwright module and its installed Chromium.
Set the module name (`playwright`, if resolvable by Node) or its absolute module
path:

```bash
RIKDOM_PLAYWRIGHT_MODULE=/absolute/path/to/node_modules/playwright \
RIKDOM_QA_SCREENSHOTS=/tmp/rikdom-report-qa/screenshots \
uv run python -m unittest tests.test_quarto_report_browser -v
```

The opt-in test renders both modes, moves each bundle after render-workspace
cleanup, opens it using `file://`, and aborts every remote browser request. It
checks desktop/mobile loading, real chart geometry, sample current valuation,
all local trust links, keyboard navigation and table scrolling, visible focus,
page overflow, and console health. A full-render failure fails this opt-in test
instead of silently accepting fallback. Without `RIKDOM_PLAYWRIGHT_MODULE`, the
browser test is explicitly skipped. The ordinary alias tests still exercise real
fallback generation through `viz`, `visualize`, and `render-report`, including
legacy output-directory routing and custom output-file precedence.

The browser check uses Chromium only. Native mobile touch, Safari, Firefox,
screen readers, zoom, and the richer data states above require separate manual
checks; screenshot or DOM assertions do not establish full accessibility.

## English and Portuguese checks

The report has complete English/Portuguese interface labels and explicit
`en-US`/`pt-BR` formatting, independent of the browser's default locale. Select
Português, verify dates, decimal/group separators, percentages, control names,
quality labels, empty states, holdings headings and all planning columns.
Select English and verify the original labels and amounts return. Preserve
source IDs, user holding names, source assumptions and raw diagnostics as text.
Original provider diagnostics are labelled “Raw source text” / “Texto original
da fonte”; translation must not alter their meaning.

The initial language defaults to English. To test a Portuguese default, use a
synthetic canonical extension `extensions.rikdom_report.locale = "pt"`. The
sibling link carries `?lang=pt`, so locale survives navigation without storage.
No new `settings` property or CLI language flag is required.

The automated regression creates anonymous income and planning records, tests
both languages at every viewport in both report modes, and checks a 5% Python
computed yield, unknown coverage, separate scenario estimates, exact payment
links, unavailable partial-period yield, empty scopes, invalid dates and escaped
untrusted assumptions. It preserves checks for real chart geometry, current
valuation, local links, keyboard navigation/scrolling, page overflow, missing
resources and runtime/console errors. Saved screenshots include `-pt.png` views.

An optional screenshot directory is local QA evidence, not a shared artifact
containing real portfolio data. Native date-input chrome can follow the browser
or operating-system locale; report date labels use the selected report locale.
