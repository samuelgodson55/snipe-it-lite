// =============================================================================
// js/components/outsiders.js
// -----------------------------------------------------------------------------
// Ad-Hoc (Unlinked) Directory table -- external individuals who've had
// assets dispatched to them without a full system user account. Custody
// Ledger for these rows is handled by components/custody.js (same modal
// used for Users, just with entityType='outsider').
// =============================================================================

import { apiRequest } from '../api.js';
import { escapeHtml, tableState, registerRenderer, filterAndPaginate, renderPaginationBar } from '../ui.js';

export async function loadOutsiders() {
  const tbody = document.getElementById('outsiderTableBody');
  if (!tbody) return; // this page doesn't have an ad-hoc directory table
  try {
    // GET /outsiders now returns a paginated envelope --
    // { items, total, limit, offset } -- instead of a bare array (Data
    // Quality & Usability requirement #4). A generous limit keeps the
    // existing client-side search/pagination behaving as before for
    // realistic dataset sizes, while the backend still enforces a hard cap.
    const result = await apiRequest('/outsiders?limit=1000');
    tableState.outsiders.raw = result.items;
    renderOutsidersTable();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" class="px-5 py-6 text-center text-rose-400">${escapeHtml(err.message)}</td></tr>`;
  }
}

export function renderOutsidersTable() {
  const tbody = document.getElementById('outsiderTableBody');
  if (!tbody) return;

  const { pageRows, total, startIndex } = filterAndPaginate('outsiders', ['name', 'contact_details', 'company']);
  document.querySelectorAll('.outsider-count').forEach(el => el.textContent = total);

  tbody.innerHTML = pageRows.map(o => {
    const initials = o.name.split(' ').map(p => p[0]).join('').slice(0, 2).toUpperCase();
    return `
    <tr class="transition hover:bg-card2/40">
      <td class="px-5 py-3.5">
        <div class="flex items-center gap-3">
          <div class="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-amber-500 to-orange-600 text-[11px] font-bold text-white">${initials}</div>
          <div>
            <p class="font-medium text-slate-100">${escapeHtml(o.name)}</p>
            <p class="tag-mono text-[11px] text-slate-500">${escapeHtml(o.contact_details)}</p>
          </div>
        </div>
      </td>
      <td class="px-5 py-3.5 text-slate-300">${escapeHtml(o.company || '—')}</td>
      <td class="px-5 py-3.5 tag-mono text-slate-300">${o.outstanding_items} item${o.outstanding_items === 1 ? '' : 's'} checked out</td>
      <td class="px-5 py-3.5">
        <div class="flex justify-end gap-2">
          <button data-action="open-custody" data-entity-id="${o.id}" data-entity-type="outsider" class="rounded-md border border-border px-2.5 py-1.5 text-[12px] font-medium text-slate-300 transition hover:border-blue-500/50 hover:text-blue-400">Custody Ledger</button>
        </div>
      </td>
    </tr>`;
  }).join('') || `<tr><td colspan="4" class="px-5 py-6 text-center text-slate-500">No ad-hoc individuals on file yet.</td></tr>`;

  renderPaginationBar('outsiders', total, startIndex, pageRows.length);
}
registerRenderer('outsiders', renderOutsidersTable);
