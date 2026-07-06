// =============================================================================
// js/ui.js
// -----------------------------------------------------------------------------
// Generic, page-agnostic UI helpers shared by every component: modal
// open/close, HTML-escaping, tab switching, the dispatch-drawer route
// toggle, the Properties Hub capacity-edit toggle, and the generic
// search/pagination engine reused by every listing table.
//
// Nothing in this file knows about assets/users/outsiders specifically --
// `components/*.js` call into this file, not the other way around.
// =============================================================================

// Every modal in this app ("Issue/Dispatch" drawer, "Custody Ledger"
// drawer, "My Profile" window) is built the same way: a `fixed inset-0 ...
// hidden items-center justify-center` (or `justify-end`, for the
// slide-in drawers) wrapper div around the actual modal box, so the box
// ends up centered (or docked to the right edge) via Flexbox.
//
// BUG THIS FIXES: `items-center`/`justify-center`/`justify-end` only do
// anything on an element that is ALSO `display: flex` (or `grid`) -- and
// this function used to only ever remove the `hidden` class, never add a
// `flex` class back. That meant every modal's wrapper was rendering as a
// plain `display: block` div the whole time: the alignment utilities were
// silently no-ops, so the modal box itself was left sitting in its default
// block-flow position (pinned to the top-left, ignoring `items-center`/
// `justify-center`) instead of actually being centered/docked on screen --
// this is what the "user properties window" (My Profile) alignment
// problem was.
//
// The fix: toggle `hidden` and `flex` TOGETHER, as a pair, exactly like
// `toggleCapacityEdit()` below already does for the same reason. (We
// deliberately do NOT just leave a static `flex` class sitting on the
// element next to `hidden` in the HTML -- Tailwind explicitly warns against
// that combination, since which one "wins" depends on the order its
// utilities happen to be generated in, which isn't something you want to
// depend on. Toggling them from JS removes that ambiguity entirely.)
export function openModal(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('hidden');
  el.classList.add('flex');
}

export function closeModal(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.add('hidden');
  el.classList.remove('flex');
}

export function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function switchTab(tab) {
  const assets = document.getElementById('assetInventorySection');
  const users = document.getElementById('userDirectorySection');
  const adhoc = document.getElementById('adhocDirectorySection');
  const tabAssets = document.getElementById('tabAssets');
  const tabUsers = document.getElementById('tabUsers');
  const tabAdhoc = document.getElementById('tabAdhoc');
  if (!assets || !users) return;

  const activeCls = ['border-blue-500', 'text-slate-50', 'font-semibold'];
  const inactiveCls = ['border-transparent', 'text-slate-500', 'font-medium'];
  const allTabs = [tabAssets, tabUsers, tabAdhoc].filter(Boolean);
  const allSections = [assets, users, adhoc].filter(Boolean);

  allSections.forEach(s => s.classList.add('hidden'));
  allTabs.forEach(t => { t.classList.add(...inactiveCls); t.classList.remove(...activeCls); });

  if (tab === 'assets') {
    assets.classList.remove('hidden');
    tabAssets.classList.add(...activeCls); tabAssets.classList.remove(...inactiveCls);
  } else if (tab === 'adhoc' && adhoc) {
    adhoc.classList.remove('hidden');
    tabAdhoc.classList.add(...activeCls); tabAdhoc.classList.remove(...inactiveCls);
  } else {
    users.classList.remove('hidden');
    tabUsers.classList.add(...activeCls); tabUsers.classList.remove(...inactiveCls);
  }
}

export function toggleRoute() {
  const val = document.getElementById('routeSelect').value;
  document.getElementById('staffField').classList.toggle('hidden', val !== 'staff');
  document.getElementById('customerField').classList.toggle('hidden', val !== 'customer');
  document.getElementById('adhocField').classList.toggle('hidden', val !== 'adhoc');
}

export function toggleCapacityEdit() {
  document.getElementById('capacityBtn').classList.toggle('hidden');
  const edit = document.getElementById('capacityEdit');
  edit.classList.toggle('hidden');
  edit.classList.toggle('flex');
}

