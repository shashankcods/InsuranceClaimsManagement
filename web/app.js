// Insurance back office: single-page front end. No build step, no framework.
// Every rule lives in MySQL; this file only calls the API and shows results/errors.
'use strict';

const $ = (sel, el = document) => el.querySelector(sel);
const main = () => $('#main');
let META = null;

// ---------------------------------------------------------------- helpers
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const inr = (v) => (v == null || v === '') ? '—' : '₹' + Number(v).toLocaleString('en-IN', { maximumFractionDigits: 0 });
const num = (v) => (v == null || v === '') ? '—' : Number(v).toLocaleString('en-IN');
const day = (v) => v ? String(v).slice(0, 10) : '—';
const badge = (v) => v == null ? '—' : `<span class="badge b-${esc(v)}">${esc(String(v).replace('_', ' '))}</span>`;
const pct = (v) => v == null ? '—' : `${Number(v).toFixed(1)}%`;
// risk_band comes from v_claim_summary, which derives it from the active model's threshold
const risk = (s, band) => s == null ? '<span class="muted">not scored</span>' : `${badge(band)} <span class="muted">${Number(s).toFixed(2)}</span>`;
const BAND_COLOR = { HIGH: '#b00', MEDIUM: '#c80', LOW: '#070' };

async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || 'GET',
    headers: opts.body ? { 'Content-Type': 'application/json' } : {},
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = res.headers.get('content-type')?.includes('json') ? await res.json() : await res.text();
  if (!res.ok) {
    let msg = data?.detail ?? data;
    if (Array.isArray(msg)) msg = msg.map((d) => `${d.loc?.slice(-1)[0]}: ${d.msg}`).join('; ');
    const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    err.status = res.status; err.errno = data?.errno;
    throw err;
  }
  return data;
}

function toast(msg, isError = false) {
  const t = $('#toast');
  t.textContent = msg; t.className = 'toast' + (isError ? ' error' : '');
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add('hidden'), isError ? 7000 : 3000);
}
const showError = (e) => toast(`${e.status ? e.status + ' · ' : ''}${e.errno ? 'MySQL ' + e.errno + ': ' : ''}${e.message}`, true);

function openDrawer(html) { $('#drawer-body').innerHTML = html; $('#drawer').classList.remove('hidden'); }
function closeDrawer() { $('#drawer').classList.add('hidden'); }
function openModal(html) { $('#modal-body').innerHTML = html; $('#modal').classList.remove('hidden'); }
function closeModal() { $('#modal').classList.add('hidden'); }
$('#drawer').addEventListener('click', (e) => { if (e.target.id === 'drawer') closeDrawer(); });
$('#modal').addEventListener('click', (e) => { if (e.target.id === 'modal') closeModal(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeModal(); closeDrawer(); } });

function formData(form) {
  const out = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === 'checkbox') out[el.name] = el.checked ? 1 : 0;
    else if (el.value !== '') out[el.name] = el.value;
  }
  return out;
}

// Tiny SVG bar chart (no external library)
function barChart(rows, labelKey, valueKey, { height = 180, fmt = num, color = '#5a7ca8' } = {}) {
  if (!rows.length) return '<p class="muted">No data</p>';
  const w = 560, pad = 28, bw = (w - pad) / rows.length;
  const max = Math.max(...rows.map((r) => Number(r[valueKey]) || 0), 1);
  const bars = rows.map((r, i) => {
    const v = Number(r[valueKey]) || 0, h = (v / max) * (height - 40);
    const x = pad + i * bw + bw * 0.15, y = height - 22 - h;
    return `<rect x="${x}" y="${y}" width="${bw * 0.7}" height="${h}" fill="${color}"><title>${esc(r[labelKey])}: ${fmt(v)}</title></rect>
            <text x="${x + bw * 0.35}" y="${height - 8}" text-anchor="middle">${esc(String(r[labelKey]).slice(0, 7))}</text>
            <text x="${x + bw * 0.35}" y="${y - 4}" text-anchor="middle">${rows.length <= 8 ? fmt(v) : ''}</text>`;
  }).join('');
  return `<div class="chart"><svg viewBox="0 0 ${w} ${height}">${bars}</svg></div>`;
}

