/* Finance Tracker - Dashboard JS */

const API = '';  // same origin
let currentMonth = '';
let barChart = null;
let doughnutChart = null;
let allCategories = [];

// ── Init ──────────────────────────────────────────────────────────────────────

async function init() {
  populateMonthSelector();
  await loadCategories();
  await Promise.all([
    loadSummary(),
    loadMonthlyChart(),
    loadBudgetBars(),
    loadTransactions(),
    loadReviewCount(),
  ]);
  setupUpload();
  setupGmailSync();
}

function populateMonthSelector() {
  const sel = document.getElementById('month-select');
  const now = new Date();
  for (let i = 0; i < 12; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const val = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    if (val < '2026-01') break;
    const label = d.toLocaleString('default', { month: 'long', year: 'numeric' });
    const opt = document.createElement('option');
    opt.value = val;
    opt.textContent = label;
    if (i === 0) {
      opt.selected = true;
      currentMonth = val;
    }
    sel.appendChild(opt);
  }
  sel.addEventListener('change', async () => {
    currentMonth = sel.value;
    document.getElementById('doughnut-month-label').textContent = sel.options[sel.selectedIndex].text;
    await Promise.all([loadSummary(), loadBudgetBars(), loadTransactions(), loadDoughnutChart()]);
  });
  document.getElementById('doughnut-month-label').textContent =
    now.toLocaleString('default', { month: 'long', year: 'numeric' });
}

// ── Data loaders ──────────────────────────────────────────────────────────────

async function loadCategories() {
  try {
    const data = await fetchJSON(`/api/categories?month=${currentMonth}`);
    allCategories = data;

    const sel = document.getElementById('filter-category');
    // Clear old options (keep first)
    while (sel.options.length > 1) sel.remove(1);
    for (const c of data) {
      const opt = document.createElement('option');
      opt.value = c.name;
      opt.textContent = c.name;
      sel.appendChild(opt);
    }
  } catch (e) {
    console.error('loadCategories:', e);
  }
}

async function loadSummary() {
  try {
    const data = await fetchJSON(`/api/summary?month=${currentMonth}`);
    document.getElementById('total-income').textContent = fmtCurrency(data.total_income / 100);
    document.getElementById('regular-income').textContent = fmtCurrency(data.regular_income / 100);
    document.getElementById('gifts-income').textContent = fmtCurrency(data.gifts_income / 100);
    document.getElementById('insurance-income').textContent = fmtCurrency(data.insurance_income / 100);
    document.getElementById('total-savings').textContent = fmtCurrency(data.total_savings / 100);
    document.getElementById('total-expenses').textContent = fmtCurrency(data.total_expenses / 100);
    const netEl = document.getElementById('net-savings');
    const netVal = data.net_savings / 100;
    netEl.textContent = (netVal < 0 ? '-' : '') + fmtCurrency(Math.abs(netVal));
    netEl.className = `card-value ${netVal >= 0 ? 'savings' : 'expense'}`;
    document.getElementById('savings-rate').textContent = `${data.savings_rate}%`;
  } catch (e) {
    console.error('loadSummary:', e);
  }
}

async function loadMonthlyChart() {
  try {
    const data = await fetchJSON('/api/summary/monthly?months=5');
    renderBarChart(data);
    await loadDoughnutChart();
  } catch (e) {
    console.error('loadMonthlyChart:', e);
  }
}

async function loadDoughnutChart() {
  try {
    const cats = await fetchJSON(`/api/categories?month=${currentMonth}`);
    renderDoughnutChart(cats.filter(c => c.spent > 0));
  } catch (e) {
    console.error('loadDoughnutChart:', e);
  }
}

async function loadBudgetBars() {
  try {
    const cats = await fetchJSON(`/api/categories?month=${currentMonth}`);
    renderBudgetBars(cats);
  } catch (e) {
    console.error('loadBudgetBars:', e);
  }
}

async function loadTransactions() {
  const tbody = document.getElementById('transactions-tbody');
  tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:20px;color:var(--text-secondary)">Loading…</td></tr>';

  const catFilter = document.getElementById('filter-category').value;
  let url = `/api/transactions?month=${currentMonth}&limit=2000`;
  if (catFilter) url += `&category=${encodeURIComponent(catFilter)}`;

  try {
    const data = await fetchJSON(url);
    renderTransactions(data.transactions);
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--red)">Error loading transactions</td></tr>';
  }
}

