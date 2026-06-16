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

// Cuota positiva pero por debajo del redondeo a 1 decimal: «<0,1 %» en vez de
// «0,0 %» (un 0 fabricado contradice la regla n/d-nunca-cero del proyecto).
function fmtPctMin(v) {
  if (v != null && isFinite(v) && v > 0 && v * 100 < 0.05) return '<0,1 %';
  return fmtPct(v);
}

function fmtUnitValue(v) {
  return (v == null || !isFinite(v)) ? 'n/d' : nf2.format(v);
}

// CAGR con tope visual: por encima de +500% el porcentaje (artefacto de base
// mínima) satura la lectura; mostramos ">+500 %" y dejamos el valor real en el
// title de la celda (§2.4). El cálculo del ranking ya winsoriza aparte.
function fmtCagr(v) {
  if (v != null && isFinite(v) && v > 5) return '>+500 %';
  return fmtPct(v, true);
}

// "2026-03" → "mar 2026"
function fmtPeriod(p) {
  if (!p) return 'n/d';
  const [y, m] = p.split('-');
  return MONTHS[+m - 1] + ' ' + y;
}

function flagEmoji(iso2) {
  if (!iso2 || !/^[A-Za-z]{2}$/.test(iso2)) return '🌐';
  return String.fromCodePoint(...[...iso2.toUpperCase()].map((c) => 0x1F1E6 + c.charCodeAt(0) - 65));
}

function escHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/* ============================== Estado y constantes ============================== */

// «Espacio competitivo» (nº de operadores) se omite: la tabla de operadores no
// tiene datos en esta extracción, así que valdría el neutro 50 en todos los
// países (componente sin señal). Si en el futuro se cargan los operadores,
// basta volver a añadir su entrada aquí y en ND_LABELS.
const COMPONENTS = [
  { key: 'size',        label: 'Tamaño',              color: '#4a8fd4', def: 'Valor exportado por España al destino en los últimos 12 meses completos.',
    tip: 'Súbelo para priorizar los mercados a los que España ya exporta más volumen (madurez actual).' },
  { key: 'growth',      label: 'Crecimiento',          color: '#2aacb8', def: 'CAGR a 3 años de los valores anuales (winsorizado p5-p95).',
    tip: 'Súbelo para priorizar mercados en auge (CAGR 3 años), aunque hoy sean pequeños — oportunidad.' },
  { key: 'stability',   label: 'Estabilidad',          color: '#9080d0', def: '1 − coeficiente de variación de los últimos 5 valores anuales.',
    tip: 'Súbelo para priorizar mercados con ventas regulares año a año y penalizar los erráticos.' },
  { key: 'unit_value',  label: 'Valor unitario',       color: '#c9a84c', def: '€/kg de los últimos 12 m frente a la mediana de destinos (proxy premium; a 4 dígitos puede mezclar calidades).',
    tip: 'Súbelo para priorizar mercados que pagan más €/kg (posicionamiento premium).' },
  { key: 'access',      label: 'Accesibilidad',        color: '#5095a8', def: 'UE = 100 · EFTA/Acuerdo UE = 75 · Resto = 40.',
    tip: 'Súbelo para priorizar la UE y países con acuerdo comercial con la UE (menos barreras).' },
];

// Pesos por defecto del modelo de 5 componentes (sin 'competition'). Suman 1
// exacto para que sliders e informe muestren porcentajes redondos (28/28/16/16/12).
const DEFAULT_WEIGHTS = {
  size: 0.28, growth: 0.28, stability: 0.16, unit_value: 0.16, access: 0.12,
};