// ---------------------------------------------------------------- generic list table
// cols: [{key, label, fmt?, num?, nosort?}]
function listView({ title, sub, endpoint, cols, filters = '', defaultSort, defaultOrder = 'asc', onRow, toolbarExtra = '', pageSize = 25, initial = {} }) {
  const state = { search: '', sort: defaultSort, order: defaultOrder, offset: 0, extra: { ...initial } };
  main().innerHTML = `
    <h1>${title}</h1><div class="sub">${sub || ''}</div>
    <div class="toolbar">
      <input id="lv-search" placeholder="Search…" style="min-width:220px">
      ${filters}
      <span class="spacer"></span>${toolbarExtra}
    </div>
    <div class="table-wrap"><table><thead><tr>${cols.map((c) =>
      `<th data-key="${c.key}" class="${c.num ? 'num' : ''} ${c.nosort ? 'nosort' : ''}">${c.label}</th>`).join('')}</tr></thead>
      <tbody id="lv-body"><tr><td colspan="${cols.length}" class="muted">Loading…</td></tr></tbody></table>
      <div class="pager"><button id="lv-prev">‹ Prev</button><button id="lv-next">Next ›</button><span id="lv-info"></span></div>
    </div>`;
  let rows = [];
  async function load() {
    const p = new URLSearchParams({ limit: pageSize, offset: state.offset, sort: state.sort, order: state.order });
    if (state.search) p.set('search', state.search);
    for (const [k, v] of Object.entries(state.extra)) if (v !== '') p.set(k, v);
    try {
      const data = await api(`${endpoint}?${p}`);
      rows = data.items;
      $('#lv-body').innerHTML = rows.length ? rows.map((r, i) => `<tr class="${onRow ? 'clickable' : ''}" data-i="${i}">${cols.map((c) =>
        `<td class="${c.num ? 'num' : ''}">${c.fmt ? c.fmt(r[c.key], r) : esc(r[c.key] ?? '—')}</td>`).join('')}</tr>`).join('')
        : `<tr><td colspan="${cols.length}" class="muted">No rows</td></tr>`;
      $('#lv-info').textContent = `${data.total ? state.offset + 1 : 0}–${Math.min(state.offset + pageSize, data.total)} of ${num(data.total)}`;
      $('#lv-prev').disabled = state.offset === 0;
      $('#lv-next').disabled = state.offset + pageSize >= data.total;
      main().querySelectorAll('th').forEach((th) => {
        th.textContent = cols.find((c) => c.key === th.dataset.key).label + (th.dataset.key === state.sort ? (state.order === 'asc' ? ' ▲' : ' ▼') : '');
      });
    } catch (e) { showError(e); }
  }
  let t;
  $('#lv-search').addEventListener('input', (e) => { clearTimeout(t); t = setTimeout(() => { state.search = e.target.value; state.offset = 0; load(); }, 250); });
  $('#lv-prev').onclick = () => { state.offset = Math.max(0, state.offset - pageSize); load(); };
  $('#lv-next').onclick = () => { state.offset += pageSize; load(); };
  main().querySelectorAll('th:not(.nosort)').forEach((th) => th.onclick = () => {
    state.order = state.sort === th.dataset.key && state.order === 'asc' ? 'desc' : 'asc';
    state.sort = th.dataset.key; state.offset = 0; load();
  });
  main().querySelectorAll('[data-filter]').forEach((el) => {
    if (initial[el.dataset.filter] != null) el.value = initial[el.dataset.filter];
    el.onchange = () => { state.extra[el.dataset.filter] = el.value; state.offset = 0; load(); };
  });
  if (onRow) $('#lv-body').onclick = (e) => { const tr = e.target.closest('tr[data-i]'); if (tr) onRow(rows[tr.dataset.i]); };
  load();
  return { reload: load };
}

const sel = (name, options, placeholder) =>
  `<select data-filter="${name}"><option value="">${placeholder}</option>${options.map((o) =>
    typeof o === 'object' ? `<option value="${esc(o.v)}">${esc(o.l)}</option>` : `<option>${esc(o)}</option>`).join('')}</select>`;

// ---------------------------------------------------------------- generic CRUD screens (F1)
const CRUD = {
  pincodes: {
    title: 'Pincodes', sub: 'pincode → city, state. Kept in its own table so customer and provider stay in BCNF.',
    cols: [['pincode', 'Pincode'], ['city', 'City'], ['state', 'State']],
    fields: [['pincode', 'Pincode (6 digits)'], ['city', 'City'], ['state', 'State']],
  },
  customers: {
    title: 'Customers', sub: 'Policy holders. City and state come from the pincode table (FK); gender and e-mail are CHECK / UNIQUE constrained.',
    cols: [['customer_id', 'ID'], ['first_name', 'First name'], ['last_name', 'Last name'], ['email', 'E-mail'],
      ['phone', 'Phone'], ['pincode', 'Pincode'], ['city', 'City'], ['state', 'State'], ['dob', 'DOB', day]],
    fields: [['first_name', 'First name'], ['last_name', 'Last name'], ['dob', 'Date of birth', 'date'],
      ['gender', 'Gender', ['M', 'F', 'O']], ['email', 'E-mail', 'email'], ['phone', 'Phone'],
      ['address_line', 'Address', 'text', 'full'], ['pincode', 'Pincode (must exist in Pincodes)']],
    filters: () => sel('gender', ['M', 'F', 'O'], 'Any gender'),
  },
  agents: {
    title: 'Agents', sub: 'Sales agents. manager_id is a self-referencing foreign key.',
    cols: [['agent_id', 'ID'], ['first_name', 'First name'], ['last_name', 'Last name'], ['email', 'E-mail'],
      ['branch_city', 'Branch'], ['commission_rate', 'Commission %'], ['manager_id', 'Manager ID'], ['hire_date', 'Hired', day]],
    fields: [['first_name', 'First name'], ['last_name', 'Last name'], ['email', 'E-mail', 'email'], ['phone', 'Phone'],
      ['branch_city', 'Branch city'], ['hire_date', 'Hire date', 'date'], ['commission_rate', 'Commission % (0-30)', 'number'],
      ['manager_id', 'Manager agent ID', 'number']],
  },
  providers: {
    title: 'Providers', sub: 'Hospitals, clinics, garages and repair centres.',
    cols: [['provider_id', 'ID'], ['name', 'Name'], ['provider_type', 'Type'], ['city', 'City'], ['state', 'State'],
      ['is_network', 'Network', (v) => v ? badge('ACTIVE').replace('ACTIVE', 'network') : badge('LAPSED').replace('LAPSED', 'non-network')]],
    fields: [['name', 'Name', 'text', 'full'], ['provider_type', 'Type', ['HOSPITAL', 'CLINIC', 'GARAGE', 'REPAIR_CENTRE']],
      ['phone', 'Phone'], ['pincode', 'Pincode'], ['is_network', 'Network provider', 'checkbox']],
    filters: () => sel('provider_type', ['HOSPITAL', 'CLINIC', 'GARAGE', 'REPAIR_CENTRE'], 'Any type') +
      sel('is_network', [{ v: 1, l: 'Network' }, { v: 0, l: 'Non-network' }], 'Any network'),
  },
  adjusters: {
    title: 'Adjusters', sub: 'Claim assessors. BR5: an adjuster cannot approve above their approval limit.',
    cols: [['adjuster_id', 'ID'], ['first_name', 'First name'], ['last_name', 'Last name'], ['email', 'E-mail'],
      ['phone', 'Phone'], ['approval_limit', 'Approval limit', inr, true]],
    fields: [['first_name', 'First name'], ['last_name', 'Last name'], ['email', 'E-mail', 'email'], ['phone', 'Phone'],
      ['approval_limit', 'Approval limit (₹)', 'number']],
  },
  'policy-types': {
    title: 'Policy types', sub: 'The product catalogue. The policy trigger checks every sale against min/max cover.',
    cols: [['type_id', 'ID'], ['type_name', 'Product'], ['min_sum_assured', 'Min cover', inr, true],
      ['max_sum_assured', 'Max cover', inr, true], ['base_rate_pct', 'Rate %/yr'], ['max_term_years', 'Max term (yrs)']],
    fields: [['type_name', 'Name'], ['description', 'Description', 'text', 'full'], ['min_sum_assured', 'Min sum assured', 'number'],
      ['max_sum_assured', 'Max sum assured', 'number'], ['base_rate_pct', 'Base rate % per year', 'number'],
      ['max_term_years', 'Max term (years)', 'number']],
  },
};

