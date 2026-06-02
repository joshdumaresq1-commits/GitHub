/* Finance Tracker - Review Queue JS */

const API = '';
let transactions = [];
let categories = [];
let reviewedCount = 0;
let totalCount = 0;
let changedCount = 0;

async function init() {
  await loadCategories();
  await loadQueue();
  setupBulkActions();
}

async function loadCategories() {
  try {
    const data = await fetchJSON('/api/categories');
    categories = data;
  } catch (e) {
    console.error('loadCategories:', e);
  }
}

async function loadQueue() {
  try {
    const data = await fetchJSON('/api/review-queue');
    transactions = data.transactions;
    totalCount = data.total;
    reviewedCount = 0;
    renderQueue();
    updateProgress();
  } catch (e) {
    document.getElementById('review-list').innerHTML =
      '<p style="color:var(--red);text-align:center;">Error loading review queue.</p>';
  }
}

function renderQueue() {
  const list = document.getElementById('review-list');

  if (!transactions.length) {
    showComplete();
    return;
  }

  // Sort: uncategorized first, then by confidence asc
  const sorted = [...transactions].sort((a, b) => {
    if (!a.category && b.category) return -1;
    if (a.category && !b.category) return 1;
    return a.confidence - b.confidence;
  });

  const catOptions = categories.map(c => `<option value="${c.name}">${c.name}</option>`).join('');

  list.innerHTML = sorted.map((t, idx) => {
    const conf = t.confidence;
    const confPct = conf + '%';
    const confColor = conf >= 85 ? 'var(--green)' : conf >= 70 ? 'var(--orange)' : 'var(--red)';
    const isExpense = t.amount > 0;
    const amtDisplay = (isExpense ? '+' : '-') + fmtCurrency(Math.abs(t.amount / 100));
    const amtColor = isExpense ? 'var(--red)' : 'var(--green)';
    const cardClass = !t.category ? 'uncategorized' : conf < 70 ? 'low-confidence' : '';
    const catColor = (categories.find(c => c.name === t.category) || {}).color || '#9e9e9e';

    return `
    <div class="review-card ${cardClass}" id="card-${t.id}" data-id="${t.id}" data-conf="${conf}" data-original-cat="${t.category || ''}">
      <div class="review-card-top">
        <div class="review-card-meta">
          <div class="review-card-date">${t.date} · ${t.source === 'gmail' ? '📧 Gmail' : '📄 PDF'}</div>
          <div class="review-card-desc">${escHtml(t.description)}</div>
          <div class="review-card-account">${t.account || ''} ${t.account_type ? '(' + t.account_type + ')' : ''}</div>
        </div>
        <div class="review-card-amount" style="color:${amtColor}">${amtDisplay}</div>
      </div>

      <div class="confidence-bar">
        <span class="conf-label" style="color:${confColor}">${t.category || 'Uncategorized'}</span>
        <div class="conf-track">
          <div class="conf-fill" style="width:${confPct};background:${confColor}"></div>
        </div>
        <span style="color:${confColor};font-weight:600;min-width:36px;text-align:right">${conf}%</span>
      </div>

      <div class="review-card-actions">
        <button class="btn btn-success btn-sm" onclick="approveCard(${t.id})">✓ Approve</button>
        <button class="btn btn-primary btn-sm" onclick="toggleEdit(${t.id})">✎ Edit</button>
        <select class="cat-edit-select" id="cat-sel-${t.id}">
          ${catOptions}
        </select>
        <button class="btn btn-sm" style="background:#e8eaf6;color:var(--navy);display:none" id="save-btn-${t.id}" onclick="saveEdit(${t.id})">Save</button>
      </div>
    </div>`;
  }).join('');

  // Set current category in selects
  for (const t of sorted) {
    const sel = document.getElementById(`cat-sel-${t.id}`);
    if (sel && t.category) {
      for (const opt of sel.options) {
        if (opt.value === t.category) { opt.selected = true; break; }
      }
    }
  }
}