const ND_LABELS = {
  nd_growth: 'crecimiento',
  nd_stability: 'estabilidad',
  nd_unit_value: 'valor unitario',
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
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.classList.remove('show'); }, 5000);
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
  const status = $('#search-status');
  let timer = null;
  let items = [];
  let active = -1;

  const hide = () => {
    box.hidden = true;
    active = -1;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
  };

  function markActive() {
    box.querySelectorAll('.search-item').forEach((el, i) => {
      const on = i === active;
      el.classList.toggle('active', on);
      el.setAttribute('aria-selected', on ? 'true' : 'false');
      if (on) { el.scrollIntoView({ block: 'nearest' }); input.setAttribute('aria-activedescendant', el.id); }
    });
    if (active < 0) input.removeAttribute('aria-activedescendant');
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
      status.textContent = 'Sin resultados';
    } else {
      box.innerHTML = items.map((r, i) => `
        <button class="search-item" id="opt-${i}" role="option" aria-selected="false" data-i="${i}" type="button">
          <span class="code">${escHtml(r.taric)}</span>
          <span class="desc" title="${escHtml(r.description)}">${escHtml(r.description)}</span>
          ${r.has_data ? '' : '<span class="tag-nodata">sin datos</span>'}
        </button>`).join('');
      status.textContent = `${items.length} resultado${items.length === 1 ? '' : 's'}`;
    }
    box.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  }

  input.addEventListener('focus', () => input.select());

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

let loadToken = 0;
async function loadProduct(taric) {
  // Un código de 2 dígitos es un capítulo, no un producto concreto: mostramos
  // su índice de subpartidas en vez de un ranking vacío.
  if (taric.length === 2) return loadChapter(taric);
  const my = ++loadToken;
  $('#empty-state').hidden = true;
  $('#product-view').hidden = true;
  $('#chapter-view').hidden = true;
  $('#left-skeleton').hidden = false;
  resetCountryPanel();

  let data;
  try {
    data = await api('/api/score/' + encodeURIComponent(taric));
  } catch {
    if (my !== loadToken) return;
    $('#left-skeleton').hidden = true;
    if (!state.product) $('#empty-state').hidden = false;
    else $('#product-view').hidden = false;
    return;
  }
  if (my !== loadToken) return; // otra carga más reciente ganó: descartar

  state.product = data;
  // El backend envía default_weights del modelo de 6 componentes (con
  // 'competition', que se omite por falta de datos de operadores); usamos los
  // pesos por defecto del modelo de 5 (DEFAULT_WEIGHTS).
  state.defaultWeights = { ...DEFAULT_WEIGHTS };
  state.weights = { ...DEFAULT_WEIGHTS };

  renderProductHeader();
  renderSliders();
  buildRankingRows();
  updateRanking(false);

  $('#left-skeleton').hidden = true;
  $('#product-view').hidden = false;
}

function renderProductHeader() {
  const p = state.product;
  const hasData = !!p.countries.length;
  $('#product-code').textContent = p.taric;
  // Algunas filas de la nomenclatura DataComex son códigos internos sin
  // descripción real ('=====(literal pendiente…'): no los mostramos como título.
  const junk = /^=+|literal pendiente/i.test(p.description || '');
  const desc = $('#product-desc');
  desc.textContent = junk ? 'Producto sin descripción disponible' : p.description;
  desc.title = junk ? '' : (p.description || '');
  $('#stat-total').textContent = fmtEur(p.total_exports_12m);
  $('#stat-window').textContent = fmtPeriod(p.period_window?.from) + ' – ' + fmtPeriod(p.period_window?.to);
  $('#stat-candidates').textContent = nf0.format(p.n_candidates);
  $('#chip-aragon').textContent = 'Cuota Aragón ' + fmtPct(p.aragon_share);
  $('#chip-zaragoza').textContent = 'Zaragoza ' + fmtPct(p.zaragoza_share);
  // Sin países candidatos no hay KPIs ni cuotas reales: ocultamos la fila de
  // estadísticas (evita 'n/d' por todos lados y una ventana temporal sin sentido).
  $('.product-stats').hidden = !hasData;

  const warn = $('#product-warning');
  warn.hidden = !p.warning;
  if (p.warning) warn.textContent = '⚠ ' + p.warning;

  $('#ranking-card').hidden = !hasData;
  $('#weights-panel').hidden = !hasData;
  $('#btn-report').hidden = !hasData;
  renderCompsLegend(hasData);

  $('#country-placeholder').querySelector('p').textContent = hasData
    ? 'Selecciona un país del ranking para ver su ficha de mercado: evolución, estacionalidad, valor unitario y provincias.'
    : 'Sin ranking disponible para este producto: no hay países con histórico suficiente.';
}

