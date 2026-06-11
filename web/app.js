/* Brújula Export — SPA (vanilla JS, módulo ES, ECharts vendorizado en window.echarts) */

const $ = (sel) => document.querySelector(sel);

/* ============================== Formato es-ES ============================== */

const nf0 = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat('es-ES', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const MONTHS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

// Euros en formato compacto: 410000000 → "410 M€"
function fmtEur(v) {
  if (v == null || !isFinite(v)) return 'n/d';
  const a = Math.abs(v);
  if (a >= 1e6) return (a >= 1e8 ? nf0 : nf1).format(v / 1e6) + ' M€';
  if (a >= 1e3) return (a >= 1e5 ? nf0 : nf1).format(v / 1e3) + ' k€';
  return nf0.format(v) + ' €';
}

function fmtPct(v, signed = false) {
  if (v == null || !isFinite(v)) return 'n/d';
  return (signed && v > 0 ? '+' : '') + nf1.format(v * 100) + ' %';
}

function fmtUnitValue(v) {
  return (v == null || !isFinite(v)) ? 'n/d' : nf2.format(v);
}

// "2026-03" → "mar 2026"
function fmtPeriod(p) {
  const [y, m] = p.split('-');
  return MONTHS[+m - 1] + ' ' + y;
}

// "2026-06-12" → "12 de junio de 2026"
function fmtDateISO(iso) {
  const d = new Date(iso + 'T00:00:00');
  return isNaN(d) ? iso : d.toLocaleDateString('es-ES', { day: 'numeric', month: 'long', year: 'numeric' });
}

function flagEmoji(iso2) {
  if (!iso2 || !/^[A-Za-z]{2}$/.test(iso2)) return '🌐';
  return String.fromCodePoint(...[...iso2.toUpperCase()].map((c) => 0x1F1E6 + c.charCodeAt(0) - 65));
}

function escHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/* ============================== Estado y constantes ============================== */

const COMPONENTS = [
  { key: 'size',        label: 'Tamaño',              color: '#44699d' },
  { key: 'growth',      label: 'Crecimiento',          color: '#2e8b9a' },
  { key: 'stability',   label: 'Estabilidad',          color: '#7a6fb3' },
  { key: 'unit_value',  label: 'Valor unitario',       color: '#b5872f' },
  { key: 'competition', label: 'Espacio competitivo',  color: '#8d99ae' },
  { key: 'access',      label: 'Accesibilidad',        color: '#5d7f8f' },
];

const ND_LABELS = {
  nd_growth: 'crecimiento',
  nd_stability: 'estabilidad',
  nd_unit_value: 'valor unitario',
  nd_operators: 'operadores',
};

const ARAGON_PROVINCES = new Set(['50', '22', '44']);

const state = {
  meta: null,
  product: null,          // respuesta de /api/score/{taric}
  weights: {},            // pesos vigentes (fracciones)
  defaultWeights: {},
  rows: new Map(),        // country_code → { tr, data }
  selected: null,         // country_code seleccionado
};

/* ============================== API y toast ============================== */

async function api(path, { allow404 = false } = {}) {
  let res;
  try {
    res = await fetch(path);
  } catch {
    showToast('No se pudo conectar con el servidor. ¿Está arrancado? Ejecuta ./run.sh');
    throw new Error('network');
  }
  if (res.status === 404 && allow404) return null;
  if (!res.ok) {
    let msg = 'Error ' + res.status + ' del servidor';
    try {
      const body = await res.json();
      if (body && body.detail) msg = body.detail;
    } catch { /* cuerpo no JSON */ }
    showToast(msg);
    throw new Error(msg);
  }
  return res.json();
}

let toastTimer;
function showToast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 5000);
}

/* ============================== Metadatos ============================== */