function crudScreen(resource) {
  const cfg = CRUD[resource];
  const pk = cfg.cols[0][0];
  const lv = listView({
    title: cfg.title, sub: cfg.sub, endpoint: `/api/${resource}`, defaultSort: pk,
    filters: cfg.filters ? cfg.filters() : '',
    toolbarExtra: `<button class="primary" id="crud-add">+ Add</button>`,
    cols: cfg.cols.map(([key, label, fmt, isNum]) => ({ key, label, fmt, num: isNum })),
    onRow: (row) => crudForm(resource, row, lv),
  });
  $('#crud-add').onclick = () => crudForm(resource, null, lv);
}

function crudForm(resource, row, lv) {
  const cfg = CRUD[resource], pk = cfg.cols[0][0];
  const field = ([name, label, type = 'text', cls = '']) => {
    const v = row ? row[name] ?? '' : '';
    if (Array.isArray(type)) return `<label class="${cls}">${label}<select name="${name}" required>${type.map((o) => `<option ${o === v ? 'selected' : ''}>${o}</option>`).join('')}</select></label>`;
    if (type === 'checkbox') return `<label class="${cls}"><span><input type="checkbox" name="${name}" ${row ? (v ? 'checked' : '') : 'checked'}> ${label}</span></label>`;
    return `<label class="${cls}">${label}<input name="${name}" type="${type}" step="any" value="${esc(type === 'date' ? day(v).replace('—', '') : v)}"></label>`;
  };
  openModal(`<h2 style="margin-top:0">${row ? 'Edit' : 'New'} ${cfg.title.replace(/s$/, '').toLowerCase()} ${row ? '#' + row[pk] : ''}</h2>
    <form id="crud-form" class="form-grid">${cfg.fields.map(field).join('')}</form>
    <div class="actions">${row ? '<button class="danger" id="crud-del">Delete</button><span style="flex:1"></span>' : ''}
      <button onclick="closeModal()">Cancel</button><button class="primary" id="crud-save">Save</button></div>`);
  $('#crud-save').onclick = async () => {
    try {
      const body = formData($('#crud-form'));
      if (row) await api(`/api/${resource}/${row[pk]}`, { method: 'PUT', body });
      else await api(`/api/${resource}`, { method: 'POST', body });
      closeModal(); toast('Saved'); lv.reload();
    } catch (e) { showError(e); }
  };
  if (row) $('#crud-del').onclick = async () => {
    if (!confirm('Delete this record?')) return;
    try { await api(`/api/${resource}/${row[pk]}`, { method: 'DELETE' }); closeModal(); toast('Deleted'); lv.reload(); }
    catch (e) { showError(e); }
  };
}

// ---------------------------------------------------------------- dashboard
async function dashboard() {
  main().innerHTML = '<h1>Dashboard</h1><div class="sub">Live figures from the database views.</div><div id="dash">Loading…</div>';
  try {
    const d = await api('/api/reports/dashboard');
    const k = d.kpis;
    const lr = k.premium_12m ? (100 * k.payouts_12m / k.premium_12m) : null;
    $('#dash').innerHTML = `
      <div class="kpis">
        <div class="kpi"><div class="label">Active policies</div><div class="value">${num(k.active_policies)}</div></div>
        <div class="kpi"><div class="label">Lapsed policies</div><div class="value">${num(k.lapsed_policies)}</div></div>
        <div class="kpi"><div class="label">Customers</div><div class="value">${num(k.customers)}</div></div>
        <div class="kpi"><div class="label">Open claims</div><div class="value">${num(k.open_claims)}</div></div>
        <div class="kpi"><div class="label">High-risk open claims</div><div class="value" style="color:#b00">${num(k.high_risk_open)}</div></div>
        <div class="kpi"><div class="label">Premium, last 12 months</div><div class="value">${inr(k.premium_12m)}</div></div>
        <div class="kpi"><div class="label">Claims paid, last 12 months</div><div class="value">${inr(k.payouts_12m)}</div></div>
        <div class="kpi"><div class="label">Loss ratio, 12 months</div><div class="value">${pct(lr)}</div></div>
        <div class="kpi"><div class="label">Overdue instalments</div><div class="value">${num(k.overdue_instalments)}</div></div>
      </div>
      <div class="grid2" style="margin-top:16px">
        <div class="card"><h2>Claims filed per month</h2>${barChart(d.monthly.map((m) => ({ ...m, m: m.month_start.slice(2, 7) })), 'm', 'claims_filed')}</div>
        <div class="card"><h2>Loss ratio by product (%)</h2>${barChart(d.loss_ratio, 'type_name', 'loss_ratio_pct', { fmt: (v) => v.toFixed(0) + '%', color: '#5a7ca8' })}</div>
        <div class="card"><h2>Claims by status</h2>${barChart(d.claims_by_status, 'status', 'n', { color: '#5a7ca8' })}</div>
        <div class="card"><h2>Active policies by product</h2>${barChart(d.policies_by_type, 'type_name', 'n', { color: '#5a7ca8' })}</div>
      </div>`;
  } catch (e) { showError(e); }
}