// Leyenda fija de colores del desglose: mapea cada color a su criterio para que
// la columna «Desglose» sea interpretable sin depender solo del hover (§5.1, §7.3).
function renderCompsLegend(show) {
  const el = $('#comps-legend');
  if (!el) return;
  el.hidden = !show;
  if (!show) return;
  el.innerHTML = '<span class="cl-title">Desglose</span>' + COMPONENTS.map((c) =>
    `<span class="cl-item"><i style="background:${c.color}"></i>${escHtml(c.label)}</span>`).join('');
}

/* ============================== Índice de capítulo ============================== */

// "CAPÍTULO 22 - BEBIDAS, LÍQUIDOS…" → "Bebidas, líquidos…" (quita prefijo y baja mayúsculas)
function chapterTitle(desc) {
  const s = (desc || '').replace(/^CAP[IÍ]TULO\s+\d+\s*[-–—]\s*/i, '').trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : (desc || '');
}

async function loadChapter(code) {
  const my = ++loadToken;
  $('#empty-state').hidden = true;
  $('#product-view').hidden = true;
  $('#chapter-view').hidden = true;
  $('#left-skeleton').hidden = false;
  state.product = null;
  resetCountryPanel();
  $('#country-placeholder').querySelector('p').textContent =
    'Elige una subpartida del índice para ver su ranking de mercados de exportación.';

  let data;
  try {
    data = await api('/api/chapter/' + encodeURIComponent(code));
  } catch {
    if (my !== loadToken) return;
    $('#left-skeleton').hidden = true;
    $('#empty-state').hidden = false;
    return;
  }
  if (my !== loadToken) return;

  renderChapterIndex(data);
  $('#left-skeleton').hidden = true;
  $('#chapter-view').hidden = false;
}

function renderChapterIndex(d) {
  $('#chapter-code').textContent = d.code;
  $('#chapter-desc').textContent = chapterTitle(d.description);
  const withData = d.children.filter((c) => c.has_data);
  $('#chapter-count').textContent =
    `${d.children.length} subpartida${d.children.length === 1 ? '' : 's'} · ${withData.length} con datos`;

  const max = Math.max(1, ...withData.map((c) => c.total_12m || 0));
  const wrap = $('#chapter-index');
  if (!d.children.length) {
    wrap.innerHTML = '<p class="empty-note">Este capítulo no tiene subpartidas de 4 dígitos en la nomenclatura.</p>';
    return;
  }
  wrap.innerHTML = d.children.map((c) => {
    const pct = c.has_data ? Math.max(2, (c.total_12m / max) * 100) : 0;
    return `
      <button class="chapter-item${c.has_data ? '' : ' nodata'}" data-taric="${escHtml(c.taric)}" type="button">
        <span class="ci-code">${escHtml(c.taric)}</span>
        <span class="ci-main">
          <span class="ci-desc" title="${escHtml(c.description)}">${escHtml(c.description)}</span>
          <span class="ci-bar"><i style="width:${pct.toFixed(1)}%"></i></span>
        </span>
        <span class="ci-val">${c.has_data ? fmtEur(c.total_12m) : 'sin datos'}</span>
      </button>`;
  }).join('');
  wrap.querySelectorAll('.chapter-item').forEach((btn) => {
    btn.addEventListener('click', () => loadProduct(btn.dataset.taric));
  });
}

/* ============================== Sliders de pesos ============================== */

// Salidas de los sliders por criterio, para refrescar todas a la vez.
const sliderOutputs = {};