function renderMetaBadge() {
  const m = state.meta;
  const b = $('#meta-badge');
  b.innerHTML =
    `<span class="range">Datos: DataComex · ${fmtPeriod(m.period_min)} – ${fmtPeriod(m.period_max)}</span>` +
    (m.provisional_from ? `<span class="prov">datos desde ${fmtPeriod(m.provisional_from)} provisionales</span>` : '');
  b.title = `${m.source}\n${m.disclaimer}\nExtracción: ${m.extracted_at} · ${nf0.format(m.n_products)} productos · ${nf0.format(m.n_countries)} países`;
  b.hidden = false;
}

/* ============================== Buscador ============================== */

function bindSearch() {
  const input = $('#search-input');
  const box = $('#search-results');
  let timer = null;
  let items = [];
  let active = -1;

  const hide = () => { box.hidden = true; active = -1; };

  function markActive() {
    box.querySelectorAll('.search-item').forEach((el, i) => {
      el.classList.toggle('active', i === active);
      if (i === active) el.scrollIntoView({ block: 'nearest' });
    });
  }

  function pick(r) {
    input.value = `${r.taric} · ${r.description}`;
    hide();
    input.blur();
    loadProduct(r.taric);
  }

  async function runSearch(q) {
    let data;
    try {
      data = await api('/api/search?q=' + encodeURIComponent(q));
    } catch {
      return;
    }
    if (input.value.trim() !== q) return; // respuesta obsoleta
    items = data.results || [];
    active = -1;
    if (!items.length) {
      const sug = data.suggestion || "Prueba con 'vino' o un código como 2204";
      box.innerHTML = `<div class="search-empty">Sin resultados. ${escHtml(sug)}</div>`;
    } else {
      box.innerHTML = items.map((r, i) => `
        <button class="search-item" data-i="${i}" type="button">
          <span class="code">${escHtml(r.taric)}</span>
          <span class="desc" title="${escHtml(r.description)}">${escHtml(r.description)}</span>
          ${r.has_data ? '' : '<span class="tag-nodata">sin datos</span>'}
        </button>`).join('');
    }
    box.hidden = false;
  }

  input.addEventListener('input', () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) { hide(); return; }
    timer = setTimeout(() => runSearch(q), 200);
  });

  input.addEventListener('keydown', (e) => {
    if (box.hidden || !items.length) {
      if (e.key === 'Escape') hide();
      return;
    }
    if (e.key === 'ArrowDown') { e.preventDefault(); active = Math.min(active + 1, items.length - 1); markActive(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(active - 1, 0); markActive(); }
    else if (e.key === 'Enter') { e.preventDefault(); pick(items[active >= 0 ? active : 0]); }
    else if (e.key === 'Escape') { hide(); }
  });

  box.addEventListener('click', (e) => {
    const btn = e.target.closest('.search-item');
    if (btn) pick(items[+btn.dataset.i]);
  });

  document.addEventListener('click', (e) => {
    if (!e.target.closest('.search-box')) hide();
  });
}

/* ============================== Carga de producto ============================== */

async function loadProduct(taric) {
  $('#empty-state').hidden = true;
  $('#product-view').hidden = true;
  $('#left-skeleton').hidden = false;
  resetCountryPanel();

  let data;
  try {
    data = await api('/api/score/' + encodeURIComponent(taric));
  } catch {
    $('#left-skeleton').hidden = true;
    if (!state.product) $('#empty-state').hidden = false;
    else $('#product-view').hidden = false;
    return;
  }

  state.product = data;
  state.defaultWeights = { ...data.default_weights };
  state.weights = { ...data.default_weights };

  renderProductHeader();
  renderSliders();
  buildRankingRows();
  updateRanking(false);

  $('#left-skeleton').hidden = true;
  $('#product-view').hidden = false;

  loadInsights(taric);
}