// ---------------------------------------------------------------- claims (F4-F7)
function claimsScreen() {
  const lv = listView({
    title: 'Claims', sub: 'Open claims first, highest fraud risk first. Click a claim to work it.',
    endpoint: '/api/claims', defaultSort: 'fraud_score', defaultOrder: 'desc',
    filters: sel('status', [{ v: 'SUBMITTED,UNDER_REVIEW', l: 'Open (submitted + review)' }, 'SUBMITTED', 'UNDER_REVIEW', 'APPROVED', 'REJECTED', 'PAID'], 'All statuses') +
      sel('type_name', ['Health', 'Motor', 'Life', 'Home', 'Travel'], 'All products') +
      sel('risk_band', ['HIGH', 'MEDIUM', 'LOW'], 'Any risk'),
    toolbarExtra: `<button id="score-open">Score open claims</button><button class="primary" id="new-claim">+ File claim</button>`,
    cols: [
      { key: 'claim_number', label: 'Claim' }, { key: 'status', label: 'Status', fmt: badge },
      { key: 'type_name', label: 'Product' }, { key: 'customer_name', label: 'Customer' },
      { key: 'claimed_amount', label: 'Claimed', fmt: inr, num: true }, { key: 'filed_on', label: 'Filed', fmt: day },
      { key: 'fraud_score', label: 'Fraud risk', fmt: (v, r) => risk(v, r.risk_band) },
    ],
    onRow: (r) => claimDrawer(r.claim_id, () => lv.reload()),
    initial: { status: 'SUBMITTED,UNDER_REVIEW' },
  });
  $('#score-open').onclick = async () => {
    try { const r = await api('/api/fraud/score-open', { method: 'POST' }); toast(`Scored ${r.scored} open claims: ${r.bands.HIGH} high, ${r.bands.MEDIUM} medium, ${r.bands.LOW} low`); lv.reload(); }
    catch (e) { showError(e); }
  };
  $('#new-claim').onclick = () => claimForm(() => lv.reload());
}

function claimForm(after, policyId = '') {
  openModal(`<h2 style="margin-top:0">File a claim</h2>
    <p class="muted">BR1–BR3 are checked by the <code>trg_claim_bi</code> trigger: policy must not be lapsed/cancelled, incident inside the policy period, amount ≤ sum assured.</p>
    <form id="claim-form" class="form-grid">
      <label>Policy ID<input name="policy_id" type="number" required value="${esc(policyId)}"></label>
      <label>Claim type<select name="claim_type">${META.claim_types.map((t) => `<option>${t}</option>`).join('')}</select></label>
      <label>Incident date<input name="incident_date" type="date" required></label>
      <label>Claimed amount (₹)<input name="claimed_amount" type="number" step="any" required></label>
      <label class="full">Provider (optional)<select name="provider_id"><option value="">— none —</option>${META.providers.map((p) =>
        `<option value="${p.provider_id}">${esc(p.name)}${p.is_network ? '' : ' (non-network)'}</option>`).join('')}</select></label>
      <label class="full">Description<textarea name="description"></textarea></label>
    </form>
    <div class="actions"><button onclick="closeModal()">Cancel</button><button class="primary" id="claim-save">File claim</button></div>`);
  $('#claim-save').onclick = async () => {
    try {
      const r = await api('/api/claims', { method: 'POST', body: formData($('#claim-form')) });
      closeModal(); toast(`Filed ${r.claim.claim_number}`); after && after(); claimDrawer(r.claim.claim_id, after);
    } catch (e) { showError(e); }
  };
}

const adjusterOptions = () => META.adjusters.map((a) => `<option value="${a.adjuster_id}">${esc(a.name)} (limit ${inr(a.approval_limit)})</option>`).join('');

