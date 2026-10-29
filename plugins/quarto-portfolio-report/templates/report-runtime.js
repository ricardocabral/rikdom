/* One offline controller owns locale, filter applicability and income provenance
 * for full and fallback pages. Financial facts arrive from Python; this module
 * only selects recorded rows, formats them and draws existing charts. */
(() => {
  'use strict';
  const payload = window.RIKDOM_REPORT_DATA || {};
  const escapeHtml = value => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  const copy = {
    'Language':'Idioma', 'Scope':'Escopo', 'All portfolio':'Carteira completa', 'Account':'Conta', 'Asset type':'Tipo de ativo', 'Currency':'Moeda',
    'Recorded dates from':'Registros a partir de', 'Recorded dates through':'Registros até', 'Reset filters':'Limpar filtros',
    'Current valuation':'Avaliação atual', 'Current holdings with the supplied FX context':'Posições atuais com o contexto cambial fornecido',
    'Historical snapshots':'Histórico de avaliações', 'Historical snapshot':'Avaliação histórica', 'none available':'nenhuma disponível',
    'Current allocation by asset class':'Alocação atual por classe de ativo', 'Market value by currency (converted to':'Valor por moeda (convertido para',
    'Open deep-dive report':'Abrir relatório detalhado', 'Open dashboard quickview':'Abrir painel resumido',
    'Data quality':'Qualidade dos dados', 'History coverage':'Cobertura histórica', 'Zero findings do not prove complete history.':'Nenhuma ocorrência não comprova um histórico completo.',
    'Quantity':'Quantidade', 'not computable':'não calculável', 'mismatched':'divergentes', 'matched':'conferentes', 'Unsupported events':'Eventos sem suporte',
    'Excluded holdings':'Posições excluídas', 'more warnings in the trust artifacts.':'avisos adicionais nos arquivos de verificação.',
    'No snapshots yet':'Nenhuma avaliação registrada', 'No data available.':'Nenhum dado disponível.', 'No data':'Sem dados', 'Asset class':'Classe de ativo', 'Currency FX':'Câmbio',
    'Missing FX rates for':'Taxas de câmbio ausentes para', 'Static portfolio report':'Relatório estático da carteira', 'Country':'País',
    'Current holdings; report generated':'Posições atuais; relatório gerado em', 'FX dates are recorded in the trust artifacts.':'As datas de câmbio constam nos arquivos de verificação.',
    'change across historical snapshots':'variação entre avaliações históricas', 'Latest interval':'Último intervalo', 'Period min / max':'Mínimo / máximo do período',
    'Largest currency share':'Maior participação por moeda', 'Coverage':'Cobertura', 'Snapshots':'Avaliações', 'Updated':'Atualizado',
    'Top holding concentration':'Concentração na maior posição', 'Largest included holding relative to current valuation.':'Maior posição incluída em relação à avaliação atual.',
    'Currencies tracked':'Moedas registradas', 'From current holdings market values.':'Valores de mercado das posições atuais.',
    'Asset buckets':'Grupos de ativos', 'Debt classes are grouped into debt_instrument.':'Classes de dívida agrupadas em instrumentos de dívida.',
    'Top holdings listed':'Principais posições listadas', 'Limited to report payload top list.':'Limitado às principais posições do relatório.',
    'Current currency allocation':'Alocação atual por moeda', 'Asset type breakdown':'Distribuição por tipo de ativo', 'Geography':'Distribuição geográfica',
    'Breakdown':'Distribuição', 'Top holdings':'Principais posições', 'Holdings':'Posições', 'Holding':'Posição', 'Source amount':'Valor na origem',
    'Current base amount':'Valor atual na moeda base', 'Current share':'Participação atual', 'Relative Size':'Tamanho relativo', 'Excluded:':'Excluído:',
    'Scroll the table horizontally to see all columns; use arrow keys when the table is focused.':'Role a tabela horizontalmente para ver todas as colunas; use as setas com o foco na tabela.',
    'Holdings use the amounts provided in the current payload. When holdings contain multiple currencies,':'As posições usam os valores fornecidos no relatório atual. Nas carteiras com várias moedas,',
    'each row preserves its own currency code.':'cada linha preserva seu código de moeda.',
    'No timeline snapshots available.':'Nenhuma avaliação histórica disponível.', 'No holdings available.':'Nenhuma posição disponível.',
    'Top holdings table':'Tabela das principais posições', 'Portfolio evolution chart':'Gráfico de evolução da carteira',
    'Holding trust':'Verificação de posições', 'Reconciliation':'Conciliação', 'Fallback Portfolio Report':'Relatório simplificado da carteira',
    'Fallback mode; charts and detailed holdings table are unavailable.':'Modo simplificado; gráficos e tabela detalhada de posições indisponíveis.',
    'Raw source text':'Texto original da fonte', 'unknown':'desconhecido', 'none':'nenhum', 'as of':'em', ' on ':' em ',
    'stocks':'ações', 'reits':'fundos imobiliários', 'funds':'fundos', 'cash_equivalents':'equivalentes de caixa', 'cryptocurrencies':'criptomoedas',
    'n/a':'indisponível', 'declared':'declarada', 'complete':'completo', 'partial':'parcial', 'debt_instrument':'instrumentos de dívida', 'stock':'ação', 'fund':'fundo', 'cash_equivalent':'equivalente de caixa', 'cryptocurrency':'criptomoeda', 'debt':'dívida',
  };
  const labels = {
    en: {
      dates: 'Dates narrow recorded snapshots, contributions and income records only. Current valuation and allocation always describe current holdings.',
      scoped: 'Historical breakdown and performance unavailable for this scope: snapshots lack asserted attribution. Unattributed income is excluded from dimension scopes.',
      artifacts: 'Trust artifact links retain the full portfolio context.',
      all: 'Recorded historical portfolio facts; valuation changes are not investment returns. Snapshot dates use the source calendar day and explicit offset, independent of browser timezone.',
      invalid: 'Start date must be on or before end date.',
      income: 'Received income', contributions: 'Recorded contributions and withdrawals', performance: 'Investment performance',
      unavailable: 'Unavailable: no attributable recorded return measure is supplied. Snapshot changes must not be interpreted as investment returns.',
      scroll: 'Scroll horizontally; focus the table and use the arrow keys to reach all columns.',
      noRows: 'No records in the selected scope and dates. Missing history does not establish zero income or zero contributions.',
      date: 'Date', source: 'Source ID', kind: 'Type', gross: 'Gross', withholding: 'Withholding', fees: 'Fees', net: 'Net', amount: 'Recorded amount',
      unknown: 'Unavailable', native: 'Native currencies; no FX conversion. Missing withholding and fees remain unknown. Only asserted event dimensions are filtered.',
      original: 'Raw source text', noPlan: 'No income plan supplied. Announcements, estimates, matching and yield on cost are unavailable.',
      announced: 'Announced income', estimates: 'Scenario estimates', reconciliation: 'Explicit payment matching', yield_on_cost: 'Yield on declared cost basis',
      estimateNote: 'Scenario estimates are separate from announced and received income.', planDates: 'Planning rows retain their declared dates and periods. Date filters select payment dates; yield is unavailable when the declared period is not fully included. No automatic annualization.',
    },
    pt: {
      dates: 'As datas limitam apenas avaliações históricas, aportes e registros de rendimentos. A avaliação e a alocação atuais sempre descrevem as posições atuais.',
      scoped: 'Distribuição histórica e rentabilidade indisponíveis neste escopo: as avaliações não têm atribuição declarada. Rendimentos sem atribuição ficam fora dos escopos por dimensão.',
      artifacts: 'Os arquivos de verificação mantêm o contexto da carteira completa.',
      all: 'Fatos históricos registrados da carteira; variações de avaliação não são rentabilidade. As datas de avaliação usam o dia e o fuso declarados na origem, independentemente do fuso do navegador.',
      invalid: 'A data inicial deve ser anterior ou igual à data final.',
      income: 'Rendimentos recebidos', contributions: 'Aportes e retiradas registrados', performance: 'Rentabilidade dos investimentos',
      unavailable: 'Indisponível: nenhuma medida de rentabilidade registrada e atribuível foi fornecida. Variações de avaliação não devem ser interpretadas como rentabilidade.',
      scroll: 'Role horizontalmente; coloque o foco na tabela e use as setas para acessar todas as colunas.',
      noRows: 'Nenhum registro no escopo e nas datas selecionados. Histórico ausente não comprova rendimentos ou aportes iguais a zero.',
      date: 'Data', source: 'ID na origem', kind: 'Tipo', gross: 'Bruto', withholding: 'Retenção', fees: 'Taxas', net: 'Líquido', amount: 'Valor registrado',
      unknown: 'Indisponível', native: 'Moedas de origem; sem conversão cambial. Retenções e taxas ausentes permanecem desconhecidas. Apenas dimensões declaradas nos eventos são filtradas.',
      original: 'Texto original da fonte', noPlan: 'Nenhum plano de rendimentos fornecido. Anúncios, estimativas, conciliação e rendimento sobre custo estão indisponíveis.',
      announced: 'Rendimentos anunciados', estimates: 'Estimativas de cenário', reconciliation: 'Conciliação explícita de pagamentos', yield_on_cost: 'Rendimento sobre o custo declarado',
      estimateNote: 'Estimativas de cenário são separadas dos rendimentos anunciados e recebidos.', planDates: 'O plano preserva suas datas e períodos declarados. Os filtros selecionam datas de pagamento; o rendimento fica indisponível se o período declarado não estiver incluído por inteiro. Sem anualização automática.',
    }
  };
  let language = new URLSearchParams(window.location.search).get('lang') || payload.profile?.language || 'en';
  language = language.toLowerCase().startsWith('pt') ? 'pt' : 'en';
  let scope = 'all', start = '', end = '';
  const locale = () => language === 'pt' ? 'pt-BR' : 'en-US';
  const money = (amount, currency) => typeof amount === 'number' && Number.isFinite(amount)
    ? new Intl.NumberFormat(locale(), {style: 'currency', currency: /^[A-Z]{3}$/.test(currency) ? currency : 'USD', maximumFractionDigits: 2}).format(amount)
    : labels[language].unknown;
  const date = value => {
    if (!value) return labels[language].unknown;
    const parsed = new Date(String(value).slice(0, 10) + 'T12:00:00Z');
    return Number.isNaN(parsed.getTime()) ? String(value) : new Intl.DateTimeFormat(locale(), {year: 'numeric', month: 'short', day: '2-digit', timeZone: 'UTC'}).format(parsed);
  };
  const sourceDateTime = value => {
    if (!value) return labels[language].unknown;
    // Preserve the source wall clock and offset; Intl only formats its calendar
    // day. Converting the instant to UTC/browser time would change date meaning.
    return `${date(value)} ${String(value).slice(11)}`.trim();
  };
  const t = text => language === 'pt' && Object.prototype.hasOwnProperty.call(copy, text) ? copy[text] : text;
  function translate(root) {
    if (language !== 'pt') return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const ordered = Object.keys(copy).sort((a, b) => b.length - a.length);
    let node;
    // Replace in one pass so dictionary entries never translate another entry's
    // Portuguese output. Source/provider text is explicitly excluded.
    const pattern = new RegExp(ordered.map(key => key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'g');
    while ((node = walker.nextNode())) {
      if (node.parentElement.closest('[data-source-text],script,style')) continue;
      node.textContent = node.parentElement.closest('[data-report-enum]')
        ? t(node.textContent) : node.textContent.replace(pattern, match => copy[match]);
    }
    root.querySelectorAll('[aria-label]').forEach(node => node.setAttribute('aria-label', t(node.getAttribute('aria-label'))));
  }
  function table(headings, rows, caption) {
    if (!rows.length) return `<p>${escapeHtml(labels[language].noRows)}</p>`;
    return `<p>${escapeHtml(labels[language].scroll)}</p><div class="report-table" tabindex="0" role="region" aria-label="${escapeHtml(caption || headings[0])}"><table><thead><tr>${headings.map(h => `<th>${escapeHtml(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(cell => `<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }
  function supplementary(sections) {
    const l = labels[language];
    const income = sections.income || {};
    const events = income.events || [];
    const kinds = {dividend: language === 'pt' ? 'Dividendo' : 'Dividend', interest: language === 'pt' ? 'Juros' : 'Interest', contribution: language === 'pt' ? 'Aporte' : 'Contribution', deposit: language === 'pt' ? 'Depósito' : 'Deposit', withdrawal: language === 'pt' ? 'Retirada' : 'Withdrawal'};
    const eventRows = events.map(row => [escapeHtml(date(row.date)), escapeHtml(row.activity_id), escapeHtml(kinds[row.event_type] || row.event_type), ...['gross', 'withholding', 'fees', 'net'].map(key => escapeHtml(money(row[key], row.currency)))]);
    const contributions = (sections.contributions || []).map(row => [escapeHtml(date(row.date)), escapeHtml(row.activity_id), escapeHtml(kinds[row.event_type] || row.event_type), escapeHtml(money(row.amount, row.currency))]);
    const diagnostics = [...(income.diagnostics || []), ...(income.planning?.diagnostics || [])];
    const planning = income.planning;
    let plan = `<p>${escapeHtml(l.noPlan)}</p>`;
    if (planning) {
      plan = `<p>${escapeHtml(l.planDates)}</p>` + ['announced', 'estimates', 'reconciliation', 'yield_on_cost'].map(key => `<section><h3>${escapeHtml(l[key])}</h3>${key === 'estimates' ? `<p>${escapeHtml(l.estimateNote)}</p>` : ''}${planningRows(key, planning[key] || [])}</section>`).join('');
    }
    return `<section class="report-panel" id="income-view"><h2>${escapeHtml(l.income)}</h2><p>${escapeHtml(l.native)}</p>${table([l.date, l.source, l.kind, l.gross, l.withholding, l.fees, l.net], eventRows, l.income)}</section>
      <section class="report-panel" id="contributions-view"><h2>${escapeHtml(l.contributions)}</h2>${table([l.date, l.source, l.kind, l.amount], contributions, l.contributions)}</section>
      <section class="report-panel" id="performance-view"><h2>${escapeHtml(l.performance)}</h2>${performancePanel(sections.performance)}</section>
      <section class="report-panel" id="planning-view">${plan}</section>
      ${diagnostics.length ? `<details class="report-panel"><summary>${escapeHtml(l.original)}</summary><ul data-source-text>${diagnostics.map(row => `<li>${escapeHtml(row.activity_id || row.id || '')}: ${escapeHtml(row.message || JSON.stringify(row))}</li>`).join('')}</ul></details>` : ''}`;
  }
  function performancePanel(performance) {
    const l = labels[language], pt = language === 'pt';
    const label = (en, br) => pt ? br : en;
    if (!performance) return `<p>${escapeHtml(l.unavailable)}</p>`;
    const p = performance, ccy = p.base_currency;
    const percentage = value => typeof value === 'number' && Number.isFinite(value)
      ? new Intl.NumberFormat(locale(), {maximumFractionDigits:4}).format(value) + '%' : l.unknown;
    const rows = [
      [label('Selected TWR', 'TWR selecionado'), percentage(p.twr_return_pct), p.twr_method, p.twr_return_basis],
      [label('MWR (XIRR)', 'MWR (XIRR)'), percentage(p.mwr_pct), 'xirr', p.mwr_return_basis],
      [label('Opening value', 'Valor inicial'), money(p.start_value_base, ccy), '', ''],
      [label('Net external contributions', 'Aportes externos líquidos'), money(p.net_external_cashflow_base, ccy), '', ''],
      [label('Closing value', 'Valor final'), money(p.end_value_base, ccy), '', ''],
    ];
    const a = p.profit_attribution, bridge = a?.bridge, d = a?.decomposition;
    if (bridge) rows.push([label('Investment result', 'Resultado dos investimentos'), money(bridge.investment_result_base, ccy), bridge.status, label('Residual from supplied bookends and external flows', 'Resíduo das avaliações e dos fluxos externos fornecidos')]);
    if (d) {
      for (const [key, en, br] of [
        ['realized_gain_base', 'Realized gain', 'Ganho realizado'],
        ['unrealized_change_base', 'Unrealized gain change', 'Variação do ganho não realizado'],
        ['net_income_base', 'Net income', 'Rendimentos líquidos'],
        ['standalone_fees_base', 'Separate fees', 'Taxas separadas'],
        ['standalone_taxes_base', 'Separate taxes', 'Impostos separados'],
      ]) rows.push([label(en, br), money(d[key], ccy), d.method, d.status]);
    }
    let html = `<p>${escapeHtml(sourceDateTime(p.period_start))} – ${escapeHtml(sourceDateTime(p.period_end))}</p>`;
    html += table([label('Metric', 'Medida'), label('Value', 'Valor'), label('Method / status', 'Método / situação'), label('Convention', 'Convenção')], rows.map(row => row.map(escapeHtml)), l.performance);
    if (p.benchmarks?.length) html += table([label('Benchmark', 'Referência'), label('Return', 'Retorno'), label('Excess', 'Excesso'), label('Comparability', 'Comparabilidade')], p.benchmarks.map(b => [escapeHtml(b.label || b.benchmark_id), escapeHtml(percentage(b.twr_pct)), escapeHtml(percentage(b.excess_pct)), escapeHtml(b.comparison_status || 'legacy')]), label('Benchmarks', 'Referências'));
    const notes = [...Object.values(p.treatment || {}), ...(p.warnings || []), ...(a?.diagnostics || [])];
    if (p.twr_fallback_reason) notes.push(p.twr_fallback_reason);
    if (notes.length) html += `<details open><summary>${escapeHtml(l.original)}</summary><ul data-source-text>${notes.map(note => `<li>${escapeHtml(typeof note === 'string' ? note : JSON.stringify(note))}</li>`).join('')}</ul></details>`;
    return html;
  }
  function planningRows(key, rows) {
    const pt = language === 'pt', l = labels[language];
    const column = (en, br) => pt ? br : en;
    const enums = {gross:column('Gross','Bruto'),net:column('Net','Líquido'),unknown:l.unknown,available:column('Available','Disponível'),unavailable:l.unknown,complete:column('Complete','Completa'),
      announced:column('Announced','Anunciado'),cancelled:column('Cancelled','Cancelado'),matched:column('Matched','Conciliado'),partial:column('Partial','Parcial'),overpaid:column('Above announced','Acima do anunciado'),unlinked:column('Unlinked; coverage unknown','Sem vínculo; cobertura desconhecida'),
      dividend:column('Dividend','Dividendo'),interest:column('Interest','Juros'),total:column('Total','Total'),per_unit:column('Per unit','Por unidade'),manual:column('Manual','Manual'),file:column('File','Arquivo'),provider:column('Provider','Provedor'),declared_constant_cost:column('Declared constant cost','Custo constante declarado')};
    const reasonTranslations = {
      linked_payments_not_selected:'As datas selecionadas excluem pagamentos recebidos vinculados; os valores conciliados ficam indisponíveis sem recalcular o resumo original.',
      additional_payments_outside_period:'Há pagamentos revisados adicionais fora do período selecionado; esta comparação inclui apenas os pagamentos recebidos selecionados.',
      cost_basis_unavailable:'O custo declarado está indisponível.',
      income_coverage_incomplete:'A cobertura dos rendimentos não está completa para o escopo, a fonte e o período declarados.',
      requested_amount_basis_unknown:'A base dos rendimentos solicitada é desconhecida.',
      income_source_unknown:'O sistema de origem dos rendimentos é desconhecido.',
      scope_source_incompatible:'A fonte do escopo declarado e o sistema de origem dos rendimentos são incompatíveis.',
      cost_period_not_fully_selected:'As datas selecionadas não abrangem todo o período do custo declarado; nenhum rendimento de período parcial foi substituído.',
      income_unclassified:'Rendimentos sem classificação impedem um numerador completo de rendimentos recebidos.',
      cost_activity_in_period:'O custo constante não é sustentado, pois há um evento que afeta o custo no período declarado.',
      cost_activity_scope_unknown:'Um evento que afeta o custo tem escopo histórico desconhecido; o custo constante está indisponível.',
      received_scope_unknown:'A atribuição histórica do escopo dos rendimentos recebidos é desconhecida.',
      received_source_incompatible:'A fonte dos rendimentos recebidos é desconhecida ou incompatível com a fonte declarada.',
      received_currency_incompatible:'A moeda dos rendimentos recebidos difere da moeda do custo declarado; sem substituição cambial.',
      received_amount_basis_unavailable:'A base dos rendimentos recebidos está indisponível.',
      announcement_cancelled:'A revisão mais recente do anúncio foi cancelada; nenhum direito foi calculado.',
      announced_amount_basis_unknown:'A base dos rendimentos anunciados é desconhecida.',
      entitlement_quantity_missing:'O anúncio por unidade não tem quantidade histórica de direito declarada; as posições atuais não são usadas.',
      payment_outside_period:'Há pagamento revisado fora do período selecionado; nenhum pagamento recebido é contado neste intervalo.',
      payment_link_missing:'Nenhum vínculo revisado de pagamento recebido neste período; a cobertura é desconhecida e não comprova atraso ou ausência de pagamento.',
    };
    const text = value => escapeHtml(value ?? l.unknown);
    const status = value => text(enums[value] || value || l.unknown);
    const scopeLabel = row => Object.entries(row.scope || {}).map(([name,value]) => `${column({account_id:'Account',asset_type_id:'Asset type',holding_id:'Holding',source_system:'Source system',instrument:'Instrument'}[name] || name,{account_id:'Conta',asset_type_id:'Tipo de ativo',holding_id:'Posição',source_system:'Sistema de origem',instrument:'Instrumento'}[name] || name)}: ${typeof value === 'object' ? JSON.stringify(value) : value}`).join('; ');
    const source = row => row.source ? `${status(row.source.kind)} · ${text(row.source.reference)} · ${text(date(row.source.as_of))}` : l.unknown;
    const reason = row => !row.reason ? '—' : pt && Object.hasOwn(reasonTranslations, row.reason_code) ? text(reasonTranslations[row.reason_code]) : `<span data-source-text>${pt ? text(l.original) + ': ' : ''}${text(row.reason)}</span>`;
    const basis = column('Amount basis','Base do valor'), provenance = column('Source and date','Fonte e data'), details = column('Scope / details','Escopo / detalhes'), state = column('Status / reason','Situação / motivo');
    if (key === 'yield_on_cost') return table([l.source,details,column('Declared period','Período declarado'),column('Method / source','Método / fonte'),basis,column('Cost basis','Custo declarado'),l.income,column('Yield (not annualized)','Rendimento (sem anualização)'),state], rows.map(row => [text(row.id),text(scopeLabel(row)),`${text(date(row.period?.start))} – ${text(date(row.period?.end))}`,`${status(row.method)}<br>${source(row)}<br>${column('Income source system','Sistema de origem dos rendimentos')}: ${text(row.income_source_system)}<br>${column('Coverage','Cobertura')}: ${status(row.coverage)}`,status(row.amount_basis),text(money(row.cost_basis,row.currency)),`${text(money(row.received_amount,row.currency))}<br>${text((row.activity_ids || []).join(', '))}`,typeof row.ratio === 'number' ? text(new Intl.NumberFormat(locale(),{style:'percent',maximumFractionDigits:2}).format(row.ratio)) : text(l.unknown),`${status(row.status)}<br>${reason(row)}`]));
    if (key === 'reconciliation') return table([l.source,l.date,details,basis,column('Announced','Anunciado'),l.income,column('Known subtotal / linked IDs','Subtotal conhecido / IDs vinculados'),state],rows.map(row => [text(row.announcement_id),text(date(row.payment_date)),text(scopeLabel(row)),status(row.amount_basis),text(money(row.expected_amount,row.currency)),text(money(row.received_amount,row.currency)),`${text(money(row.known_received_subtotal,row.currency))}<br>${text((row.activity_ids || []).join(', '))}`,`${status(row.status)}<br>${reason(row)}`]));
    return table([l.source,l.date,details,basis,column('Amount','Valor'),provenance,state], rows.map(row => [text(row.id),`${text(date(row.payment_date))}<br>${row.ex_date ? column('Ex-date','Data ex') + ': ' + text(date(row.ex_date)) + '<br>' : ''}${row.record_date ? column('Record date','Data de registro') + ': ' + text(date(row.record_date)) : ''}`,`${text(scopeLabel(row))}<br>${status(row.income_type)}<br>${key === 'estimates' ? text(row.scenario) + '<br>' + text(row.assumptions) : status(row.amount_kind) + (row.entitlement_quantity == null ? '' : '<br>' + text(new Intl.NumberFormat(locale()).format(row.entitlement_quantity)) + '<br>' + source({source:row.entitlement_source}))}`,status(row.amount_basis),text(money(key === 'estimates' ? row.estimated_amount : row.expected_amount,row.currency)),source(row),`${key === 'estimates' ? text(l.estimateNote) : status(row.status) + '<br>' + column('Revision','Revisão') + ' ' + text(row.revision)}<br>${reason(row)}`]));
  }
  const style = document.createElement('style');
  style.textContent = `.report-controls,.report-extra{max-width:1400px;margin:1rem auto;padding:0 24px;box-sizing:border-box;min-width:0}.report-controls{display:flex;flex-wrap:wrap;gap:12px;align-items:end}.report-controls label{display:flex;flex-direction:column;gap:5px;font-size:14px;min-width:0;max-width:100%}.report-controls select,.report-controls input,.report-controls button{box-sizing:border-box;max-width:100%;min-height:42px;background:var(--rk-surface,var(--linen,#E9E2D4));color:var(--rk-text,var(--ink,#1F1A14));border:1px solid currentColor;border-radius:4px;padding:8px;font:inherit}.report-controls select{max-width:min(100%,25rem)}.report-panel{background:var(--rk-surface,var(--linen,#E9E2D4));color:var(--rk-text,var(--ink,#1F1A14));padding:24px;margin:16px 0;border:1px solid var(--rk-border,var(--stone,#B8AE9E));border-radius:4px;overflow-wrap:anywhere;min-width:0}.report-panel h2{margin-top:0}.report-table{max-width:100%;overflow-x:auto}.report-table table{border-collapse:collapse;min-width:640px;width:100%;font-variant-numeric:tabular-nums}.report-table th,.report-table td{padding:10px;min-width:8rem;text-align:left;border-bottom:1px solid currentColor;vertical-align:top}.report-table td{max-width:24rem;overflow-wrap:anywhere}.report-status{flex-basis:100%;overflow-wrap:anywhere;font-size:14px}.report-panel pre{white-space:pre-wrap;overflow-wrap:anywhere}a:focus-visible,select:focus-visible,input:focus-visible,button:focus-visible,.report-table:focus-visible,summary:focus-visible{outline:3px solid var(--rk-primary,var(--fjord,#2C4A6B));outline-offset:3px}@media(max-width:420px){.report-controls,.report-extra{padding:0 12px}.report-controls label{width:100%}.report-controls select{width:100%}.report-panel{padding:16px}}`;
  document.head.append(style);
  function mount(render) {
    const host = document.getElementById('rk-app') || document.querySelector('.wrap') || document.getElementById('fallback-app');
    const original = host.innerHTML;
    const controls = document.createElement('form');
    controls.className = 'report-controls';
    controls.addEventListener('submit', e => e.preventDefault());
    host.before(controls);
    const extra = document.createElement('div'); extra.className = 'report-extra'; host.after(extra);
    function update(restoreFocus) {
      const focused = restoreFocus || document.activeElement?.id;
      document.documentElement.lang = locale();
      const pageName = host.id === 'fallback-app' ? t('Fallback Portfolio Report') : host.id === 'rk-app' ? (language === 'pt' ? 'Relatório da carteira' : 'Portfolio Report') : (language === 'pt' ? 'Visão resumida' : 'Portfolio quickview');
      document.title = 'rikdom · ' + pageName;
      const generatedTitle = document.querySelector('#title-block-header h1');
      if (generatedTitle) generatedTitle.textContent = 'rikdom · ' + pageName;
      const selected = (payload.report_views || []).find(view => `${view.dimension}:${view.value}` === scope);
      const invalid = start && end && start > end;
      const sections = {...(selected?.sections || payload.sections || {})};
      const within = row => !invalid && (!start || String(row.date || row.timestamp).slice(0,10) >= start) && (!end || String(row.date || row.timestamp).slice(0,10) <= end);
      sections.timeline = (sections.timeline || []).filter(within);
      // Returns are precomputed for their disclosed whole window. A narrower
      // date selection cannot reuse that number as a new financial calculation.
      const performance = sections.performance;
      if (performance && (invalid || (start && start > String(performance.period_start).slice(0,10)) || (end && end < String(performance.period_end).slice(0,10)))) sections.performance = null;
      sections.income = {...sections.income, events: (sections.income?.events || []).filter(within)};
      sections.contributions = (sections.contributions || []).filter(within);
      if (sections.income.planning) {
        const planning = {...sections.income.planning};
        for (const key of ['announced', 'estimates', 'reconciliation']) planning[key] = (planning[key] || []).filter(row => within({date:row.payment_date}));
        const visibleIncome = new Set(sections.income.events.map(row => row.activity_id));
        planning.reconciliation = planning.reconciliation.map(row => (row.activity_ids || []).every(id => visibleIncome.has(id)) ? row : {...row, received_amount:null, known_received_subtotal:null, status:'unavailable', reason_code:'linked_payments_not_selected', reason:'Selected dates exclude linked received payments; matching amounts are unavailable without recomputing the original summary.'});
        planning.yield_on_cost = (planning.yield_on_cost || []).map(row => (!invalid && (!start || start <= row.period.start) && (!end || end >= row.period.end)) ? row : {...row, ratio:null, received_amount:null, status:'unavailable', reason_code:'cost_period_not_fully_selected', reason:'Selected dates do not include the entire declared cost-basis period; no partial-period yield substituted.'});
        sections.income.planning = planning;
      }
      const l = labels[language];
      controls.innerHTML = `<label>${t('Language')}<select id="report-language"><option value="en" ${language === 'en' ? 'selected' : ''}>English</option><option value="pt" ${language === 'pt' ? 'selected' : ''}>Português</option></select></label>
        <label>${t('Scope')}<select id="report-scope"><option value="all">${t('All portfolio')}</option>${(payload.report_views || []).map(view => {const id = `${view.dimension}:${view.value}`; return `<option value="${escapeHtml(id)}" ${id === scope ? 'selected' : ''}>${t({account_id:'Account',asset_type_id:'Asset type',currency:'Currency'}[view.dimension])}: ${escapeHtml(view.dimension === 'asset_type_id' ? t(view.value) : view.value)}</option>`;}).join('')}</select></label>
        <label>${t('Recorded dates from')}<input type="date" id="report-start" value="${escapeHtml(start)}"></label><label>${t('Recorded dates through')}<input type="date" id="report-end" value="${escapeHtml(end)}"></label><button type="button" id="report-reset">${t('Reset filters')}</button>
        <div id="filter-status" class="report-status" role="status">${escapeHtml(invalid ? l.invalid : selected ? l.scoped : l.all)} <span>${escapeHtml(l.dates)} ${escapeHtml(l.artifacts)}</span> <span>${t('Snapshots')}: <strong data-snapshot-count>${sections.timeline.length}</strong></span></div>`;
      host.innerHTML = original;
      render({...payload, sections}, locale());
      const current = host.querySelector('#total,.rk-hero-value,[data-current-value]');
      if (current) current.setAttribute('data-current-value', '');
      // Date-limited chart geometry remains meaningful. Whole-history monetary
      // summaries must not masquerade as filtered calculations.
      if (start || end || selected || !sections.timeline.length) host.querySelectorAll('.rk-signed,.rk-period-strip').forEach(node => node.hidden = true);
      translate(host);
      extra.innerHTML = supplementary(sections);
      host.querySelectorAll('a[href="dashboard.html"],a[href="portfolio-report.html"]').forEach(link => {
        const target = link.getAttribute('href');
        if (language === 'pt') link.setAttribute('href', target + '?lang=pt');
      });
      document.getElementById('report-language').addEventListener('change', e => {language = e.target.value; update('report-language');});
      document.getElementById('report-scope').addEventListener('change', e => {scope = e.target.value; update('report-scope');});
      for (const id of ['report-start', 'report-end']) document.getElementById(id).addEventListener('change', e => {if (id === 'report-start') start = e.target.value; else end = e.target.value; update(id);});
      document.getElementById('report-reset').addEventListener('click', () => {scope = 'all'; start = ''; end = ''; update('report-reset');});
      if (focused) document.getElementById(focused)?.focus({preventScroll:true});
    }
    update();
  }
  function mountFallback() {
    mount(data => {
      const s = data.sections || {}, v = s.current_valuation || {}, q = s.data_quality || {}, history = s.timeline || [];
      const host = document.getElementById('fallback-app');
      host.innerHTML = `<h1>${t('Fallback Portfolio Report')}</h1><p>${t('Fallback mode; charts and detailed holdings table are unavailable.')}</p><details><summary>${t('Raw source text')}</summary><p data-source-text>${escapeHtml(host.dataset.reason)}</p></details><p><a href="${escapeHtml(host.dataset.sibling)}">${t(host.dataset.sibling === 'dashboard.html' ? 'Open dashboard quickview' : 'Open deep-dive report')}</a></p><section class="report-panel"><h2>${t('Current valuation')}</h2><p data-current-value>${escapeHtml(money(v.total_value_base, v.base_currency))}</p><h2>${t('Historical snapshot')}</h2><p>${history.length ? `${escapeHtml(money(history.at(-1).portfolio_value_base, v.base_currency))} · ${escapeHtml(date(history.at(-1).timestamp))}` : labels[language].unknown}</p><h2>${t('Data quality')}</h2><p>${t('History coverage')}: ${t(q.coverage?.status || 'unknown')}. ${t('Zero findings do not prove complete history.')}</p><p>${t('Quantity')}: ${Number(q.quantity?.matched || 0)} ${t('matched')}, ${Number(q.quantity?.mismatched || 0)} ${t('mismatched')}, ${Number(q.quantity?.not_computable || 0)} ${t('not computable')}.</p><p>${t('Excluded holdings')}: <span data-source-text>${escapeHtml((q.excluded_holding_ids || []).join(', ') || t('none'))}</span></p><p>${t('Raw source text')}</p><ul data-source-text>${(q.warnings || []).map(row => `<li>${escapeHtml(row)}</li>`).join('')}</ul><p>${(q.artifacts || []).map(row => `<a href="${escapeHtml(row.href)}">${escapeHtml(row.label)}</a>`).join(' · ')}</p></section>`;
    });
  }
  window.RIKDOM_REPORT = {mount, mountFallback, sourceDate:date, sourceDateTime};
})();