// El score solo depende de los pesos RELATIVOS (Σ w_i·c_i / Σ w_i). El número
// que ve el usuario es ese peso efectivo normalizado a 100 %: al subir un slider,
// el % mostrado de los demás baja, y el conjunto suma ~100 % (§2.5). El valor del
// mando (0-50) sigue siendo la palanca de intención.
function refreshWeightLabels() {
  const sum = COMPONENTS.reduce((s, c) => s + (state.weights[c.key] || 0), 0);
  for (const c of COMPONENTS) {
    const out = sliderOutputs[c.key];
    if (!out) continue;
    const text = sum > 0 ? Math.round((state.weights[c.key] || 0) / sum * 100) + ' %' : '—';
    out.textContent = text;
    const input = out.closest('.slider')?.querySelector('input');
    if (input) input.setAttribute('aria-valuetext', `peso efectivo ${text}`);
  }
}

function renderSliders() {
  const wrap = $('#sliders');
  wrap.innerHTML = '';
  for (const c of COMPONENTS) {
    const val = Math.round((state.weights[c.key] || 0) * 100);
    const label = document.createElement('label');
    label.className = 'slider';
    label.innerHTML = `
      <span class="slider-head"><span class="dot" style="background:${c.color}"></span>${c.label}<output></output></span>
      <input type="range" min="0" max="50" step="1" value="${val}" aria-label="Peso de ${c.label}" aria-describedby="tip-${c.key}">
      <span class="slider-tip" id="tip-${c.key}" role="tooltip" style="border-left-color:${c.color}">${c.tip}</span>`;
    const input = label.querySelector('input');
    sliderOutputs[c.key] = label.querySelector('output');
    input.addEventListener('input', () => {
      state.weights[c.key] = input.value / 100;
      refreshWeightLabels();
      updateRanking(true);
    });
    wrap.appendChild(label);
  }
  refreshWeightLabels();
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
    const nd = c.flags.filter((f) => ND_LABELS[f]).map((f) => ND_LABELS[f]);
    const ndTag = nd.length
      ? `<span class="flag-nd" title="Sin dato (componente neutro 50): ${escHtml(nd.join(', '))}">n/d</span>`
      : '';

    // Señalización de calidad de datos (NO altera el score; solo avisa, §2.1-2.3):
    const size = c.metrics.size_eur_12m;
    const k = c.components;
    let baseTag = '';
    if (size === 0) {
      baseTag = '<span class="flag-stale" title="Candidato (exportó en los últimos 3 años) pero 0 € en los últimos 12 meses: sin exportación reciente.">sin export. reciente</span>';
    } else if (k.size < 25 && (k.growth > 75 || k.unit_value > 75)) {
      baseTag = '<span class="flag-small" title="Base reducida: su crecimiento o €/kg —altos sobre una base pequeña— lo impulsan en el ranking. Léelo como oportunidad volátil, no como tamaño.">base reducida</span>';
    }

    const cagr = c.metrics.cagr_3y;
    const cagrCapped = cagr != null && isFinite(cagr) && cagr > 5;
    const cagrCell = `<td class="num ${cagrClass(cagr)}"${cagrCapped ? ` title="CAGR real: ${fmtPct(cagr, true)}"` : ''}>${fmtCagr(cagr)}</td>`;

    const uvRel = c.metrics.unit_value_rel;
    const uvOutlier = uvRel != null && isFinite(uvRel) && uvRel > 5;
    const uvCell = `<td class="num${uvOutlier ? ' uv-outlier' : ''}"${uvOutlier ? ' title="Valor unitario atípico (>5× la mediana de destinos): probable artefacto de un envío marginal que distorsiona el criterio de valor unitario."' : ''}>${fmtUnitValue(c.metrics.unit_value_eur_kg)}</td>`;

    tr.innerHTML = `
      <td class="pos"></td>
      <td class="country" title="${escHtml(c.name)} · ${escHtml(c.region || '')}">
        <span class="flag">${flagEmoji(c.iso2)}</span><span class="cname">${escHtml(c.name)}</span>${lowData}${ndTag}${baseTag}
      </td>
      <td class="score"><div class="score-wrap"><span class="score-num"></span><span class="score-bar"><i></i></span></div></td>
      <td class="comps"><span class="stack"></span></td>
      <td class="num">${fmtEur(c.metrics.size_eur_12m)}</td>
      ${cagrCell}
      ${uvCell}`;

    tr.tabIndex = 0;
    tr.setAttribute('role', 'button');
    tr.setAttribute('aria-label', `${c.name}, ver ficha de mercado`);
    tr.addEventListener('click', () => selectCountry(c.country_code));
    tr.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectCountry(c.country_code); }
    });
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
    .map((c) => `${c.label}: ${Math.round(comps[c.key] ?? 50)} · peso ${Math.round(((w[c.key] || 0) / sum) * 100)} %`)
    .join('\n') + `\nScore: ${Math.round(score)}`;
  el.setAttribute('aria-label', el.title);
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

  // Con todos los pesos a 0 el score es 0 para todos y el orden pierde sentido:
  // avisamos y bloqueamos el informe en vez de mostrar un ranking vacío silencioso.
  const wSum = COMPONENTS.reduce((s, c) => s + (state.weights[c.key] || 0), 0);
  const warn = $('#product-warning');
  if (wSum === 0) {
    warn.textContent = '⚠ Asigna peso a algún criterio (están todos a 0) para ordenar el ranking.';
    warn.hidden = false;
    $('#btn-report').disabled = true;
  } else {
    const pw = state.product.warning;
    warn.hidden = !pw;
    warn.textContent = pw ? '⚠ ' + pw : '';
    $('#btn-report').disabled = false;
  }

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
}