function renderProductHeader() {
  const p = state.product;
  $('#product-code').textContent = p.taric;
  $('#product-desc').textContent = p.description;
  $('#stat-total').textContent = fmtEur(p.total_exports_12m);
  $('#stat-window').textContent = fmtPeriod(p.period_window.from) + ' – ' + fmtPeriod(p.period_window.to);
  $('#stat-candidates').textContent = nf0.format(p.n_candidates);
  $('#chip-aragon').textContent = 'Cuota Aragón ' + fmtPct(p.aragon_share);
  $('#chip-zaragoza').textContent = 'Zaragoza ' + fmtPct(p.zaragoza_share);

  const warn = $('#product-warning');
  warn.hidden = !p.warning;
  if (p.warning) warn.textContent = '⚠ ' + p.warning;

  $('#ranking-card').hidden = !p.countries.length;
  $('#weights-panel').hidden = !p.countries.length;
}

/* ============================== Sliders de pesos ============================== */

function renderSliders() {
  const wrap = $('#sliders');
  wrap.innerHTML = '';
  for (const c of COMPONENTS) {
    const val = Math.round((state.weights[c.key] || 0) * 100);
    const label = document.createElement('label');
    label.className = 'slider';
    label.innerHTML = `
      <span class="slider-head"><span class="dot" style="background:${c.color}"></span>${c.label}<output>${val} %</output></span>
      <input type="range" min="0" max="50" step="1" value="${val}" aria-label="Peso de ${c.label}">`;
    const input = label.querySelector('input');
    const out = label.querySelector('output');
    input.addEventListener('input', () => {
      state.weights[c.key] = input.value / 100;
      out.textContent = input.value + ' %';
      updateRanking(true);
    });
    wrap.appendChild(label);
  }
}

function bindWeightsReset() {
  $('#btn-reset-weights').addEventListener('click', () => {
    state.weights = { ...state.defaultWeights };
    renderSliders();
    updateRanking(true);
  });
}

/* ============================== Ranking ============================== */

function computeScore(components, weights) {
  let num = 0;
  let den = 0;
  for (const c of COMPONENTS) {
    const w = weights[c.key] || 0;
    num += w * (components[c.key] ?? 50);
    den += w;
  }
  return den ? num / den : 0;
}

function currentRanking() {
  const w = state.weights;
  return state.product.countries
    .map((c) => ({ c, score: computeScore(c.components, w) }))
    .sort((a, b) => (b.score - a.score) || ((b.c.metrics.size_eur_12m || 0) - (a.c.metrics.size_eur_12m || 0)));
}

function cagrClass(v) {
  if (v == null || !isFinite(v)) return '';
  return v > 0 ? 'cagr-pos' : (v < 0 ? 'cagr-neg' : '');
}

function buildRankingRows() {
  const tbody = $('#ranking-body');
  tbody.innerHTML = '';
  state.rows = new Map();
  state.selected = null;

  for (const c of state.product.countries) {
    const tr = document.createElement('tr');
    tr.dataset.cc = c.country_code;

    const lowData = c.flags.includes('low_data')
      ? '<span class="flag-warn" title="Histórico limitado: menos de 12 meses con dato en los últimos 5 años">⚠</span>'
      : '';
    const nd = c.flags.filter((f) => f.startsWith('nd_')).map((f) => ND_LABELS[f] || f);
    const ndTag = nd.length
      ? `<span class="flag-nd" title="Sin dato (componente neutro 50): ${escHtml(nd.join(', '))}">n/d</span>`
      : '';

    tr.innerHTML = `
      <td class="pos"></td>
      <td class="country" title="${escHtml(c.name)} · ${escHtml(c.region || '')}">
        <span class="flag">${flagEmoji(c.iso2)}</span><span class="cname">${escHtml(c.name)}</span>${lowData}${ndTag}
      </td>
      <td class="score"><div class="score-wrap"><span class="score-num"></span><span class="score-bar"><i></i></span></div></td>
      <td class="comps"><span class="stack"></span></td>
      <td class="num">${fmtEur(c.metrics.size_eur_12m)}</td>
      <td class="num ${cagrClass(c.metrics.cagr_3y)}">${fmtPct(c.metrics.cagr_3y, true)}</td>
      <td class="num">${fmtUnitValue(c.metrics.unit_value_eur_kg)}</td>`;

    tr.addEventListener('click', () => selectCountry(c.country_code));
    state.rows.set(c.country_code, { tr, data: c });
  }
}