async function claimDrawer(id, after) {
  let d;
  try { d = await api(`/api/claims/${id}/detail`); } catch (e) { return showError(e); }
  const c = d.claim, f = d.features || {};
  const s = c.fraud_score;
  const color = BAND_COLOR[c.risk_band] || '#ccc';
  let actions = '';
  if (c.status === 'SUBMITTED') actions = `<div class="row"><label>Adjuster<select id="wf-adj">${adjusterOptions()}</select></label>
      <button class="primary" data-act="start-review">Start review</button></div>`;
  if (c.status === 'UNDER_REVIEW') actions = `<div class="row">
      <label>Adjuster<select id="wf-adj">${adjusterOptions()}</select></label>
      <label>Approved amount (₹)<input id="wf-amt" type="number" value="${c.claimed_amount}" style="width:140px"></label>
      <label>Payout method<select id="wf-method"><option>NEFT</option><option>UPI</option><option>CHEQUE</option><option>DIRECT_TO_PROVIDER</option></select></label></div>
      <div class="row"><label style="flex:1">Remarks<input id="wf-rem" placeholder="Assessment remarks"></label></div>
      <div class="row"><button class="ok" data-act="approve">Approve</button>
      <button class="primary" data-act="approve-and-pay">Approve &amp; pay (atomic)</button>
      <button data-act="request-info">Request info</button>
      <button class="danger" data-act="reject">Reject</button>
      <label style="flex-direction:row;align-items:center;gap:5px"><input type="checkbox" id="wf-fraud"> confirmed fraud</label></div>`;
  if (c.status === 'APPROVED') actions = `<div class="row"><label>Payout method<select id="wf-method"><option>NEFT</option><option>UPI</option><option>CHEQUE</option><option>DIRECT_TO_PROVIDER</option></select></label>
      <button class="primary" data-act="pay">Pay ${inr(c.approved_amount)}</button></div>`;
  openDrawer(`
    <h1>${esc(c.claim_number)} ${badge(c.status)}</h1>
    <div class="sub">${esc(c.type_name)} · ${esc(c.claim_type)} · policy <a href="#" id="go-policy">${esc(c.policy_number)}</a> · ${esc(c.customer_name)}</div>
    <div class="grid2">
      <div class="card"><dl class="kv">
        <dt>Incident date</dt><dd>${day(c.incident_date)}</dd><dt>Filed on</dt><dd>${esc(c.filed_on)}</dd>
        <dt>Claimed</dt><dd>${inr(c.claimed_amount)}</dd><dt>Approved</dt><dd>${inr(c.approved_amount)}</dd>
        <dt>Paid</dt><dd>${inr(c.paid_amount)}${d.payout ? ` <span class="muted">(${esc(d.payout.reference_no)})</span>` : ''}</dd>
        <dt>Provider</dt><dd>${esc(c.provider_name || '—')}${c.provider_id && !c.is_network ? ' ' + badge('non-network') : ''}</dd>
        <dt>Adjuster</dt><dd>${esc(c.adjuster_name || '—')}</dd><dt>Confirmed fraud</dt><dd>${c.fraud_flag ? badge('HIGH').replace('HIGH', 'YES') : 'No'}</dd>
      </dl></div>
      <div class="card"><h3 style="margin-top:0">Fraud risk</h3>
        <div style="font-size:26px;font-weight:700">${s == null ? '—' : Number(s).toFixed(2)} ${s == null ? '' : badge(c.risk_band)}</div>
        <div class="risk-meter"><div style="width:${(s || 0) * 100}%;background:${color}"></div></div>
        <button style="margin-top:10px" data-act="fraud-score">Re-score</button>
        <button style="margin-top:10px" data-act="${c.fraud_flag ? 'unflag' : 'flag'}">${c.fraud_flag ? 'Clear fraud flag' : 'Mark as confirmed fraud'}</button>
        <dl class="kv" style="margin-top:12px;font-size:12px">
          <dt>Claim / sum assured</dt><dd>${f.claim_ratio ?? '—'}</dd><dt>Days since start</dt><dd>${f.days_since_start ?? '—'}</dd>
          <dt>Filing delay (days)</dt><dd>${f.filing_delay ?? '—'}</dd><dt>Documents at filing</dt><dd>${f.documents_attached ?? '—'}</dd>
          <dt>Prior claims</dt><dd>${f.prior_claims ?? '—'}</dd><dt>Late premiums</dt><dd>${f.late_payments ?? '—'}</dd>
        </dl></div>
    </div>
    ${actions ? `<div class="workflow"><h3 style="margin-top:0">Workflow</h3>${actions}</div>` : ''}
    <h2>Documents (${d.documents.length})</h2>
    <div class="table-wrap"><table><tr><th class="nosort">Type</th><th class="nosort">File</th><th class="nosort">Uploaded</th></tr>
      ${d.documents.map((x) => `<tr><td>${esc(x.doc_type)}</td><td>${esc(x.file_name)}</td><td>${esc(x.uploaded_on)}</td></tr>`).join('') || '<tr><td colspan=3 class="muted">None</td></tr>'}</table></div>
    <div class="row" style="display:flex;gap:8px;margin-top:8px"><select id="doc-type">${META.doc_types.map((t) => `<option>${t}</option>`).join('')}</select>
      <input id="doc-name" placeholder="file name, e.g. bill_123.pdf"><button data-act="add-doc">Attach</button></div>
    <h2>Assessments</h2>
    <div class="table-wrap"><table><tr><th class="nosort">When</th><th class="nosort">Adjuster</th><th class="nosort">Decision</th><th class="nosort num">Amount</th><th class="nosort">Remarks</th></tr>
      ${d.assessments.map((a) => `<tr><td>${esc(a.assessed_on)}</td><td>${esc(a.adjuster_name)}</td><td>${badge(a.decision)}</td><td class="num">${inr(a.approved_amount)}</td><td>${esc(a.remarks || '')}</td></tr>`).join('') || '<tr><td colspan=5 class="muted">None</td></tr>'}</table></div>
    <h2>Audit trail <span class="muted" style="font-weight:400">(claim_status_log, written by triggers)</span></h2>
    <ul class="timeline">${d.status_log.map((l) => `<li>${l.old_status ? badge(l.old_status) + ' → ' : ''}${badge(l.new_status)} <small>${esc(l.changed_at)} · ${esc(l.changed_by)}</small></li>`).join('')}</ul>`);

  $('#go-policy').onclick = (e) => { e.preventDefault(); policyDrawer(c.policy_id); };
  const refresh = () => { after && after(); claimDrawer(id, after); };
  $('#drawer-body').querySelectorAll('[data-act]').forEach((b) => b.onclick = async () => {
    const act = b.dataset.act, v = (x) => $(x)?.value;
    try {
      if (act === 'start-review') await api(`/api/claims/${id}/start-review`, { method: 'POST', body: { adjuster_id: +v('#wf-adj') } });
      if (act === 'approve') await api(`/api/claims/${id}/approve`, { method: 'POST', body: { adjuster_id: +v('#wf-adj'), amount: v('#wf-amt'), remarks: v('#wf-rem') } });
      if (act === 'approve-and-pay') await api(`/api/claims/${id}/approve-and-pay`, { method: 'POST', body: { adjuster_id: +v('#wf-adj'), amount: v('#wf-amt'), remarks: v('#wf-rem'), method: v('#wf-method') } });
      if (act === 'reject') await api(`/api/claims/${id}/reject`, { method: 'POST', body: { adjuster_id: +v('#wf-adj'), remarks: v('#wf-rem'), is_fraud: $('#wf-fraud').checked } });
      if (act === 'pay') await api(`/api/claims/${id}/pay`, { method: 'POST', body: { method: v('#wf-method') } });
      if (act === 'fraud-score') await api(`/api/claims/${id}/fraud-score`, { method: 'POST' });
      if (act === 'request-info') await api(`/api/claims/${id}/request-info`, { method: 'POST', body: { adjuster_id: +v('#wf-adj'), remarks: v('#wf-rem') } });
      if (act === 'flag' || act === 'unflag') {
        if (act === 'flag' && !confirm('Mark this claim as confirmed fraud? This label is used to train the model.')) return;
        await api(`/api/claims/${id}/flag-fraud`, { method: 'POST', body: { fraud_flag: act === 'flag' } });
      }
      if (act === 'add-doc') await api('/api/documents', { method: 'POST', body: { claim_id: id, doc_type: v('#doc-type'), file_name: v('#doc-name') || `${v('#doc-type').toLowerCase()}_${id}.pdf` } });
      toast('Done'); refresh();
    } catch (e) { showError(e); }
  });
}