async function selectCountry(cc) {
  // Re-clic sobre la fila ya seleccionada con su ficha visible: no recargar
  // (evita el parpadeo a spinner). Sí dejamos pasar carga en curso y reintento.
  if (state.selected === cc && !$('#country-panel').hidden) return;
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
}

/* ============================== Gráficos (ECharts) ============================== */

const charts = {};
function chart(id) {
  if (!charts[id]) {
    const el = document.getElementById(id);
    const instance = echarts.init(el);
    charts[id] = instance;
    // Un ResizeObserver por contenedor: el gráfico se recompone ante CUALQUIER
    // cambio de tamaño (panel que pasa de oculto a visible, reflow del grid,
    // carga de fuentes, resize de ventana). Sin esto, ECharts cachea el tamaño
    // del momento del init y, si el contenedor estaba a 0/estrecho, los ejes
    // quedan colapsados y el plot comprimido hasta un resize manual (§4.x).
    if (typeof ResizeObserver !== 'undefined') {
      new ResizeObserver(() => instance.resize()).observe(el);
    }
  }
  return charts[id];
}
window.addEventListener('resize', () => Object.values(charts).forEach((c) => c.resize()));

const CHART_FONT = { fontFamily: 'system-ui, sans-serif', color: '#6e8ba5' };
const axisLabel = () => ({ color: '#6e8ba5', fontSize: 11 });
const splitLine = () => ({ lineStyle: { color: '#192e47' } });
const eurAxisLabel = (v) => (Math.abs(v) >= 1e6 ? nf0.format(v / 1e6) + ' M' : Math.abs(v) >= 1e3 ? nf0.format(v / 1e3) + ' k' : nf0.format(v));
const chartTooltip = (extra = {}) => ({
  backgroundColor: '#102236', borderColor: '#213d5c',
  textStyle: { color: '#ddd4bc', fontSize: 12 }, ...extra,
});
const chartLegend = () => ({ top: 0, right: 0, itemWidth: 14, textStyle: { fontSize: 11, color: '#6e8ba5' } });