async function loadReviewCount() {
  try {
    const data = await fetchJSON('/api/review-queue');
    const badge = document.getElementById('review-badge');
    badge.textContent = data.total;
    badge.style.display = data.total > 0 ? '' : 'none';
  } catch (e) {
    console.error('loadReviewCount:', e);
  }
}

// ── Render functions ──────────────────────────────────────────────────────────

function renderBarChart(monthlyData) {
  const ctx = document.getElementById('bar-chart').getContext('2d');

  // Collect top categories
  const catTotals = {};
  for (const m of monthlyData) {
    for (const [cat, val] of Object.entries(m.by_category || {})) {
      if (val > 0) catTotals[cat] = (catTotals[cat] || 0) + val;
    }
  }

  // Pick top 6 categories
  const topCats = Object.entries(catTotals)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
    .map(e => e[0]);

  const labels = monthlyData.map(m => {
    const [y, mo] = m.month.split('-');
    return new Date(+y, +mo - 1, 1).toLocaleString('default', { month: 'short' });
  });

  const catColors = {};
  for (const c of allCategories) catColors[c.name] = c.color;

  const datasets = topCats.map(cat => ({
    label: cat,
    data: monthlyData.map(m => ((m.by_category || {})[cat] || 0) / 100),
    backgroundColor: catColors[cat] || '#9e9e9e',
    borderRadius: 4,
    borderSkipped: false,
  }));

  if (barChart) barChart.destroy();
  barChart = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } } },
      scales: {
        x: { stacked: true, grid: { display: false } },
        y: {
          stacked: true,
          ticks: { callback: v => '$' + v.toLocaleString() },
          grid: { color: '#f0f0f0' },
        },
      },
    },
  });
}

function renderDoughnutChart(cats) {
  const ctx = document.getElementById('doughnut-chart').getContext('2d');

  const labels = cats.map(c => c.name);
  const data = cats.map(c => c.spent / 100);
  const colors = cats.map(c => c.color);

  if (doughnutChart) doughnutChart.destroy();
  doughnutChart = new Chart(ctx, {
    type: 'doughnut',
    data: { labels, datasets: [{ data, backgroundColor: colors, borderWidth: 2, borderColor: '#fff' }] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '62%',
      plugins: {
        legend: { position: 'right', labels: { boxWidth: 12, font: { size: 11 }, padding: 10 } },
        tooltip: {
          callbacks: {
            label: ctx => ` ${ctx.label}: $${ctx.raw.toLocaleString('en-CA', { minimumFractionDigits: 2 })}`,
          },
        },
      },
    },
  });
}

function renderBudgetBars(cats) {
  const grid = document.getElementById('budget-grid');
  const withBudget = cats.filter(c => c.budget_monthly && c.budget_monthly > 0);

  if (!withBudget.length) {
    grid.innerHTML = '<p class="text-muted text-sm">No budget categories configured.</p>';
    return;
  }

  grid.innerHTML = withBudget.map(c => {
    const pct = Math.min(100, c.percent || 0);
    const over = (c.percent || 0) > 100;
    const fillColor = over ? 'var(--red)' : c.color;
    return `
    <div class="budget-item">
      <div class="budget-label">
        <span class="budget-name">
          <span class="budget-dot" style="background:${c.color}"></span>
          ${c.name}
        </span>
        <span class="budget-amounts">
          ${fmtCurrency(c.spent_display)} / ${fmtCurrency(c.budget_display)}
          ${over ? ' <strong style="color:var(--red)">Over!</strong>' : ''}
        </span>
      </div>
      <div class="budget-bar-track">
        <div class="budget-bar-fill ${over ? 'over' : ''}" style="width:${pct}%;background:${fillColor}"></div>
      </div>
    </div>`;
  }).join('');
}