function toggleEdit(txId) {
  const sel = document.getElementById(`cat-sel-${txId}`);
  const saveBtn = document.getElementById(`save-btn-${txId}`);
  if (!sel) return;
  const isOpen = sel.style.display === 'inline-block';
  sel.style.display = isOpen ? 'none' : 'inline-block';
  if (saveBtn) saveBtn.style.display = isOpen ? 'none' : 'inline-block';
}

async function approveCard(txId) {
  const card = document.getElementById(`card-${txId}`);
  const cat = card.dataset.originalCat || 'Other';
  await patchTransaction(txId, cat, true);
  markReviewed(card);
}

async function saveEdit(txId) {
  const sel = document.getElementById(`cat-sel-${txId}`);
  const newCat = sel ? sel.value : '';
  if (!newCat) return;
  await patchTransaction(txId, newCat, true);
  const card = document.getElementById(`card-${txId}`);
  card.dataset.originalCat = newCat;
  // Update display
  const confLabel = card.querySelector('.conf-label');
  if (confLabel) confLabel.textContent = newCat;
  changedCount++;
  markReviewed(card);
}

function markReviewed(card) {
  card.classList.add('reviewed');
  card.classList.remove('uncategorized', 'low-confidence');
  // Disable buttons
  card.querySelectorAll('button').forEach(b => { b.disabled = true; b.style.opacity = '0.5'; });
  reviewedCount++;
  updateProgress();
  if (reviewedCount >= totalCount) showComplete();
}

function updateProgress() {
  const pct = totalCount > 0 ? Math.round(reviewedCount / totalCount * 100) : 0;
  document.getElementById('progress-fill').style.width = pct + '%';
  document.getElementById('progress-label').textContent = `${reviewedCount} of ${totalCount} reviewed`;
  document.getElementById('review-subtitle').textContent =
    `${totalCount - reviewedCount} transactions remaining to review`;
}

async function patchTransaction(txId, category, isReviewed) {
  try {
    await fetch(`${API}/api/transactions/${txId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ category, is_reviewed: isReviewed }),
    });
  } catch (e) {
    console.error('patchTransaction:', e);
  }
}

function setupBulkActions() {
  document.getElementById('bulk-approve-btn').addEventListener('click', async () => {
    const btn = document.getElementById('bulk-approve-btn');
    btn.disabled = true;
    const status = document.getElementById('action-status');
    status.textContent = 'Approving high-confidence transactions…';

    const cards = document.querySelectorAll('.review-card:not(.reviewed)');
    let count = 0;
    const promises = [];
    for (const card of cards) {
      const conf = parseInt(card.dataset.conf || '0', 10);
      if (conf >= 85) {
        const txId = parseInt(card.dataset.id, 10);
        const cat = card.dataset.originalCat || 'Other';
        promises.push(patchTransaction(txId, cat, true).then(() => { markReviewed(card); count++; }));
      }
    }
    await Promise.all(promises);
    status.textContent = `Approved ${count} high-confidence transactions.`;
    btn.disabled = false;
    if (reviewedCount >= totalCount) showComplete();
  });

  document.getElementById('approve-all-btn').addEventListener('click', async () => {
    const btn = document.getElementById('approve-all-btn');
    btn.disabled = true;
    const status = document.getElementById('action-status');
    status.textContent = 'Approving all remaining…';

    const cards = document.querySelectorAll('.review-card:not(.reviewed)');
    const promises = [];
    for (const card of cards) {
      const txId = parseInt(card.dataset.id, 10);
      const cat = card.dataset.originalCat || 'Other';
      promises.push(patchTransaction(txId, cat, true).then(() => markReviewed(card)));
    }
    await Promise.all(promises);
    status.textContent = 'All transactions approved.';
    btn.disabled = false;
    showComplete();
  });
}

function showComplete() {
  document.getElementById('review-list').classList.add('hidden');
  document.getElementById('review-complete').classList.remove('hidden');
  document.getElementById('complete-summary').textContent =
    `Reviewed ${reviewedCount} transaction${reviewedCount !== 1 ? 's' : ''}. ` +
    (changedCount > 0 ? `${changedCount} categor${changedCount !== 1 ? 'ies' : 'y'} updated.` : 'No changes made.');
}

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