function renderStack(el, comps, score) {
  const w = state.weights;
  const sum = COMPONENTS.reduce((s, c) => s + (w[c.key] || 0), 0) || 1;
  el.innerHTML = COMPONENTS.map((c) => {
    const part = ((w[c.key] || 0) * (comps[c.key] ?? 50)) / sum; // contribución en puntos de score
    return `<i style="width:${part.toFixed(2)}%;background:${c.color}"></i>`;
  }).join('');
  el.title = COMPONENTS
    .map((c) => `${c.label}: ${comps[c.key] ?? 50} · peso ${Math.round(((w[c.key] || 0) / sum) * 100)} %`)
    .join('\n') + `\nScore: ${Math.round(score)}`;
}

function snapshotPositions(tbody) {
  const m = new Map();
  for (const tr of tbody.children) m.set(tr, tr.getBoundingClientRect().top);
  return m;
}

function playFlip(tbody, before) {
  for (const tr of tbody.children) {
    const prev = before.get(tr);
    if (prev == null) continue;
    const dy = prev - tr.getBoundingClientRect().top;
    if (!dy) { tr.style.transform = ''; continue; }
    tr.style.transition = 'none';
    tr.style.transform = `translateY(${dy}px)`;
  }
  requestAnimationFrame(() => {
    for (const tr of tbody.children) {
      tr.style.transition = 'transform .35s cubic-bezier(.2,.7,.3,1)';
      tr.style.transform = '';
    }
  });
}

function updateRanking(animate) {
  if (!state.product || !state.product.countries.length) return;
  const tbody = $('#ranking-body');
  const before = animate ? snapshotPositions(tbody) : null;
  const ranked = currentRanking();

  ranked.forEach(({ c, score }, i) => {
    const { tr } = state.rows.get(c.country_code);
    tr.querySelector('.pos').textContent = i + 1;
    tr.querySelector('.score-num').textContent = Math.round(score);
    tr.querySelector('.score-bar i').style.width = Math.max(0, Math.min(100, score)).toFixed(1) + '%';
    renderStack(tr.querySelector('.stack'), c.components, score);
    tbody.appendChild(tr);
  });

  if (animate) playFlip(tbody, before);
}

/* ============================== Ficha país ============================== */

function resetCountryPanel() {
  state.selected = null;
  $('#country-panel').hidden = true;
  $('#country-loading').hidden = true;
  $('#country-placeholder').hidden = false;
  $('#insights-panel').hidden = true;
}

async function selectCountry(cc) {
  if (state.selected && state.rows.has(state.selected)) {
    state.rows.get(state.selected).tr.classList.remove('selected');
  }
  state.selected = cc;
  state.rows.get(cc).tr.classList.add('selected');

  $('#country-placeholder').hidden = true;
  $('#country-panel').hidden = true;
  $('#country-loading').hidden = false;

  let data;
  try {
    data = await api(`/api/market/${encodeURIComponent(state.product.taric)}/${encodeURIComponent(cc)}`);
  } catch {
    if (state.selected === cc) {
      $('#country-loading').hidden = true;
      $('#country-placeholder').hidden = false;
    }
    return;
  }
  if (state.selected !== cc) return; // el usuario ya cambió de país

  $('#country-loading').hidden = true;
  renderCountryPanel(data);
}

function renderCountryPanel(d) {
  $('#country-panel').hidden = false;

  $('#cp-flag').textContent = flagEmoji(d.country.iso2);
  $('#cp-name').textContent = d.country.name;
  $('#cp-sub').textContent = (d.country.region || '') + (d.country.eu_member ? ' · UE' : '');
  $('#cp-share').textContent = fmtPct(d.country_share_12m);
  $('#cp-share-label').textContent = `de la exportación española (12 m: ${fmtEur(d.spain_total_12m)})`;

  renderMonthlyChart(d.monthly);
  renderYearlyChart(d.yearly);
  renderSeasonChart(d.seasonality);
  renderProvincesChart(d.provinces);
  renderOperators(d.operators);
}