// =============================================================================
// SEARCH + PAGINATION (generic, reused by every listing table)
// -----------------------------------------------------------------------------
// Every table on the dashboards ("Asset Inventory", "User Directory" / "Team
// Allocation Matrix", "Ad-Hoc Directory", and the self-service "My Items"
// tables) works the same way:
//   1. Fetch the FULL list from the API once and cache it in `tableState`.
//   2. Whenever the user types in the search box, changes "Rows per page",
//      or clicks Prev/Next, we DON'T hit the API again -- we just re-filter
//      and re-slice the cached array in memory and re-render. This is what
//      fixes the old "Rows per page does nothing" bug and keeps the UI fast
//      even with a large list, since filtering/pagination happen instantly
//      client-side instead of round-tripping to the server.
//   3. Each component's `renderXxxTable()` reads `tableState[key]`, figures
//      out which "page" of rows to show, renders just those rows, and
//      updates the "Showing X-Y of Z" + Prev/Next button states.
// =============================================================================
export const tableState = {
  assets: { raw: [], search: '', page: 1, perPage: 10 },
  users: { raw: [], search: '', page: 1, perPage: 10 },
  outsiders: { raw: [], search: '', page: 1, perPage: 10 },
  myItems: { raw: [], search: '', page: 1, perPage: 10 },
};

// Maps a table key to the function that should re-render it. Each
// component registers its own render function via `registerRenderer()` once
// it's defined, so `setSearch`/`setPerPage`/`changePage` can call the right
// one without this module needing to import every component directly.
const RENDERERS = {};

export function registerRenderer(key, renderFn) {
  RENDERERS[key] = renderFn;
}

// Filters `rows` by `state.search` (case-insensitive substring match across
// `searchFields`), then slices out just the current page. Returns everything
// the caller needs to both render the rows and update the pagination bar.
export function filterAndPaginate(key, searchFields) {
  const state = tableState[key];
  let rows = state.raw;

  const query = state.search.trim().toLowerCase();
  if (query) {
    rows = rows.filter((row) =>
      searchFields.some((field) => String(row[field] ?? '').toLowerCase().includes(query))
    );
  }

  const total = rows.length;
  const totalPages = Math.max(1, Math.ceil(total / state.perPage));
  if (state.page > totalPages) state.page = totalPages;
  if (state.page < 1) state.page = 1;

  const startIndex = (state.page - 1) * state.perPage;
  const pageRows = rows.slice(startIndex, startIndex + state.perPage);

  return { pageRows, total, totalPages, startIndex };
}

// Updates the little "Showing 1-10 of 42" label and disables Prev/Next at
// the ends of the list. Safe to call even if a page doesn't have a
// pagination bar for this table (the elements just won't be found).
export function renderPaginationBar(key, total, startIndex, pageRowsLength) {
  const state = tableState[key];
  const infoEl = document.getElementById(`${key}PageInfo`);
  if (infoEl) {
    infoEl.textContent = total === 0
      ? 'No results found.'
      : `Showing ${startIndex + 1}-${startIndex + pageRowsLength} of ${total}`;
  }
  const totalPages = Math.max(1, Math.ceil(total / state.perPage));
  const prevBtn = document.getElementById(`${key}PrevBtn`);
  const nextBtn = document.getElementById(`${key}NextBtn`);
  if (prevBtn) prevBtn.disabled = state.page <= 1;
  if (nextBtn) nextBtn.disabled = state.page >= totalPages;
}

// Called from the search box's 'input' listener (wired in main.js).
export function setSearch(key, value) {
  if (!tableState[key]) return;
  tableState[key].search = value;
  tableState[key].page = 1; // always jump back to page 1 on a new search
  if (RENDERERS[key]) RENDERERS[key]();
}

// Called from the "Rows per page" <select>'s 'change' listener (main.js).
export function setPerPage(key, value) {
  if (!tableState[key]) return;
  tableState[key].perPage = parseInt(value, 10) || 10;
  tableState[key].page = 1;
  if (RENDERERS[key]) RENDERERS[key]();
}

// Called from the Prev (-1) / Next (+1) buttons' delegated click handler.
export function changePage(key, delta) {
  if (!tableState[key]) return;
  tableState[key].page += delta;
  if (RENDERERS[key]) RENDERERS[key]();
}

export function statusBadge(available) {
  if (available <= 3) {
    return `<span class="inline-flex items-center gap-1 rounded-full bg-amber-500/10 px-2.5 py-1 text-[11px] font-semibold text-amber-400 ring-1 ring-amber-500/30"><span class="h-1.5 w-1.5 rounded-full bg-amber-500"></span> Critical Low Stock</span>`;
  }
  return `<span class="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2.5 py-1 text-[11px] font-semibold text-emerald-400 ring-1 ring-emerald-500/30"><span class="h-1.5 w-1.5 rounded-full bg-emerald-500"></span> In Stock</span>`;
}