// ---------------------------------------------------------------- policies (F2, F3)
function policiesScreen() {
  const lv = listView({
    title: 'Policies', sub: 'All policies with payment position. Click one for instalments, nominees and claims.',
    endpoint: '/api/policies', defaultSort: 'policy_id', defaultOrder: 'desc',
    filters: sel('status', ['ACTIVE', 'LAPSED', 'EXPIRED', 'CANCELLED'], 'All statuses') + sel('type_name', ['Health', 'Motor', 'Life', 'Home', 'Travel'], 'All products'),
    toolbarExtra: '<button class="primary" id="sell">+ Sell policy</button>',
    cols: [
      { key: 'policy_number', label: 'Policy' }, { key: 'status', label: 'Status', fmt: badge },
      { key: 'type_name', label: 'Product' }, { key: 'customer_name', label: 'Customer' },
      { key: 'sum_assured', label: 'Sum assured', fmt: inr, num: true }, { key: 'premium_amount', label: 'Instalment', fmt: inr, num: true },
      { key: 'start_date', label: 'Start', fmt: day }, { key: 'end_date', label: 'End', fmt: day },
      { key: 'overdue_instalments', label: 'Overdue', num: true, fmt: (v) => v > 0 ? badge('overdue').replace('overdue', v) : '0' },
      { key: 'claim_count', label: 'Claims', num: true },
    ],
    onRow: (r) => policyDrawer(r.policy_id, () => lv.reload()),
  });
  $('#sell').onclick = () => sellForm(() => lv.reload());
}

function sellForm(after) {
  openModal(`<h2 style="margin-top:0">Sell a policy</h2>
    <p class="muted"><code>sp_sell_policy</code> validates cover against the product range (trigger), computes the premium with an age loading, numbers the policy and raises the first instalment, all in one transaction.</p>
    <form id="sell-form" class="form-grid">
      <label>Customer ID<input name="customer_id" type="number" required></label>
      <label>Product<select name="type_id">${META.policy_types.map((t) => `<option value="${t.type_id}">${t.type_name} (${inr(t.min_sum_assured)}–${inr(t.max_sum_assured)})</option>`).join('')}</select></label>
      <label>Agent<select name="agent_id"><option value="">— direct —</option>${META.agents.map((a) => `<option value="${a.agent_id}">${esc(a.name)}</option>`).join('')}</select></label>
      <label>Start date<input name="start_date" type="date" value="${new Date().toISOString().slice(0, 10)}"></label>
      <label>Term (months)<input name="term_months" type="number" value="12"></label>
      <label>Sum assured (₹)<input name="sum_assured" type="number" value="500000"></label>
      <label>Payment frequency<select name="payment_frequency">${META.frequencies.map((f) => `<option ${f === 'ANNUAL' ? 'selected' : ''}>${f}</option>`).join('')}</select></label>
    </form>
    <div class="actions"><button onclick="closeModal()">Cancel</button><button class="primary" id="sell-save">Sell</button></div>`);
  $('#sell-save').onclick = async () => {
    try {
      const r = await api('/api/policies', { method: 'POST', body: formData($('#sell-form')) });
      closeModal(); toast(`Sold ${r.policy.policy_number}: instalment ${inr(r.policy.premium_amount)}`); after && after(); policyDrawer(r.policy.policy_id, after);
    } catch (e) { showError(e); }
  };
}