/* ============================== Gráficos (ECharts) ============================== */

const charts = {};
function chart(id) {
  if (!charts[id]) charts[id] = echarts.init(document.getElementById(id));
  return charts[id];
}
window.addEventListener('resize', () => Object.values(charts).forEach((c) => c.resize()));

const CHART_FONT = { fontFamily: 'system-ui, sans-serif' };
const axisLabel = () => ({ color: '#7a8595', fontSize: 11 });
const splitLine = () => ({ lineStyle: { color: '#edf0f4' } });
const eurAxisLabel = (v) => (Math.abs(v) >= 1e6 ? nf0.format(v / 1e6) + ' M' : Math.abs(v) >= 1e3 ? nf0.format(v / 1e3) + ' k' : nf0.format(v));

function renderMonthlyChart(monthly) {
  const periods = monthly.map((m) => m.period);
  const firstProv = monthly.findIndex((m) => m.is_provisional);
  // serie definitiva hasta el corte; serie provisional desde el mes anterior al corte (para enlazar el trazo)
  const def = monthly.map((m, i) => (firstProv === -1 || i < firstProv ? m.euros : null));
  const prov = monthly.map((m, i) => (firstProv !== -1 && i >= firstProv - 1 ? m.euros : null));

  const series = [{
    name: 'Definitivo', type: 'line', data: def,
    showSymbol: false, color: '#44699d', lineStyle: { width: 2 },
  }];
  if (firstProv !== -1) {
    series.push({
      name: 'Provisional', type: 'line', data: prov,
      showSymbol: false, color: '#8aa6cc', lineStyle: { width: 2, type: 'dashed' },
    });
  }

  chart('chart-monthly').setOption({
    textStyle: CHART_FONT,
    animationDuration: 300,
    legend: { top: 0, right: 0, itemWidth: 16, textStyle: { fontSize: 11, color: '#5f6b7a' } },
    grid: { left: 8, right: 12, top: 28, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      formatter(params) {
        const idx = params[0].dataIndex;
        let pts = params.filter((p) => p.value != null);
        if (pts.length === 2 && pts[0].value === pts[1].value) pts = [pts[0]];
        const lines = pts.map((p) => `${p.marker} ${p.seriesName}: <strong>${fmtEur(p.value)}</strong>`);
        return `${fmtPeriod(periods[idx])}<br>${lines.join('<br>')}`;
      },
    },
    xAxis: {
      type: 'category', data: periods,
      axisTick: { show: false }, axisLine: { lineStyle: { color: '#d6dde6' } },
      axisLabel: { ...axisLabel(), interval: 0, formatter: (p) => (p.endsWith('-01') ? p.slice(0, 4) : '') },
    },
    yAxis: { type: 'value', axisLabel: { ...axisLabel(), formatter: eurAxisLabel }, splitLine: splitLine() },
    series,
  }, true);
}

function renderYearlyChart(yearly) {
  chart('chart-yearly').setOption({
    textStyle: CHART_FONT,
    animationDuration: 300,
    legend: { top: 0, right: 0, itemWidth: 14, textStyle: { fontSize: 11, color: '#5f6b7a' } },
    grid: { left: 8, right: 8, top: 28, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      formatter(params) {
        const lines = params.map((p) => p.seriesIndex === 0
          ? `${p.marker} Exportación: <strong>${fmtEur(p.value)}</strong>`
          : `${p.marker} Valor unitario: <strong>${p.value == null ? 'n/d' : nf2.format(p.value) + ' €/kg'}</strong>`);
        return `${params[0].axisValueLabel}<br>${lines.join('<br>')}`;
      },
    },
    xAxis: {
      type: 'category', data: yearly.map((y) => y.year),
      axisTick: { show: false }, axisLine: { lineStyle: { color: '#d6dde6' } }, axisLabel: axisLabel(),
    },
    yAxis: [
      { type: 'value', axisLabel: { ...axisLabel(), formatter: eurAxisLabel }, splitLine: splitLine() },
      { type: 'value', name: '€/kg', nameTextStyle: { color: '#b5872f', fontSize: 10 }, axisLabel: { ...axisLabel(), color: '#b5872f' }, splitLine: { show: false } },
    ],
    series: [
      {
        name: 'Exportación (€)', type: 'bar', data: yearly.map((y) => y.euros),
        itemStyle: { color: '#44699d', borderRadius: [3, 3, 0, 0] }, barMaxWidth: 26,
      },
      {
        name: 'Valor unitario (€/kg)', type: 'line', yAxisIndex: 1, data: yearly.map((y) => y.unit_value),
        color: '#b5872f', symbol: 'circle', symbolSize: 5, lineStyle: { width: 2 },
      },
    ],
  }, true);
}

