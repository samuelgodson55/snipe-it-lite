// =============================================================================
// js/components/audit.js
// -----------------------------------------------------------------------------
// Audit Trail table + the "Export Audit Ledger CSV" action. The export is
// the one place the frontend needs a raw (non-JSON) authenticated fetch, so
// it uses `API_URL` + the session token directly rather than `apiRequest`
// (which assumes a JSON or passthrough-Response result, not a file download).
//
// PAGINATION NOTE (Data Quality & Usability requirement #4): the audit
// ledger is genuinely unbounded (it's an append-only log that grows for
// the entire lifetime of the system), so this file does TRUE server-side
// pagination: every page turn or "rows per page" change re-fetches just
// that slice from `GET /audit-logs?limit=&offset=`. `auditState` below is
// this file's own tiny bit of state (page number + rows-per-page +
// last-known total) -- it's intentionally NOT wired into js/ui.js's
// client-side `tableState`/`filterAndPaginate` machinery, since that
// machinery assumes the full dataset is already sitting in the browser,
// which is exactly what we're avoiding here.
//
// This is now the same pattern used by the Asset/User/Outsider
// directories (see components/assets.js, components/users.js,
// components/outsiders.js) -- `renderServerPaginationBar()` in js/ui.js is
// the bit all four of these files share.
// =============================================================================

import { apiRequest, API_URL } from '../api.js';
import { getSession } from '../auth.js';
import { escapeHtml, renderServerPaginationBar } from '../ui.js';

const auditState = { page: 1, perPage: 10, total: 0 };

export async function loadAuditLogs() {
  const tbody = document.getElementById('auditTableBody');
  if (!tbody) return;
  try {
    const offset = (auditState.page - 1) * auditState.perPage;
    const result = await apiRequest(`/audit-logs?limit=${auditState.perPage}&offset=${offset}`);
    auditState.total = result.total;

    tbody.innerHTML = result.items.map(l => `
    <tr>
      <td class="px-5 py-2.5 whitespace-nowrap">${escapeHtml(l.timestamp)}</td>
      <td class="px-5 py-2.5">${escapeHtml(l.operator)}</td>
      <td class="px-5 py-2.5"><span class="rounded bg-blue-500/10 px-1.5 py-0.5 text-blue-400 ring-1 ring-blue-500/30">${escapeHtml(l.action)}</span></td>
      <td class="px-5 py-2.5 text-slate-500">${escapeHtml(l.details)}</td>
    </tr>`).join('') || `<tr><td colspan="4" class="px-5 py-6 text-center text-slate-500">No log entries yet.</td></tr>`;

    renderServerPaginationBar('audit', auditState);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" class="px-5 py-6 text-center text-rose-400">${escapeHtml(err.message)}</td></tr>`;
  }
}

// Called by main.js's delegated click handler when Prev/Next is clicked.
export function changeAuditPage(delta) {
  const nextPage = auditState.page + delta;
  if (nextPage < 1) return;
  auditState.page = nextPage;
  loadAuditLogs();
}

// Called by main.js's delegated change handler when "Rows per page" changes.
export function setAuditPerPage(value) {
  auditState.perPage = parseInt(value, 10) || 10;
  auditState.page = 1; // changing page size always resets back to page 1
  loadAuditLogs();
}

// ---- Export Audit Ledger (CSV or PDF) ----
// Prompts the user for an optional start/end date range before exporting,
// and forwards them to GET /audit-logs/export?format=&start_date=&end_date=.
// This intentionally bypasses auditState/limit/offset entirely -- exporting
// "everything in this date range" is a different operation from paging
// through the UI. The CSV branch streams row-by-row on the backend (see
// services/audit_service.py); the PDF branch is built as one file, so both
// share this same "narrow it to a date range first" prompt flow.
export async function exportAuditLogs(format = 'csv') {
  try {
    const startDate = prompt('Export from which date? (YYYY-MM-DD, leave blank for "no start limit")', '');
    if (startDate === null) return; // user clicked Cancel -- abort the export entirely
    const endDate = prompt('Export up to which date? (YYYY-MM-DD, leave blank for "no end limit")', '');
    if (endDate === null) return;

    const params = new URLSearchParams();
    if (startDate.trim()) params.set('start_date', startDate.trim());
    if (endDate.trim()) params.set('end_date', endDate.trim());
    params.set('format', format);
    const query = `?${params.toString()}`;

    const session = getSession();
    const response = await fetch(`${API_URL}/audit-logs/export${query}`, {
      headers: { 'Authorization': `Bearer ${session.token}` },
    });
    if (!response.ok) throw new Error('Export failed. Check the date format (YYYY-MM-DD) and try again.');
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `audit_export_${new Date().toISOString().slice(0, 10)}.${format}`;
    a.click();
    window.URL.revokeObjectURL(url);
  } catch (err) {
    alert(err.message);
  }
}
