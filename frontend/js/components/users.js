// =============================================================================
// js/components/users.js
// -----------------------------------------------------------------------------
// "User Directory" / "Team Allocation Matrix" table, Delete Profile action,
// and the Provision System User Account form.
// =============================================================================

import { apiRequest } from '../api.js';
import { getSession } from '../auth.js';
import { escapeHtml, tableState, registerRenderer, filterAndPaginate, renderPaginationBar } from '../ui.js';
import { refreshDashboard } from '../dashboard.js';

// ---- User Directory / Team Allocation Matrix table ----
export async function loadUsers() {
  const tbody = document.getElementById('userTableBody');
  if (!tbody) return;
  try {
    // GET /users now returns a paginated envelope --
    // { items, total, limit, offset } -- instead of a bare array (Data
    // Quality & Usability requirement #4). A generous limit keeps the
    // existing client-side search/pagination (js/ui.js's
    // filterAndPaginate()) behaving exactly as before for realistic
    // directory sizes, while the backend still enforces a hard cap.
    const result = await apiRequest('/users?limit=1000');
    const users = result.items;
    tableState.users.raw = users;
    renderUsersTable();

    // Also populate the "Assign To > Staff Member" dropdown in the dispatch
    // drawer. This ALWAYS uses the full unfiltered list (not the paginated
    // page), because it's a dropdown of dispatch targets, not a table to
    // page through -- filtering/paginating it would hide valid recipients.
    const staffSelect = document.getElementById('staffSelect');
    if (staffSelect) {
      staffSelect.innerHTML = users.map(u => `<option value="${u.id}">${escapeHtml(u.name)} (${escapeHtml(u.department_role || u.role)})</option>`).join('');
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" class="px-5 py-6 text-center text-rose-400">${escapeHtml(err.message)}</td></tr>`;
  }
}

export function renderUsersTable() {
  const tbody = document.getElementById('userTableBody');
  if (!tbody) return;
  const isManagerView = document.body.dataset.view === 'manager';

  const { pageRows, total, startIndex } = filterAndPaginate('users', ['name', 'email', 'role', 'department_role', 'department']);
  document.querySelectorAll('.user-count').forEach(el => el.textContent = total);

  tbody.innerHTML = pageRows.map(u => {
    const initials = u.name.split(' ').map(p => p[0]).join('').slice(0, 2).toUpperCase();
    // `checkout_count` comes straight from the backend (GET /users), which
    // sums up the outstanding quantity across that user's active checkouts.
    const custodyLabel = `${u.checkout_count ?? 0} item${(u.checkout_count ?? 0) === 1 ? '' : 's'} checked out`;
    return `
    <tr class="transition hover:bg-card2/40">
      <td class="px-5 py-3.5">
        <div class="flex items-center gap-3">
          <div class="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 text-[11px] font-bold text-white">${initials}</div>
          <div>
            <p class="font-medium text-slate-100">${escapeHtml(u.name)}</p>
            <p class="tag-mono text-[11px] text-slate-500">${escapeHtml(u.email)}</p>
          </div>
        </div>
      </td>
      <td class="px-5 py-3.5">
        <span class="inline-flex items-center gap-1 rounded-full bg-blue-500/10 px-2.5 py-1 text-[11px] font-semibold text-blue-400 ring-1 ring-blue-500/30">
          <span class="h-1.5 w-1.5 rounded-full bg-blue-500"></span> ${escapeHtml(isManagerView ? (u.department_role || 'Team Member') : u.role.replace('_', ' '))}
        </span>
      </td>
      <td class="px-5 py-3.5 tag-mono text-slate-300">${custodyLabel}</td>
      <td class="px-5 py-3.5">
        <div class="flex justify-end gap-2">
          <button data-action="open-custody" data-entity-id="${u.id}" data-entity-type="user" class="rounded-md border border-border px-2.5 py-1.5 text-[12px] font-medium text-slate-300 transition hover:border-blue-500/50 hover:text-blue-400">Custody Ledger</button>
          ${isManagerView ? '' : `<button data-action="delete-profile" data-user-id="${u.id}" data-user-name="${escapeHtml(u.name)}" class="rounded-md border border-rose-500/30 px-2.5 py-1.5 text-[12px] font-medium text-rose-400 transition hover:border-rose-500 hover:bg-rose-500/10">Delete Profile</button>`}
        </div>
      </td>
    </tr>`;
  }).join('') || `<tr><td colspan="4" class="px-5 py-6 text-center text-slate-500">No accounts found.</td></tr>`;

  renderPaginationBar('users', total, startIndex, pageRows.length);
}
registerRenderer('users', renderUsersTable);

// ---- Delete Profile (Super Admin only) ----
export async function deleteProfile(userId, userName) {
  // Requirement #4 frontend safeguard: intercept and block a Super Admin
  // trying to delete their own active session's account BEFORE the
  // request even goes out. The backend enforces this too (defense in
  // depth), but catching it here gives an immediate, clear message
  // instead of a round-trip 403.
  const session = getSession();
  if (session && String(session.sub) === String(userId)) {
    alert("You cannot delete your own account while logged in as it.");
    return;
  }
  if (!confirm(`Delete profile for ${userName}? This cannot be undone.`)) return;
  try {
    await apiRequest(`/users/${userId}`, { method: 'DELETE' });
    refreshDashboard();
  } catch (err) {
    alert(err.message);
  }
}

// ---- Provision System User Account (Super Admin + Manager) ----
// Managers reach this same form/handler (see admin.html/manager.html); the
// ROLE dropdown available to them is limited to Staff/Customer directly in
// the HTML, and the backend independently re-checks + enforces that same
// limit in POST /users, so a manager can't grant themselves admin rights
// even by tampering with the page or calling the API directly.
export async function submitCreateUserForm(event) {
  event.preventDefault();
  const passwordInput = document.getElementById('newUserPassword');
  const payload = {
    name: document.getElementById('newUserName').value,
    email: document.getElementById('newUserEmail').value,
    role: document.getElementById('newUserRole').value,
    password: passwordInput.value,
    department: document.getElementById('newUserDepartment').value || null,
    department_role: document.getElementById('newUserDeptRole').value || null,
  };
  try {
    const result = await apiRequest('/users', { method: 'POST', body: JSON.stringify(payload) });
    alert(result.message);
    document.getElementById('createUserForm').reset();
    // Security fix: explicitly blank the password field's in-memory value
    // right after submitting, on top of the form .reset() above. .reset()
    // normally clears it already, but some browsers can restore an
    // autofilled value into a "reset" field -- this line guarantees the
    // plaintext password isn't left sitting in the DOM/input value after
    // the account has been created.
    if (passwordInput) passwordInput.value = '';
    refreshDashboard();
  } catch (err) {
    alert(err.message);
    if (passwordInput) passwordInput.value = '';
  }
}