function renderSeasonChart(seasonality) {
  const el = document.getElementById('chart-season');
  const empty = $('#season-empty');
  if (!seasonality.length) {
    el.hidden = true;
    empty.hidden = false;
    return;
  }
  el.hidden = false;
  empty.hidden = true;

  const byMonth = seasonality.slice().sort((a, b) => a.month - b.month);
  const c = chart('chart-season');
  c.resize();
  c.setOption({
    textStyle: CHART_FONT,
    animationDuration: 300,
    grid: { left: 8, right: 8, top: 12, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      formatter: (params) => `${params[0].name}: <strong>${nf1.format(params[0].value)} %</strong> del total anual`,
    },
    xAxis: {
      type: 'category', data: byMonth.map((s) => MONTHS[s.month - 1]),
      axisTick: { show: false }, axisLine: { lineStyle: { color: '#d6dde6' } },
      axisLabel: { ...axisLabel(), interval: 0, fontSize: 9.5 },
    },
    yAxis: { type: 'value', axisLabel: { ...axisLabel(), formatter: (v) => nf0.format(v) + ' %' }, splitLine: splitLine() },
    series: [{
      type: 'bar', data: byMonth.map((s) => +(s.avg_share * 100).toFixed(2)),
      itemStyle: { color: '#7a93b5', borderRadius: [3, 3, 0, 0] }, barMaxWidth: 18,
    }],
  }, true);
}

function renderProvincesChart(provinces) {
  const el = document.getElementById('chart-provinces');
  const empty = $('#prov-empty');
  if (!provinces.length) {
    el.hidden = true;
    empty.hidden = false;
    return;
  }
  el.hidden = false;
  empty.hidden = true;

  // orden ascendente porque ECharts pinta las barras horizontales de abajo arriba
  const rows = provinces.slice().sort((a, b) => (a.euros_12m || 0) - (b.euros_12m || 0));
  el.style.height = Math.max(140, 30 + rows.length * 26) + 'px';
  const c = chart('chart-provinces');
  c.resize();
  c.setOption({
    textStyle: CHART_FONT,
    animationDuration: 300,
    grid: { left: 8, right: 56, top: 6, bottom: 4, containLabel: true },
    tooltip: {
      formatter(p) {
        const r = rows[p.dataIndex];
        return `${escHtml(r.name)}: <strong>${fmtEur(r.euros_12m)}</strong> · ${fmtPct(r.share)} del total nacional`;
      },
    },
    xAxis: { type: 'value', splitNumber: 3, axisLabel: { ...axisLabel(), formatter: eurAxisLabel }, splitLine: splitLine() },
    yAxis: {
      type: 'category', data: rows.map((r) => r.name),
      axisTick: { show: false }, axisLine: { lineStyle: { color: '#d6dde6' } }, axisLabel: axisLabel(),
    },
    series: [{
      type: 'bar', barMaxWidth: 16,
      data: rows.map((r) => ({
        value: r.euros_12m,
        itemStyle: {
          color: ARAGON_PROVINCES.has(r.province_code) ? '#9d2235' : '#9fb1c9',
          borderRadius: [0, 3, 3, 0],
        },
      })),
      label: {
        show: true, position: 'right', fontSize: 11, color: '#5f6b7a',
        formatter: (p) => fmtPct(rows[p.dataIndex].share),
      },
    }],
  }, true);
}