function renderMonthlyChart(monthly) {
  chart('chart-monthly').resize(); // recalcula tamaño con el contenedor ya visible
  const periods = monthly.map((m) => m.period);
  const firstProv = monthly.findIndex((m) => m.is_provisional);
  // serie definitiva hasta el corte; serie provisional desde el mes anterior al corte (para enlazar el trazo)
  const def = monthly.map((m, i) => (firstProv === -1 || i < firstProv ? m.euros : null));
  const prov = monthly.map((m, i) => (firstProv !== -1 && i >= firstProv - 1 ? m.euros : null));

  // Solo añadimos cada serie si tiene algún punto: evita una leyenda 'Definitivo'
  // fantasma en países que solo tienen meses provisionales. Con un único punto,
  // mostramos el símbolo para que no quede un gráfico aparentemente vacío.
  const fewPoints = monthly.length < 2;
  const series = [];
  if (def.some((v) => v != null)) {
    series.push({
      name: 'Definitivo', type: 'line', data: def,
      showSymbol: fewPoints, symbolSize: 6, color: '#4a8fd4', lineStyle: { width: 2 },
    });
  }
  if (firstProv !== -1 && prov.some((v) => v != null)) {
    series.push({
      name: 'Provisional', type: 'line', data: prov,
      showSymbol: fewPoints, symbolSize: 6, color: '#6aadd8', lineStyle: { width: 2, type: 'dashed' },
    });
  }

  chart('chart-monthly').setOption({
    textStyle: CHART_FONT,
    animationDuration: 300,
    legend: chartLegend(),
    grid: { left: 8, right: 12, top: 28, bottom: 4, containLabel: true },
    tooltip: {
      ...chartTooltip(),
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
      axisTick: { show: false }, axisLine: { lineStyle: { color: '#213d5c' } },
      axisLabel: { ...axisLabel(), interval: 0, formatter: (p) => (p.endsWith('-01') ? p.slice(0, 4) : '') },
    },
    yAxis: { type: 'value', axisLabel: { ...axisLabel(), formatter: eurAxisLabel }, splitLine: splitLine() },
    series,
  }, true);
}