async function policyDrawer(id, after) {
  let d;
  try { d = await api(`/api/policies/${id}/detail`); } catch (e) { return showError(e); }
  const p = d.policy;
  const share = d.nominees.reduce((s, n) => s + Number(n.share_pct), 0);
  openDrawer(`
    <h1>${esc(p.policy_number)} ${badge(p.status)}</h1>
    <div class="sub">${esc(p.type_name)} · ${esc(p.customer_name)} (customer #${p.customer_id}) · agent ${esc(p.agent_name || '—')}</div>
    <div class="card"><dl class="kv">
      <dt>Period</dt><dd>${day(p.start_date)} to ${day(p.end_date)} (${p.days_to_expiry} days left)</dd>
      <dt>Sum assured</dt><dd>${inr(p.sum_assured)}</dd><dt>Instalment</dt><dd>${inr(p.premium_amount)} · ${esc(p.payment_frequency)}</dd>
      <dt>Premium paid</dt><dd>${inr(p.premium_paid)}</dd><dt>Overdue instalments</dt><dd>${p.overdue_instalments}</dd>
    </dl>
    <div class="actions" style="justify-content:flex-start"><button id="pol-claim">File claim on this policy</button></div></div>
    <h2>Premium instalments</h2>
    <p class="muted">Paying the last overdue instalment of a LAPSED policy re-activates it (BR9, trigger on premium_payment).</p>
    <div class="table-wrap"><table><tr><th class="nosort">#</th><th class="nosort">Due</th><th class="nosort num">Amount</th><th class="nosort">Status</th><th class="nosort">Paid on</th><th class="nosort"></th></tr>
      ${d.payments.map((x) => `<tr><td>${x.instalment_no}</td><td>${day(x.due_date)} ${x.is_overdue ? badge('overdue') : ''}</td><td class="num">${inr(x.amount)}</td>
        <td>${badge(x.status)}</td><td>${day(x.paid_on)}</td><td>${x.status !== 'PAID' ? `<button data-pay="${x.payment_id}">Pay</button>` : ''}</td></tr>`).join('')}</table></div>
    <h2>Nominees <span class="muted" style="font-weight:400">(${share}% allocated; BR8 caps at 100%)</span></h2>
    <div class="table-wrap"><table><tr><th class="nosort">Name</th><th class="nosort">Relationship</th><th class="nosort num">Share</th><th class="nosort"></th></tr>
      ${d.nominees.map((n) => `<tr><td>${esc(n.full_name)}</td><td>${esc(n.relationship)}</td><td class="num">${n.share_pct}%</td><td><button class="danger" data-delnom="${n.nominee_id}">Remove</button></td></tr>`).join('') || '<tr><td colspan=4 class="muted">None</td></tr>'}</table></div>
    <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap"><input id="nom-name" placeholder="Full name">
      <select id="nom-rel">${['SPOUSE', 'SON', 'DAUGHTER', 'FATHER', 'MOTHER', 'BROTHER', 'SISTER', 'OTHER'].map((r) => `<option>${r}</option>`).join('')}</select>
      <input id="nom-share" type="number" placeholder="Share %" style="width:90px"><button id="nom-add">Add nominee</button></div>
    <h2>Claims</h2>
    <div class="table-wrap"><table><tr><th class="nosort">Claim</th><th class="nosort">Type</th><th class="nosort">Filed</th><th class="nosort num">Claimed</th><th class="nosort">Status</th></tr>
      ${d.claims.map((c) => `<tr class="clickable" data-claim="${c.claim_id}"><td>${esc(c.claim_number)}</td><td>${esc(c.claim_type)}</td><td>${day(c.filed_on)}</td><td class="num">${inr(c.claimed_amount)}</td><td>${badge(c.status)}</td></tr>`).join('') || '<tr><td colspan=5 class="muted">None</td></tr>'}</table></div>`);
  const refresh = () => { after && after(); policyDrawer(id, after); };
  $('#pol-claim').onclick = () => claimForm(after, id);
  $('#drawer-body').querySelectorAll('[data-pay]').forEach((b) => b.onclick = async () => {
    try { const r = await api(`/api/payments/${b.dataset.pay}/pay`, { method: 'POST', body: { method: 'UPI' } }); toast(`Paid. Policy is now ${r.policy_status}`); refresh(); }
    catch (e) { showError(e); }
  });
  $('#drawer-body').querySelectorAll('[data-delnom]').forEach((b) => b.onclick = async () => {
    try { await api(`/api/nominees/${b.dataset.delnom}`, { method: 'DELETE' }); refresh(); } catch (e) { showError(e); }
  });
  $('#drawer-body').querySelectorAll('[data-claim]').forEach((tr) => tr.onclick = () => claimDrawer(+tr.dataset.claim, after));
  $('#nom-add').onclick = async () => {
    try {
      await api('/api/nominees', { method: 'POST', body: { policy_id: id, full_name: $('#nom-name').value, relationship: $('#nom-rel').value, share_pct: $('#nom-share').value } });
      refresh();
    } catch (e) { showError(e); }
  };
}

// ---------------------------------------------------------------- premiums (F3)
function premiumsScreen() {
  const lv = listView({
    title: 'Premium payments', sub: 'Overdue instalments, oldest first. Batch jobs run the lifecycle procedures.',
    endpoint: '/api/overdue', defaultSort: 'days_overdue', defaultOrder: 'desc',
    filters: sel('policy_status', ['ACTIVE', 'LAPSED'], 'Any policy status') + sel('type_name', ['Health', 'Motor', 'Life', 'Home', 'Travel'], 'All products'),
    toolbarExtra: `<button id="gen">Raise due instalments</button><button id="lapse">Lapse overdue (30-day grace)</button><button id="expire">Expire ended policies</button>`,
    cols: [
      { key: 'policy_number', label: 'Policy' }, { key: 'policy_status', label: 'Policy status', fmt: badge, nosort: true },
      { key: 'customer_name', label: 'Customer' }, { key: 'phone', label: 'Phone', nosort: true },
      { key: 'due_date', label: 'Due', fmt: day }, { key: 'amount', label: 'Amount', fmt: inr, num: true },
      { key: 'days_overdue', label: 'Days overdue', num: true },
      { key: 'payment_id', label: '', nosort: true, fmt: (v) => `<button data-pay="${v}">Record payment</button>` },
    ],
  });
  $('#lv-body').addEventListener('click', async (e) => {
    const b = e.target.closest('[data-pay]'); if (!b) return;
    try { const r = await api(`/api/payments/${b.dataset.pay}/pay`, { method: 'POST', body: { method: 'UPI' } }); toast(`Paid. Policy is now ${r.policy_status}`); lv.reload(); }
    catch (err) { showError(err); }
  });
  const job = (btn, path, msg) => $(btn).onclick = async () => {
    try { const r = await api(path, { method: 'POST' }); toast(msg(r)); lv.reload(); } catch (e) { showError(e); }
  };
  job('#gen', '/api/admin/generate-instalments', (r) => `sp_generate_instalments created ${r.instalments_created} instalment(s)`);
  job('#lapse', '/api/admin/lapse-overdue', (r) => `sp_lapse_overdue_policies lapsed ${r.policies_lapsed} policies`);
  job('#expire', '/api/admin/expire-policies', (r) => `sp_expire_policies expired ${r.policies_expired} policies`);
}