function renderOperators(operators) {
  const tbody = $('#operators-body');
  if (!operators.length) {
    tbody.innerHTML = '<tr><td colspan="3" class="empty-note">Sin datos de operadores para este destino.</td></tr>';
    return;
  }
  tbody.innerHTML = operators
    .slice()
    .sort((a, b) => b.year - a.year)
    .map((o) => `
      <tr>
        <td>${o.year}</td>
        <td class="num">${o.num_operators == null ? '<span class="nd">n/d (secreto estadístico)</span>' : nf0.format(o.num_operators)}</td>
        <td class="num">${fmtEur(o.euros)}</td>
      </tr>`).join('');
}

/* ============================== Insights IA ============================== */

async function loadInsights(taric) {
  const panel = $('#insights-panel');
  panel.hidden = true;
  let data = null;
  try {
    data = await api('/api/insights/' + encodeURIComponent(taric), { allow404: true });
  } catch {
    return;
  }
  if (!data || !state.product || state.product.taric !== taric) return;
  $('#insights-body').innerHTML = renderMarkdown(data.markdown || '');
  $('#insights-date').textContent = data.generated_at ? 'Generado el ' + fmtDateISO(data.generated_at) : '';
  panel.hidden = false;
}

// Mini-renderer de markdown: #/##/###, **negrita**, *cursiva*, listas con - o *, párrafos.
function renderMarkdown(md) {
  const inline = (s) => escHtml(s)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>');

  const out = [];
  let list = null;
  let para = [];
  const flushPara = () => { if (para.length) { out.push('<p>' + inline(para.join(' ')) + '</p>'); para = []; } };
  const flushList = () => { if (list) { out.push('<ul>' + list.map((i) => '<li>' + inline(i) + '</li>').join('') + '</ul>'); list = null; } };

  for (const raw of md.split('\n')) {
    const line = raw.trim();
    const h = line.match(/^(#{1,3})\s+(.*)$/);
    if (h) { flushPara(); flushList(); out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); continue; }
    const li = line.match(/^[-*]\s+(.*)$/);
    if (li) { flushPara(); if (!list) list = []; list.push(li[1]); continue; }
    if (!line) { flushPara(); flushList(); continue; }
    flushList();
    para.push(line);
  }
  flushPara();
  flushList();
  return out.join('\n');
}

/* ============================== Informe imprimible ============================== */

function bindReport() {
  $('#btn-report').addEventListener('click', () => {
    if (!state.product) return;
    buildReport();
    document.body.classList.add('print-mode');
    const prevTitle = document.title;
    document.title = 'Brujula-Export_' + state.product.taric;
    window.print();
    document.title = prevTitle;
  });
  window.addEventListener('afterprint', () => document.body.classList.remove('print-mode'));
}

function buildReport() {
  const p = state.product;
  const m = state.meta || {};
  const top = currentRanking().slice(0, 10);
  const w = state.weights;
  const sum = COMPONENTS.reduce((s, c) => s + (w[c.key] || 0), 0) || 1;
  const weightsRow = COMPONENTS.map((c) => `${c.label} ${Math.round(((w[c.key] || 0) / sum) * 100)} %`).join(' · ');
  const today = new Date().toLocaleDateString('es-ES', { day: 'numeric', month: 'long', year: 'numeric' });
  const source = m.source || 'DataComex — Secretaría de Estado de Comercio. Comercio declarado.';
  const disclaimer = m.disclaimer || 'Datos 2024 en adelante provisionales. Celdas con ≤5 operadores ocultas por secreto estadístico.';

  const rowsHtml = top.map(({ c, score }, i) => `
    <tr>
      <td>${i + 1}</td>
      <td>${escHtml(c.name)}${c.flags.includes('low_data') ? ' ⚠' : ''}</td>
      <td><strong>${Math.round(score)}</strong></td>
      ${COMPONENTS.map((k) => `<td>${c.components[k.key] ?? 50}</td>`).join('')}
      <td>${fmtEur(c.metrics.size_eur_12m)}</td>
      <td>${fmtPct(c.metrics.cagr_3y, true)}</td>
    </tr>`).join('');

  $('#report').innerHTML = `
    <header class="r-cover">
      <div class="r-brand">Brújula Export</div>
      <h1>Informe de selección de mercados</h1>
      <p class="r-product"><strong>${escHtml(p.taric)}</strong> — ${escHtml(p.description)}</p>
      <p class="r-meta">Fecha: ${today} · Fuente: ${escHtml(source)} · Ventana 12 m: ${fmtPeriod(p.period_window.from)} – ${fmtPeriod(p.period_window.to)}</p>
    </header>

    <section>
      <table class="r-kpis"><tr>
        <td><span>Exportación España 12 m</span><strong>${fmtEur(p.total_exports_12m)}</strong></td>
        <td><span>Cuota Aragón</span><strong>${fmtPct(p.aragon_share)}</strong></td>
        <td><span>Cuota Zaragoza</span><strong>${fmtPct(p.zaragoza_share)}</strong></td>
        <td><span>Países candidatos</span><strong>${nf0.format(p.n_candidates)}</strong></td>
      </tr></table>
    </section>

    <section class="r-ranking">
      <h2>Top 10 mercados por score</h2>
      <p class="r-weights">Pesos aplicados: ${weightsRow}</p>
      <table class="r-table">
        <thead>
          <tr>
            <th>#</th><th>País</th><th>Score</th>
            ${COMPONENTS.map((c) => `<th>${c.label}</th>`).join('')}
            <th>Export. 12 m</th><th>CAGR 3a</th>
          </tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>
      <p class="r-note">⚠ = histórico limitado (&lt;12 meses con dato en 5 años). Componentes expresados como percentil 0-100 entre los ${nf0.format(p.n_candidates)} países candidatos del producto.</p>
    </section>

    <section class="r-method">
      <h2>Metodología</h2>
      <p>El score (0-100) de cada país es la media ponderada de seis componentes. Cada métrica se normaliza como ranking percentil [0-100] entre los países candidatos del producto (aquellos con exportación española &gt; 0 en los últimos 3 años). Las métricas no calculables reciben el componente neutro 50 y se marcan como «n/d».</p>
      <ul>
        <li><strong>Tamaño:</strong> valor exportado por España al destino en los últimos 12 meses completos.</li>
        <li><strong>Crecimiento:</strong> CAGR a 3 años de los valores anuales (winsorizado p5-p95).</li>
        <li><strong>Estabilidad:</strong> 1 − coeficiente de variación de los últimos 5 valores anuales.</li>
        <li><strong>Valor unitario:</strong> €/kg de los últimos 12 meses frente a la mediana de los destinos (proxy de mercado premium).</li>
        <li><strong>Espacio competitivo:</strong> valor medio por operador español (€/operador, último año con dato).</li>
        <li><strong>Accesibilidad:</strong> UE = 100 · EFTA/Acuerdo UE = 75 · Resto = 40.</li>
      </ul>
      <p><strong>Fuente:</strong> ${escHtml(source)}</p>
      <p><strong>Cautelas:</strong> ${escHtml(disclaimer)} Las cifras reflejan la exportación española declarada (demanda revelada del producto español), no la demanda mundial del producto.</p>
    </section>`;
}

/* ============================== Arranque ============================== */

function bindExampleChips() {
  document.querySelectorAll('.chip-action[data-taric]').forEach((btn) => {
    btn.addEventListener('click', () => loadProduct(btn.dataset.taric));
  });
}

async function init() {
  bindSearch();
  bindExampleChips();
  bindWeightsReset();
  bindReport();
  try {
    state.meta = await api('/api/meta');
    renderMetaBadge();
  } catch {
    /* el toast ya avisó; la app sigue siendo usable cuando vuelva el servidor */
  }
}

init();