function renderTransactions(txns) {
  const tbody = document.getElementById('transactions-tbody');

  if (!txns.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:30px;color:var(--text-secondary)">No transactions for this period. Upload a bank statement to get started.</td></tr>';
    return;
  }

  const catOptions = allCategories.map(c => `<option value="${c.name}">${c.name}</option>`).join('');

  tbody.innerHTML = txns.map(t => {
    const isExpense = t.amount > 0;
    const amtClass = isExpense ? 'amount-positive' : 'amount-negative';
    const amtStr = (isExpense ? '+' : '-') + fmtCurrency(Math.abs(t.amount_display));
    const catColor = (allCategories.find(c => c.name === t.category) || {}).color || '#9e9e9e';

    return `
    <tr>
      <td style="white-space:nowrap">${t.date}</td>
      <td style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(t.description)}">${escHtml(t.description)}</td>
      <td style="font-size:0.78rem;color:var(--text-secondary)">${t.account || '—'}</td>
      <td>
        <select class="cat-select" data-id="${t.id}" style="border:none;background:transparent;font-weight:600;color:${catColor}">
          <option value="">${t.category || '(none)'}</option>
          ${catOptions}
        </select>
      </td>
      <td class="${amtClass}" style="text-align:right;white-space:nowrap">${amtStr}</td>
    </tr>`;
  }).join('');

  // Attach category change handlers
  tbody.querySelectorAll('.cat-select').forEach(sel => {
    sel.addEventListener('change', async () => {
      const txId = sel.dataset.id;
      const newCat = sel.value;
      await updateTransactionCategory(txId, newCat);
      const color = (allCategories.find(c => c.name === newCat) || {}).color || '#9e9e9e';
      sel.style.color = color;
    });
  });
}

// ── Actions ───────────────────────────────────────────────────────────────────

async function updateTransactionCategory(txId, category) {
  try {
    await fetch(`${API}/api/transactions/${txId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ category, is_reviewed: true }),
    });
  } catch (e) {
    console.error('updateTransactionCategory:', e);
  }
}

function setupGmailSync() {
  document.getElementById('sync-gmail-btn').addEventListener('click', async () => {
    const btn = document.getElementById('sync-gmail-btn');
    const original = btn.innerHTML;
    btn.innerHTML = '<span class="spinner"></span> Syncing…';
    btn.disabled = true;

    try {
      const res = await fetch(`${API}/api/gmail/sync`, { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        alert(data.message || 'Gmail sync complete');
        await Promise.all([loadSummary(), loadBudgetBars(), loadTransactions(), loadReviewCount()]);
      } else {
        alert(`Gmail sync error: ${data.detail || 'Unknown error'}`);
      }
    } catch (e) {
      alert(`Network error: ${e.message}`);
    } finally {
      btn.innerHTML = original;
      btn.disabled = false;
    }
  });
}

function setupUpload() {
  const zone = document.getElementById('upload-zone');
  const input = document.getElementById('file-input');
  const result = document.getElementById('upload-result');

  zone.addEventListener('click', () => input.click());

  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  });

  input.addEventListener('change', () => {
    if (input.files[0]) uploadFile(input.files[0]);
  });

  async function uploadFile(file) {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      showResult('error', 'Only PDF files are supported');
      return;
    }

    zone.innerHTML = `<div class="loading-overlay"><div class="spinner" style="border-color:rgba(0,0,0,0.15);border-top-color:var(--blue);"></div> Uploading and parsing ${escHtml(file.name)}…</div>`;

    const form = new FormData();
    form.append('file', file);

    try {
      const res = await fetch(`${API}/api/upload`, { method: 'POST', body: form });
      const data = await res.json();

      // Restore upload zone
      zone.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><polyline points="14 2 14 8 20 8" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><line x1="12" y1="18" x2="12" y2="12" stroke-width="1.5" stroke-linecap="round"/><polyline points="9 15 12 12 15 15" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <p><strong>Click to upload</strong> or drag & drop a PDF bank statement</p>
        <p class="mt-4" style="font-size:0.8rem;">Supports: RBC, Scotiabank, CIBC, BMO, Amex</p>`;

      if (data.success) {
        showResult('success', `✓ ${data.message} (Bank detected: ${data.bank})`);
        await Promise.all([loadSummary(), loadBudgetBars(), loadTransactions(), loadReviewCount()]);
      } else {
        showResult('error', data.message || 'Upload failed');
      }
    } catch (e) {
      zone.innerHTML = `<p><strong>Click to upload</strong> or drag & drop</p>`;
      showResult('error', `Upload error: ${e.message}`);
    }
  }

  function showResult(type, msg) {
    result.className = `upload-result ${type}`;
    result.textContent = msg;
    result.style.display = 'block';
    setTimeout(() => { result.style.display = 'none'; }, 6000);
  }
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function fmtCurrency(n) {
  return '$' + Math.abs(n || 0).toLocaleString('en-CA', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function escHtml(str) {
  return (str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

document.addEventListener('DOMContentLoaded', init);