// ---------------------------------------------------------------- reports (F8)
async function reportsScreen() {
  main().innerHTML = '<h1>Reports</h1><div class="sub">Each report is one SQL query over the views. Download any as CSV.</div><div class="toolbar" id="rep-tabs"></div><div id="rep-body"></div>';
  const list = await api('/api/reports');
  $('#rep-tabs').innerHTML = list.map((r) => `<button data-rep="${r.name}">${esc(r.title)}</button>`).join('');
  const show = async (name) => {
    main().querySelectorAll('[data-rep]').forEach((b) => b.classList.toggle('primary', b.dataset.rep === name));
    try {
      const r = await api(`/api/reports/${name}`);
      const cols = r.rows.length ? Object.keys(r.rows[0]) : [];
      const money = /amount|premium|paid|claimed|commission_earned|sum_assured|cover/;
      $('#rep-body').innerHTML = `<div class="toolbar"><h2 style="margin:0">${esc(r.title)}</h2><span class="muted">${r.rows.length} rows</span><span class="spacer"></span>
        <a class="btn" href="/api/reports/${name}?format=csv">Download CSV</a></div>
        <div class="table-wrap"><table><tr>${cols.map((c) => `<th class="nosort">${esc(c)}</th>`).join('')}</tr>
        ${r.rows.slice(0, 200).map((row) => `<tr>${cols.map((c) => {
          const v = row[c]; const isNum = typeof v === 'number' || (v !== null && v !== '' && !isNaN(v) && !/date|month|_on|number|phone/.test(c));
          return `<td class="${isNum ? 'num' : ''}">${money.test(c) && !/pct|rate|claims$/.test(c) ? inr(v) : /status|band|network/.test(c) && v ? badge(v) : esc(v ?? '—')}</td>`;
        }).join('')}</tr>`).join('')}</table></div>`;
    } catch (e) { showError(e); }
  };
  main().querySelectorAll('[data-rep]').forEach((b) => b.onclick = () => show(b.dataset.rep));
  show(list[0].name);
}

// ---------------------------------------------------------------- fraud model (F7)
async function fraudScreen() {
  main().innerHTML = '<h1>Fraud model</h1><div class="sub">Claim fraud classifier trained on resolved claims (ml/train.py).</div><div id="ml">Loading…</div>';
  try {
    const m = await api('/api/fraud/model');
    const t = m.test, cm = t.confusion_matrix;
    $('#ml').innerHTML = `
      <div class="note">${esc(m.note)}</div>
      <div class="kpis">
        <div class="kpi"><div class="label">Selected model</div><div class="value" style="font-size:17px">${esc(m.selected_model)}</div></div>
        <div class="kpi"><div class="label">Test ROC-AUC</div><div class="value">${t.roc_auc.toFixed(3)}</div></div>
        <div class="kpi"><div class="label">Test PR-AUC</div><div class="value">${t.pr_auc.toFixed(3)}</div></div>
        <div class="kpi"><div class="label">Precision / recall</div><div class="value">${t.precision.toFixed(2)} / ${t.recall.toFixed(2)}</div></div>
        <div class="kpi"><div class="label">F1 at threshold ${m.threshold.toFixed(2)}</div><div class="value">${t.f1.toFixed(3)}</div></div>
        <div class="kpi"><div class="label">Fraud base rate (test)</div><div class="value">${pct(100 * t.base_rate)}</div></div>
      </div>
      <div class="grid2" style="margin-top:16px">
        <div class="card"><h2>Model comparison (5-fold CV ROC-AUC on train split)</h2>
          <div class="table-wrap"><table><tr><th class="nosort">Model</th><th class="nosort num">Mean</th><th class="nosort num">Std</th></tr>
          ${Object.entries(m.cv).map(([k, v]) => `<tr><td>${esc(k)} ${k === m.selected_model ? badge('ACTIVE').replace('ACTIVE', 'selected') : ''}</td><td class="num">${v.cv_roc_auc_mean.toFixed(4)}</td><td class="num">${v.cv_roc_auc_std.toFixed(4)}</td></tr>`).join('')}</table></div>
          <p class="muted">Train ${m.n_train} · test ${m.n_test} · ${m.n_positive} confirmed fraud of ${m.n_resolved} resolved claims. Threshold chosen from out-of-fold predictions, never from the test set.</p>
          <h3>Confusion matrix (test)</h3>
          <dl class="kv"><dt>True negatives</dt><dd>${cm.tn}</dd><dt>False positives</dt><dd>${cm.fp}</dd><dt>False negatives</dt><dd>${cm.fn}</dd><dt>True positives</dt><dd>${cm.tp}</dd></dl>
        </div>
        <div class="card"><h2>Permutation importance</h2>${barChart(m.permutation_importance.slice(0, 8), 'feature', 'importance', { fmt: (v) => v.toFixed(3), color: '#5a7ca8', height: 200 })}
          <p class="muted">Drop in test ROC-AUC when each feature is shuffled.</p></div>
      </div>
      <h2>Charts</h2>
      <div class="ml-imgs">${m.charts.map((c) => `<img src="/ml-assets/${c}?t=${encodeURIComponent(m.trained_at)}" alt="${c}">`).join('')}</div>
      <p class="muted">Trained ${esc(m.trained_at)}.</p>`;
  } catch (e) { $('#ml').innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
}

// ---------------------------------------------------------------- router
const ROUTES = {
  dashboard, claims: claimsScreen, policies: policiesScreen, premiums: premiumsScreen, reports: reportsScreen, fraud: fraudScreen,
  customers: () => crudScreen('customers'), agents: () => crudScreen('agents'), providers: () => crudScreen('providers'),
  adjusters: () => crudScreen('adjusters'), 'policy-types': () => crudScreen('policy-types'),
  pincodes: () => crudScreen('pincodes'),
};

async function route() {
  const view = location.hash.slice(1) || 'dashboard';
  document.querySelectorAll('#nav a').forEach((a) => a.classList.toggle('active', a.dataset.view === view));
  $('#nav .menu').classList.toggle('active', !!$('#nav .menu-items a.active'));
  document.activeElement?.blur();  // close the dropdown after picking an item
  closeDrawer(); closeModal();
  if (!META) { try { META = await api('/api/meta'); } catch (e) { showError(e); } }
  (ROUTES[view] || dashboard)();
}
window.addEventListener('hashchange', route);
route();