function renderYearlyChart(yearly) {
  // El último año suele ser parcial (p.ej. 2026 = solo hasta el último mes con
  // dato): lo marcamos para que su barra corta no se lea como un desplome.
  const pmax = state.meta?.period_max || '';
  const partialYear = pmax && !pmax.endsWith('-12') ? +pmax.slice(0, 4) : null;
  chart('chart-yearly').resize(); // recalcula tamaño con el contenedor ya visible
  chart('chart-yearly').setOption({
    textStyle: CHART_FONT,
    animationDuration: 300,
    legend: chartLegend(),
    grid: { left: 8, right: 8, top: 28, bottom: 4, containLabel: true },
    tooltip: {
      ...chartTooltip(),
      trigger: 'axis',
      formatter(params) {
        const lines = params.map((p) => p.seriesIndex === 0
          ? `${p.marker} Exportación: <strong>${fmtEur(p.value)}</strong>`
          : `${p.marker} Valor unitario: <strong>${p.value == null ? 'n/d' : nf2.format(p.value) + ' €/kg'}</strong>`);
        const note = +params[0].axisValueLabel === partialYear
          ? '<br><span style="color:#c9a84c">año en curso · solo datos parciales</span>' : '';
        return `${params[0].axisValueLabel}<br>${lines.join('<br>')}${note}`;
      },
    },
    xAxis: {
      type: 'category', data: yearly.map((y) => y.year),
      axisTick: { show: false }, axisLine: { lineStyle: { color: '#213d5c' } }, axisLabel: axisLabel(),
    },
    yAxis: [
      { type: 'value', axisLabel: { ...axisLabel(), formatter: eurAxisLabel }, splitLine: splitLine() },
      { type: 'value', name: '€/kg', nameTextStyle: { color: '#c9a84c', fontSize: 10 }, axisLabel: { ...axisLabel(), color: '#c9a84c' }, splitLine: { show: false } },
    ],
    series: [
      {
        name: 'Exportación (€)', type: 'bar', barMaxWidth: 26,
        data: yearly.map((y) => {
          const partial = y.year === partialYear;
          return {
            value: y.euros,
            itemStyle: {
              color: partial ? '#2f5575' : '#3a7fc0', borderRadius: [3, 3, 0, 0],
              decal: partial ? { symbol: 'rect', dashArrayX: [1, 3], dashArrayY: [2, 4], rotation: -Math.PI / 4, color: 'rgba(221,212,188,.22)' } : null,
            },
            label: partial ? { show: true, position: 'top', formatter: 'parcial', color: '#c9a84c', fontSize: 9, fontWeight: 700 } : undefined,
          };
        }),
      },
      {
        name: 'Valor unitario (€/kg)', type: 'line', yAxisIndex: 1, data: yearly.map((y) => y.unit_value),
        color: '#c9a84c', symbol: 'circle', symbolSize: 5, lineStyle: { width: 2 },
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
      ...chartTooltip(),
      trigger: 'axis',
      formatter: (params) => `${params[0].name}: <strong>${nf1.format(params[0].value)} %</strong> del total anual`,
    },
    xAxis: {
      type: 'category', data: byMonth.map((s) => MONTHS[s.month - 1]),
      axisTick: { show: false }, axisLine: { lineStyle: { color: '#213d5c' } },
      axisLabel: { ...axisLabel(), interval: 0, fontSize: 9.5 },
    },
    yAxis: { type: 'value', axisLabel: { ...axisLabel(), formatter: (v) => nf0.format(v) + ' %' }, splitLine: splitLine() },
    series: [{
      type: 'bar', data: byMonth.map((s) => +(s.avg_share * 100).toFixed(2)),
      itemStyle: { color: '#3a7fc0', borderRadius: [3, 3, 0, 0] }, barMaxWidth: 18,
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
  el.style.height = Math.max(190, 30 + rows.length * 26) + 'px';
  const c = chart('chart-provinces');
  c.resize();
  c.setOption({
    textStyle: CHART_FONT,
    animationDuration: 300,
    grid: { left: 8, right: 56, top: 6, bottom: 4, containLabel: true },
    tooltip: {
      ...chartTooltip(),
      formatter(p) {
        const r = rows[p.dataIndex];
        return `${escHtml(r.name)}: <strong>${fmtEur(r.euros_12m)}</strong> · ${fmtPctMin(r.share)} del total nacional`;
      },
    },
    xAxis: { type: 'value', splitNumber: 3, axisLabel: { ...axisLabel(), formatter: eurAxisLabel }, splitLine: splitLine() },
    yAxis: {
      type: 'category', data: rows.map((r) => r.name),
      axisTick: { show: false }, axisLine: { lineStyle: { color: '#213d5c' } }, axisLabel: axisLabel(),
    },
    series: [{
      type: 'bar', barMaxWidth: 16, barMinHeight: 3,
      data: rows.map((r) => ({
        value: r.euros_12m,
        itemStyle: {
          color: ARAGON_PROVINCES.has(r.province_code) ? '#d94060' : '#3a6f92',
          borderRadius: [0, 3, 3, 0],
        },
      })),
      label: {
        show: true, position: 'right', fontSize: 11, color: '#6e8ba5',
        formatter: (p) => fmtPctMin(rows[p.dataIndex].share),
      },
    }],
  }, true);
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
  const today = new Date().toLocaleDateString('es-ES', { day: 'numeric', month: 'long', year: 'numeric' });
  const source = m.source || 'DataComex — Secretaría de Estado de Comercio. Comercio declarado.';
  const disclaimer = m.disclaimer || 'Datos 2024 en adelante provisionales. Celdas con ≤5 operadores ocultas por secreto estadístico.';
  const maxScore = Math.max(1, ...top.map((t) => t.score));

  const weightsRow = COMPONENTS.map((c) =>
    `<span class="r-wchip"><i style="background:${c.color}"></i>${c.label} ${Math.round(((w[c.key] || 0) / sum) * 100)}%</span>`).join('');

  const rowsHtml = top.map(({ c, score }, i) => {
    const stack = COMPONENTS.map((k) => {
      const part = ((w[k.key] || 0) * (c.components[k.key] ?? 50)) / sum;
      return `<i style="width:${part.toFixed(2)}%;background:${k.color}"></i>`;
    }).join('');
    const cagr = c.metrics.cagr_3y;
    const cagrCls = cagr == null || !isFinite(cagr) ? '' : (cagr > 0 ? 'r-pos' : (cagr < 0 ? 'r-neg' : ''));
    const warn = c.flags.includes('low_data')
      ? ' <span class="r-warn" title="histórico limitado">▲</span>' : '';
    return `
      <tr>
        <td class="r-rank">${i + 1}</td>
        <td class="r-country">${escHtml(c.name)}${warn}</td>
        <td class="r-scorecell">
          <span class="r-score-n">${Math.round(score)}</span>
          <span class="r-score-track"><i style="width:${(score / maxScore * 100).toFixed(1)}%"></i></span>
        </td>
        <td class="r-stackcell"><span class="r-stack">${stack}</span></td>
        <td class="r-num">${fmtEur(c.metrics.size_eur_12m)}</td>
        <td class="r-num ${cagrCls}">${fmtPct(cagr, true)}</td>
      </tr>`;
  }).join('');

  $('#report').innerHTML = `
    <header class="r-cover">
      <div class="r-mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="34" height="34" fill="none">
          <circle cx="12" cy="12" r="9.5" stroke="currentColor" stroke-width="1.4"/>
          <polygon points="12,4.8 14.3,12 12,19.2 9.7,12" fill="currentColor"/>
          <circle cx="12" cy="12" r="1.3" fill="#9d2235"/>
        </svg>
      </div>
      <div class="r-cover-body">
        <div class="r-brand">Brújula Export</div>
        <h1>Informe de selección de mercados</h1>
        <p class="r-product"><span class="r-pcode">${escHtml(p.taric)}</span>${escHtml(p.description)}</p>
      </div>
      <div class="r-cover-meta">
        <span>${today}</span>
        <span>Ventana 12 m · ${fmtPeriod(p.period_window?.from)} – ${fmtPeriod(p.period_window?.to)}</span>
      </div>
    </header>

    <section class="r-kpis">
      <div class="r-kpi"><span>Exportación España · 12 m</span><strong>${fmtEur(p.total_exports_12m)}</strong></div>
      <div class="r-kpi r-kpi-accent"><span>Cuota Aragón</span><strong>${fmtPct(p.aragon_share)}</strong></div>
      <div class="r-kpi r-kpi-accent"><span>Cuota Zaragoza</span><strong>${fmtPct(p.zaragoza_share)}</strong></div>
      <div class="r-kpi"><span>Países candidatos</span><strong>${nf0.format(p.n_candidates)}</strong></div>
    </section>

    <section class="r-ranking">
      <div class="r-sechead">
        <h2>Top 10 mercados por score</h2>
        <div class="r-weights">${weightsRow}</div>
      </div>
      <table class="r-table">
        <thead>
          <tr>
            <th class="r-th-rank">#</th><th>País</th>
            <th class="r-th-score">Score</th><th>Desglose por criterio</th>
            <th class="r-num">Export. 12 m</th><th class="r-num">CAGR 3a</th>
          </tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>
      <p class="r-note"><span class="r-warn">▲</span> histórico limitado (&lt;12 meses con dato en 5 años). Cada criterio es un percentil 0-100 entre los ${nf0.format(p.n_candidates)} países candidatos del producto; el ancho de cada color es su contribución al score.</p>
    </section>

    <section class="r-method">
      <h2>Metodología</h2>
      <p class="r-lead">El score (0-100) de cada país es la media ponderada de cinco componentes. Cada métrica se normaliza como ranking percentil [0-100] entre los países candidatos del producto (exportación española &gt; 0 en los últimos 3 años). Las métricas no calculables reciben el componente neutro 50 y se marcan como «n/d».</p>
      <div class="r-defs">
        ${COMPONENTS.map((c) => `
          <div class="r-def">
            <span class="r-dot" style="background:${c.color}"></span>
            <div><strong>${c.label}.</strong> ${c.def}</div>
          </div>`).join('')}
      </div>
      <div class="r-cautions">
        <strong>Cautelas.</strong> ${escHtml(disclaimer)} Las cifras reflejan la exportación española declarada —demanda revelada del producto español—, no la demanda mundial del producto.
      </div>
    </section>

    <footer class="r-foot">
      <span class="r-foot-brand">Brújula Export</span>
      <span>${escHtml(source)}</span>
      <span>${today}</span>
    </footer>`;
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
