# Snipe-IT Lite

A small, self-hosted **IT asset registry / equipment checkout system** —
think "who currently has the MacBook Pool unit #12, and when is it due
back?" Built with a **FastAPI + PostgreSQL** backend and a **plain
HTML/JS (no framework, no build step)** frontend, all wired together with
Docker Compose.

This README is a **complete guide for a beginner developer**. It assumes
you can read code but may not have deployed a full-stack app before. It
covers: what the app does, how to run it (with Docker and without), what
every file is for, how the pieces fit together, how to safely make changes
or add features, how to test what you build, and how to move this toward a
real production deployment.

> **New here? Read in this order:** [Quick Start](#quick-start-docker) to get it
> running → [Feature Tour](#feature-tour) to see what it does →
> [How A Request Flows](#how-a-request-flows-through-the-app) for the
> mental model → [Making Changes Safely](#making-changes-safely-a-guide-for-beginners)
> when you're ready to modify something.

---

## Table of Contents

1. [What This App Does](#what-this-app-does)
2. [Feature Tour](#feature-tour)
3. [Tech Stack](#tech-stack)
4. [Project Structure](#project-structure)
5. [How A Request Flows Through The App](#how-a-request-flows-through-the-app)
6. [Quick Start (Docker)](#quick-start-docker)
7. [Deploying Across Environments (nginx Reverse Proxy)](#deploying-across-environments-nginx-reverse-proxy)
8. [Running Without Docker (Local Dev)](#running-without-docker-local-dev)
9. [Environment Variables Reference](#environment-variables-reference)
10. [Roles & Permissions Model](#roles--permissions-model)
11. [Database & Migrations (Alembic)](#database--migrations-alembic)
12. [Full API Reference](#full-api-reference)
13. [File & Function Reference](#file--function-reference)
14. [Making Changes Safely (A Guide For Beginners)](#making-changes-safely-a-guide-for-beginners)
15. [Testing Your Changes](#testing-your-changes)
16. [Security Model](#security-model)
17. [Running In Production](#running-in-production)
18. [Suggested Future Features](#suggested-future-features)
19. [Troubleshooting](#troubleshooting)

---

## What This App Does

Five kinds of people use the system:

| Role | Can do |
|------|--------|
| `super_admin` | Everything `admin` can do (see below). This is a single **hardcoded** identity, not a `users` table row — configured via `SUPER_ADMIN_USERNAME`/`SUPER_ADMIN_PASSWORD` in your environment (see [Environment Variables Reference](#environment-variables-reference)). There is always exactly one, it can never be created/edited/deleted through the app, and it never appears in the User Directory or any other listing. |
| `admin` | Everything: create/delete asset pools, adjust capacity, flag maintenance exceptions, provision any account, view/export all audit logs, export properties for anyone. A normal, database-backed, editable/deletable account — functionally identical in privilege to `super_admin`, just not the one hardcoded root identity. |
| `manager` | View inventory, dispatch/check-in items to Staff, Linked Customers, or Ad-Hoc Individuals; manage custody for their own department; provision new Staff/Customer logins (never Manager/Admin); export properties/audit data for their scope. |
| `staff` | Self-service dashboard showing their own checked-out items, with the ability to export their own list; can view/edit their own profile and change their own password. |
| `customer` | Same as staff, but for an external contact who has a login (as opposed to an "Ad-Hoc Individual", who doesn't — see below). |

Wherever the rest of this README says "Super Admin", it applies equally to
both `super_admin` and `admin` — they're permission-equivalent everywhere
in the app. The distinction only matters for account *lifecycle*: one is a
hardcoded singleton you configure via environment variables, the other is
an ordinary account you create/manage through the UI like anyone else. See
[Roles & Permissions Model](#roles--permissions-model) for the full
rationale.

The core object is an **Asset Pool** (`AssetType`, e.g. "MacBook Pro 14"
M3 Pool") with a `total_quantity`. Units of that pool can be:

- **Checked out** to a User (Staff/Customer) or an ad-hoc **Outsider**
  (`AssetCheckout`),
- **Isolated** for repair/loss (`AssetException`), or
- **Available** (everything else).

```
Available = Total − Outbound (active checkouts) − Isolated
```

This formula is recalculated by `backend/services/stock.py` after every
mutating action, so it's never allowed to drift out of sync. Every
meaningful action in the system (checkouts, returns, pool changes, account
changes, etc.) is written to an append-only `AuditLog` that can never be
edited or deleted through the app.

## Feature Tour

This section walks through **every feature** the app has, organized by
who uses it.

### Asset Inventory (Super Admin)

- **Create an asset pool** — name + starting quantity + optional custom
  fields (JSON blob for anything pool-specific you want to track).
- **Adjust capacity** — change `total_quantity` up or down at any time;
  the Available count recalculates automatically.
- **Flag a unit as unavailable** ("Exception") — mark one serial number as
  "Under Repair", "Stolen", "Missing", etc. It's pulled out of the
  Available pool until someone "Recalls" it back into service.
- **Bulk import via CSV** — upload a spreadsheet to create many pools at
  once. Files over 5 MiB are rejected before parsing (denial-of-service
  protection). Malformed rows are reported back to you individually
  instead of failing the whole import.
- **Dispatch (checkout)** — assign N units of a pool to a Staff member, a
  Customer, or an ad-hoc Outsider, with a due date. A due date is
  **required** for anyone without a login (ad-hoc Outsiders), since
  there's no dashboard reminding them.
- **Delete an asset pool** — permanently remove a pool from active
  inventory (soft-delete: the row and its full checkout/exception history
  stay intact for the audit trail, it just disappears from listings).
  Blocked while the pool still has outstanding checkouts or isolated
  (under-repair/stolen) units, so inventory can never silently "disappear"
  out from under an active custody or maintenance record. Reachable two
  ways: a "Delete" button directly on each row of the Asset Inventory
  table, or a "Delete Asset Pool" button inside that pool's own Properties
  Hub modal.

### Custody & Returns (Super Admin / Manager)

- **Custody Ledger** — open any user's or ad-hoc individual's page to see
  everything currently checked out to them.
- **Process a return** — partial returns are supported (e.g. someone
  returns 3 of the 5 units they were issued; the other 2 stay outstanding
  on the same checkout record).
- **Bulk return** — select multiple line items in the Custody Ledger and
  return them all in one action.
- **Overdue alerts** — a banner on the Admin/Manager dashboard lists every
  active checkout whose due date has passed, most-overdue-first.

### Directories (Super Admin / Manager)

- **User Directory** — every Staff/Customer/Manager/Admin account. A
  Manager only sees their own department's users plus every Customer; an
  Admin/Super Admin sees everyone. The hardcoded `super_admin` identity
  itself never appears here (or anywhere else the directory is listed/
  exported) — it isn't a `users` table row, so there's nothing for these
  queries to return.
- **Ad-Hoc (Unlinked) Directory** — external people who receive equipment
  but never get a login (contractors, vendors, guests, etc.) — created
  automatically the first time you check something out to a new name.
- **Provision a new account** — Super Admins can create any role; Managers
  can only create Staff/Customer accounts.
- **Soft-delete an account/pool** — nothing is ever hard-deleted. A
  "deleted" row just gets hidden from listings and can no longer log in
  (for a User); its full history stays intact for the audit trail.
- **Search + pagination, entirely server-side** — the Asset Inventory,
  User Directory, and Ad-Hoc Directory tables (like the Audit Ledger)
  never download an entire table into the browser. Every keystroke in a
  search box (debounced ~300ms so it doesn't fire on every keypress),
  page turn, or "rows per page" change re-fetches just that slice from
  the API via `?search=&limit=&offset=`, so these directories stay fast
  and responsive no matter how large they grow. See [How A Request Flows
  Through The App](#how-a-request-flows-through-the-app) and
  `services/search_utils.py` for how the search matching works.

### Exporting Data (all roles, scoped by permission)

Everyone can export the data they're allowed to see, as **CSV** (for
spreadsheets) or **PDF** (for printing/sharing):

| Who | What they can export |
|---|---|
| Staff / Customer | Their own "Properties Assigned To Me" list. |
| Manager | One specific user's or ad-hoc individual's custody ledger; a bulk export of every active checkout across their department + all customers, or across all ad-hoc individuals; the audit ledger (their own entries only). |
| Super Admin | Any/all of the above, unrestricted. |

All exports share one formatting/security layer
(`backend/services/export_service.py`) — see
[Full API Reference](#full-api-reference) for the exact endpoints.

### "My Profile" (everyone)

Click your name in the navbar on any dashboard to:
- View your name, email, username, role, and department (fetched fresh
  from the server every time you open it — never a stale cached value).
- Change your own password (you must correctly enter your *current*
  password first — this prevents someone who steals an unattended, still
  logged-in session from locking you out of your own account).

### Audit Trail (Super Admin / Manager)

- A permanent, paginated, append-only log of every meaningful action:
  pool created/deleted, capacity changed, unit flagged/recalled, checkout,
  return, account created/deleted, password changed, etc.
- Every entry records **who did it** (`operator`), **what** (`action`),
  **which record it affected** (`target_type`/`target_id`), and a
  human-readable **details** string. A return entry specifically also
  names **who the equipment was returned from** — a linked User (name +
  email) or an unlinked ad-hoc Outsider (name, and company if known).
- Exportable as CSV or PDF. Export generation runs on a background
  Celery worker (see [Tech Stack](#tech-stack)) rather than inline in the
  request — clicking "Export" enqueues a job and polls it to completion
  before downloading, so a wide date range never risks tying up the API
  or timing out the browser. A Manager only ever sees/exports entries
  they personally generated; a Super Admin sees everything.

### Account Security (built-in, mostly invisible until you need it)

- Passwords are hashed with **Argon2id**, never stored or logged in plain
  text, and must meet a minimum complexity policy.
- Login is rate-limited **per IP address** (a burst of guesses from one
  source gets slowed down) **and** **per account** (after too many wrong
  passwords against the *same* account, that account is locked for a
  cooldown period no matter which IP the attempts come from).
- Sessions use signed JWTs; deactivating or deleting an account takes
  effect **immediately** on their next request, rather than waiting for
  their token to naturally expire.
- An idle dashboard automatically logs you out after a period of
  inactivity.

## Tech Stack

- **Backend:** Python 3.11, FastAPI, SQLAlchemy 2.0, PostgreSQL 16,
  Alembic (migrations), PyJWT (session tokens), `pwdlib`/Argon2id
  (password hashing), Pydantic Settings v2 (typed config), `reportlab`
  (PDF generation for exports), Celery + Redis (background workers for
  audit-ledger exports — see below).
- **Frontend:** Plain HTML + vanilla JS ES Modules — **no React/Vue, no
  app build step** — styled with Tailwind CSS, compiled locally ahead of
  time to a single static `frontend/css/tailwind.css` (see
  [`build-tailwind/README.md`](build-tailwind/README.md)) instead of being
  pulled from a CDN and recompiled in every visitor's browser at runtime.
  Served by an nginx reverse proxy built from
  [`nginx/Dockerfile`](nginx/Dockerfile) (see
  [Deploying Across Environments](#deploying-across-environments-nginx-reverse-proxy)).
- **Infra:** Docker Compose, 5 services: `db` (Postgres), `redis`
  (Celery broker/result backend, not exposed to the host), `backend`
  (FastAPI/uvicorn, not exposed to the host), `worker` (Celery — builds
  audit-ledger CSV/PDF exports out-of-band, not exposed to the host),
  `frontend` (nginx — serves the static site AND reverse-proxies
  `/api/*` to `backend`, the only publicly-exposed service).

Because `frontend/css/tailwind.css` is a plain committed file (not
generated inside the Docker build), **editing an `.html` or `.js` file
and refreshing your browser is still the entire "deploy" cycle** while
developing locally — nothing to compile, and `docker compose up` needs no
`npm install` of its own. The only time you touch `build-tailwind/` is
if you add/remove Tailwind utility classes and need to regenerate that
one CSS file — see that folder's README for the one-line command.

## Project Structure

```
snipe-it-lite/
├── docker-compose.yml        # 5 services: db, redis, backend, worker, frontend
├── render.yaml                # Render Blueprint -- deploys all tiers, see
│                                # "Deploying Across Environments" section above
├── .env.example               # Copy this to .env and fill in real secrets
├── .gitignore                 # Keeps .env (and other junk) out of git
├── .dockerignore               # Keeps .env (and other junk) out of the build context too
│
├── nginx/
│   ├── Dockerfile                  # Builds the frontend/reverse-proxy image
│   ├── default.conf.template        # nginx config template -- see "Deploying
│   │                                  # Across Environments" section above
│   └── docker-entrypoint.d/
│       └── 15-detect-resolver-ip.sh  # Auto-detects RESOLVER_IP from
│                                       # /etc/resolv.conf if it isn't set
│                                       # (must stay non-executable -- see
│                                       # its own header comment for why)
│
├── backend/
│   ├── main.py                    # FastAPI app: middleware, startup, routers
│   ├── config.py                   # Pydantic Settings -- all env vars, one place
│   ├── database.py                  # SQLAlchemy engine/session + init_db()/seed_db()
│   ├── models.py                     # SQLAlchemy ORM table definitions
│   ├── security.py                    # Password hashing, password policy, JWT
│   ├── deps.py                         # get_current_user / role-gate dependencies
│   ├── logging_config.py                # Structured (JSON) logging setup
│   ├── celery_app.py                      # Celery app: Redis broker/result backend
│   │                                        # for async exports -- shared by `backend`
│   │                                        # (producer) and `worker` (consumer)
│   ├── requirements.txt                  # Python dependencies
│   ├── Dockerfile                         # Backend container build (also used,
│   │                                        # unmodified, by the `worker` service --
│   │                                        # see docker-compose.yml)
│   │
│   ├── tasks/                     # Celery tasks -- run on the `worker` container
│   │   └── export_tasks.py          # generate_audit_export(): builds the CSV/PDF
│   │                                  # off the request/response cycle
│   │
│   ├── middleware/                # ASGI middleware, one concern per file
│   │   ├── request_context.py       # Request Correlation ID (X-Request-ID)
│   │   ├── rate_limit.py             # Per-IP login rate limiting
│   │   └── security_headers.py       # Standard defensive response headers
│   │
│   ├── api/                       # Thin FastAPI routers (HTTP layer only)
│   │   ├── auth.py, assets.py, users.py, outsiders.py, checkouts.py, audit.py
│   │
│   ├── schemas/                   # Pydantic request/response models
│   │   ├── auth.py, assets.py, users.py, checkouts.py
│   │
│   ├── services/                  # All business logic / DB queries live here
│   │   ├── auth_service.py           # Login, password changes, account lockout
│   │   ├── asset_service.py           # Asset pool CRUD, checkout, CSV import
│   │   ├── user_service.py             # User directory, self/bulk exports
│   │   ├── outsider_service.py          # Ad-hoc directory, exports
│   │   ├── checkout_service.py           # Returns, overdue-checkout feed
│   │   ├── audit_service.py               # Audit ledger + CSV/PDF export
│   │   ├── export_service.py               # Shared CSV/PDF builders
│   │   ├── search_utils.py                  # Shared ILIKE search-filter helper
│   │   │                                       # (GET /assets, /users, /outsiders)
│   │   └── stock.py                         # The Available-quantity formula
│   │
│   └── alembic/                    # Database migration scripts
│       ├── env.py
│       └── versions/
│           ├── 0001_baseline_schema.py
│           └── 0002_add_account_lockout_fields.py
│
├── build-tailwind/              # Build tooling ONLY -- never shipped/run in
│   │                              # Docker. Compiles frontend/css/tailwind.css.
│   │                              # See build-tailwind/README.md.
│   ├── tailwind.config.js         # Theme colors/fonts, single source of truth
│   ├── input.css                   # @tailwind base/components/utilities
│   └── package.json                 # `npm run build` / `npm run watch`
│
└── frontend/
    ├── index.html            # Login page
    ├── admin.html            # Super Admin dashboard
    ├── manager.html          # Manager dashboard
    ├── staff.html            # Staff self-service dashboard
    ├── customer.html         # Customer self-service dashboard
    ├── css/
    │   └── tailwind.css       # Compiled by build-tailwind/ -- committed as a
    │                            # plain static file, not generated by Docker
    └── js/
        ├── main.js            # Wires up every DOM event (event delegation)
        ├── api.js             # The one place that calls fetch()
        ├── auth.js            # Login/session/JWT-decode/role guard
        ├── ui.js               # Shared table/pagination/modal helpers
        ├── dashboard.js         # refreshDashboard() orchestrates all loads
        └── components/           # One file per feature area
            ├── assets.js           # Inventory table, dispatch, exceptions, CSV import
            ├── audit.js             # Audit ledger table + CSV/PDF export
            ├── custody.js            # Custody Ledger modal + returns
            ├── exports.js             # Properties-assigned CSV/PDF downloads
            ├── myitems.js              # Staff/Customer "what do I have?" view
            ├── outsiders.js             # Ad-Hoc directory table
            ├── overdue.js                # Overdue-checkouts alert banner
            ├── profile.js                 # "My Profile" modal + change password
            └── users.js                    # User directory table + provisioning
```

## How A Request Flows Through The App

This is the most important mental model in the whole project. Once you
understand this, every file's purpose becomes obvious.

```
Browser (frontend/js)
   │  fetch('/api/...') — see js/api.js (relative path, no hardcoded host)
   ▼
nginx (frontend container)   <-- reverse proxy: strips the "/api" prefix and
                                  forwards to the backend container. See
                                  nginx/default.conf.template and the
                                  "Deploying Across Environments" section.
   │
   ▼
api/*.py            <-- HTTP layer only: parses the request body, checks
                        "is this person allowed to call this?", then hands
                        off to a services/*.py function. Contains almost
                        no actual logic.
   │
   ▼
services/*.py       <-- ALL business logic lives here: validation beyond
                        what Pydantic already checked, database queries,
                        the Available-quantity formula, audit log writes.
                        This is where you look for "how does X actually
                        work?"
   │  SQLAlchemy ORM (never raw SQL)
   ▼
models.py           <-- Table definitions. The shape of the data.
   │
   ▼
PostgreSQL
```

Two more pieces sit alongside this flow:

- **`schemas/*.py`** define what a valid request/response *looks like* —
  Pydantic validates this automatically before your route code even runs
  (e.g. "is `quantity` a positive integer?", "does this password meet the
  complexity policy?"). If validation fails, FastAPI returns a `422` error
  before your function body executes at all.
- **`deps.py`** defines *who's allowed* to call a route (e.g.
  `require_super_admin`, `require_privileged_role`) — these run as FastAPI
  dependencies, one line above your route function, keeping permission
  checks consistent instead of hand-rolled inside every function.

**Nothing outside `database.py` talks to SQLAlchemy's engine directly** —
every other file gets a `Session` handed to it via the `get_db()`
dependency.

On the frontend, the equivalent flow is:

```
User clicks something (data-action="..." attribute)
   │
   ▼
js/main.js's event delegation      <-- one click listener on the whole
                                        page, dispatches based on the
                                        data-action attribute
   │
   ▼
js/components/*.js                 <-- one file per feature area; calls
                                        apiRequest() (js/api.js) to talk
                                        to the backend, then re-renders
                                        its own table/modal
   │
   ▼
js/ui.js's shared helpers          <-- escapeHtml(), pagination, modals
```

## Quick Start (Docker)

This is the fastest way to get the whole app running — no Python or
Node.js installation needed on your machine at all, just Docker.

```bash
# 1. Copy the environment template and fill in real secrets
cp .env.example .env

#    - Generate a real JWT secret and paste it into .env as JWT_SECRET_KEY:
python3 -c "import secrets; print(secrets.token_hex(32))"

#    - Pick a real POSTGRES_PASSWORD and update DATABASE_URL in .env to match
#      (the placeholder password appears in BOTH places -- keep them in sync).

# 2. Build and start everything (Postgres, Redis, backend, worker, frontend)
docker compose up --build

# 3. Open the app -- everything is served from ONE origin now, via the
#    nginx reverse proxy (see the next section for how/why):
#    App (login page):  http://localhost:8080
#    API docs:           http://localhost:8080/docs
```

Leave the terminal running to see live logs from all three containers.
Press `Ctrl+C` to stop everything, or run `docker compose up -d --build`
to start it in the background instead.

**To stop and remove the containers (keeping your database data):**
```bash
docker compose down
```

**To wipe the database completely and start fresh** (useful if you break
something while experimenting):
```bash
docker compose down -v   # -v also removes the named Postgres volume
docker compose up --build
```

### Demo Login Credentials

The very first time the app starts against an **empty** database, it
seeds a few demo accounts and some sample inventory/checkouts (see
`backend/database.py -> seed_db()`) so you have something to look at
immediately. This only happens if `AUTO_SEED_DEMO_DATA=true` (the default
for local dev — see [Environment Variables Reference](#environment-variables-reference)).

| Role | Email | Username | Password |
|------|-------|----------|----------|
| Admin | `r.adeyemi@corp.io` | `r.adeyemi` | `Admin123!` |
| Manager | `s.chen@corp.io` | `s.chen` | `Manager123!` |
| Staff | `t.okafor@corp.io` | `t.okafor` | `Staff123!` |
| Customer | `d.martins@customer.io` | `d.martins` | `Customer123!` |

Login accepts **either** the email or the username in the same field.

**Super Admin** isn't seeded here — it's the hardcoded root identity
described in [Roles & Permissions Model](#roles--permissions-model). For
local Docker Compose, `.env.example`'s defaults let you log in with
username `superadmin` / password `change-this-super-admin-password`; set
your own `SUPER_ADMIN_USERNAME`/`SUPER_ADMIN_PASSWORD` before deploying
anywhere real.

## Deploying Across Environments (nginx Reverse Proxy)

This app is designed to run, **unmodified**, across three tiers: your local
Docker Compose setup, a Render staging environment, and a real cloud
environment (AWS/GCP/Azure/etc.). The piece that makes that possible is the
`frontend` service — it's no longer a bare static-file server, it's an
**nginx reverse proxy** built from [`nginx/Dockerfile`](nginx/Dockerfile).

**The core idea:** the browser never talks to the FastAPI backend directly
and never needs to know its hostname. `frontend/js/api.js` calls a single
constant, relative path — `/api` — for every request. nginx, sitting in
front of both the static site and the backend, quietly forwards
(“proxies”) anything under `/api/*` to wherever the real backend actually
lives in that environment, stripping the `/api` prefix on the way through
(FastAPI's routers mount at `/auth`, `/assets`, `/users`, etc. — no `/api`
prefix of their own). See [`nginx/default.conf.template`](nginx/default.conf.template)
for the fully-commented config that does this.

```
Browser  --GET /api/assets-->  nginx (frontend container)  --GET /assets-->  FastAPI (backend container)
Browser  <--------------------------- same response --------------------------------------
```

Because that config is a **template** (`envsubst`'d by nginx's own
entrypoint script every time the container starts), the exact same Docker
image works in all three tiers — only these environment variables change:

| Variable | What it controls | Local Docker Compose | Render / Cloud |
|---|---|---|---|
| `PORT` | Port nginx listens on inside its container | `80` | Whatever port that platform injects |
| `BACKEND_HOST` | Hostname nginx proxies `/api/*` to | `backend` (the Compose service name) | Your backend service's real hostname on that platform |
| `BACKEND_PORT` | Port on that host | `8000` | Whatever port your backend actually listens on there |
| `RESOLVER_IP` | Internal DNS server nginx uses to re-resolve `BACKEND_HOST` on every request (so a backend redeploy never leaves nginx pointed at a stale IP) | `127.0.0.11` (Docker's built-in DNS) | Auto-detected at boot from `/etc/resolv.conf` if left unset — see [`nginx/docker-entrypoint.d/15-detect-resolver-ip.sh`](nginx/docker-entrypoint.d/15-detect-resolver-ip.sh) |

`PORT`, `BACKEND_HOST`, and `BACKEND_PORT` all have sensible defaults baked
into `nginx/Dockerfile`. `RESOLVER_IP` deliberately does **not** — instead of
hardcoding a guess that could go stale on some future platform, it's
auto-detected at container boot (see the table above and
[`nginx/docker-entrypoint.d/15-detect-resolver-ip.sh`](nginx/docker-entrypoint.d/15-detect-resolver-ip.sh)
for why). All four are already wired up as `environment:` overrides on the
`frontend` service in `docker-compose.yml`, sourced from `.env` (see
`.env.example`) — Compose explicitly pins `RESOLVER_IP=127.0.0.11` there, so
nothing changes for local dev.

### Local Docker Compose
Nothing to configure — `docker compose up --build` already sets
`BACKEND_HOST=backend`/`BACKEND_PORT=8000`, matching the `backend` service
in the same compose file.

### Render

The easiest path is the [`render.yaml`](render.yaml) **Blueprint** at the
repo root, which provisions all three pieces (Postgres, the private
backend, and the public frontend/proxy) in one shot and wires them
together automatically:

- [ ] Push `render.yaml` (already at the repo root) to your Git provider.
- [ ] In the Render Dashboard: **New** → **Blueprint** → connect this repo.
      Render reads `render.yaml`, shows you the three resources it's about
      to create (`snipeit-lite-db`, `snipeit-lite-backend`,
      `snipeit-lite-frontend`), and provisions them on **Deploy Blueprint**.
- [ ] That's it — `render.yaml` uses Blueprint's `fromService`/
      `fromDatabase` references to fill in `DATABASE_URL` (from the
      Postgres instance) and `BACKEND_HOST`/`BACKEND_PORT` (from the
      backend private service) automatically. There's no "open the
      Connect menu and copy the internal hostname" step to do by hand —
      see `render.yaml`'s own comments for exactly how each variable is
      derived, and the "Deploying Across Environments" table above for
      what each one controls. `RESOLVER_IP` is intentionally left unset;
      it's auto-detected at boot (see the table above).
- [ ] `JWT_SECRET_KEY` is auto-generated by Render (`generateValue: true`)
      — you never need to invent or store one yourself.
- [ ] `ENABLE_API_DOCS` is already set to `false` on both services in
      `render.yaml` — `/docs`, `/redoc`, and `/openapi.json` are disabled
      by default on this Blueprint, not just left at their locally-
      convenient default. See the Security Model section above if you
      ever want to turn them back on for a staging environment.
- [ ] Both services default to `region: oregon` in `render.yaml` — change
      both together if you want a different region (private networking,
      and therefore this whole setup, only works within a single region).
- [ ] Verify: load the frontend service's public Render URL, log in, and
      confirm `/api/*` calls succeed (open your browser's Network tab —
      you should see `200`s from `/api/auth/login` etc., not connection
      errors or `405`s).

> **Troubleshooting: "I edited `render.yaml` but the new env var never
> shows up on the service."** This almost always means that particular
> service isn't actually linked to the Blueprint — usually because it was
> created by hand first (see the manual path below), before `render.yaml`
> existed, or during earlier trial and error. Blueprint sync only pushes
> `render.yaml` changes to resources it created and owns; a manually
> created service ignores the file entirely, silently. **Tell the two
> apart from the Render Dashboard**: a Blueprint-owned service's type
> matches `render.yaml` exactly — the backend must read **Private
> Service**, not **Web Service** (if the backend's dashboard tab/header
> says "Web Service" or it has a public `onrender.com` URL, it was created
> manually and is not the resource `render.yaml` deploys to). Two ways to
> fix a service stuck in this state:
> 1. **(Recommended)** Delete the manually created service(s) and deploy
>    fresh via **New → Blueprint** as described above, so Render creates
>    all three resources from `render.yaml` and they stay in sync going
>    forward.
> 2. Or, keep the manual service and set `SUPER_ADMIN_PASSWORD` (and
>    `JWT_SECRET_KEY`, `SUPER_ADMIN_USERNAME`, etc.) directly on it, by
>    hand, under that service's **Environment** tab — `generateValue: true`
>    only has any effect for variables Blueprint sync itself manages.

<details>
<summary>Prefer to set services up manually instead of via Blueprint? Click to expand.</summary>

Deploy this as **two** services from the same repo/region (private
networking only works within the same Render region):

- [ ] Create a **Web Service** built from `nginx/Dockerfile` (build
      context = repo root) for the frontend/proxy — this is the only
      piece that needs a public URL. Render assigns/injects its own
      `PORT` (defaults to `10000`); the nginx image already reads and
      binds to whatever `PORT` it's given, so there's nothing to change
      in the Dockerfile itself.
- [ ] Create a **Private Service** (not a Web Service) built from
      `backend/Dockerfile` for the FastAPI backend. Private services get
      no public `onrender.com` URL at all and are reachable only from
      other services on your private network — the correct choice here,
      since nothing but nginx should ever reach the backend directly.
      Make sure it binds to `0.0.0.0` on the `PORT` Render gives it (the
      existing `uvicorn main:app --host 0.0.0.0 --port 8000` command
      works — just also set `PORT=8000` in that service's environment,
      or update the Dockerfile's `CMD` to use Render's `$PORT`).
- [ ] In the Render Dashboard, open the backend service's **Connect**
      menu → **Internal** tab to find its actual internal hostname
      (format: `<service-name>-<random-hash>`, not just the plain
      service name). Set that on the **frontend** service's environment:
      ```
      BACKEND_HOST=<the-hostname-shown-in-the-Internal-tab>
      BACKEND_PORT=<the-port-shown-there-too>
      ```
- [ ] Leave `RESOLVER_IP` unset. Render doesn't publish one fixed,
      documented internal-resolver address the way Docker Compose does,
      so rather than guess (and risk that guess silently going stale),
      `nginx/docker-entrypoint.d/15-detect-resolver-ip.sh` reads the real
      one straight out of the container's own `/etc/resolv.conf` at boot.
      Only set `RESOLVER_IP` explicitly if you've independently confirmed
      a different value is needed.
- [ ] Confirm both services are deployed in the **same Render region** —
      private networking (and therefore this whole nginx→backend setup)
      does not work across regions.
- [ ] Verify: load the frontend's public Render URL, log in, and confirm
      `/api/*` calls succeed (open your browser's Network tab — you
      should see `200`s from `/api/auth/login` etc., not connection
      errors). If they fail, re-check `BACKEND_HOST`/`BACKEND_PORT`
      against the Connect → Internal tab values first.

</details>

### Cloud (AWS/GCP/Azure/etc.)
Same pattern: deploy the `nginx/Dockerfile` image as your public-facing
service, deploy `backend/Dockerfile` as an internal-only service (e.g.
behind a private load balancer or in the same VPC/private subnet with no
public IP), and set `BACKEND_HOST`/`BACKEND_PORT` to match that
environment's actual internal DNS naming (e.g. an ECS Service Connect name,
a Kubernetes Service DNS name like `backend.default.svc.cluster.local`, or
an internal ALB/NLB hostname). Leave `RESOLVER_IP` unset unless you've
confirmed a specific value your platform needs — it's auto-detected from
`/etc/resolv.conf` at boot otherwise (see
[`nginx/docker-entrypoint.d/15-detect-resolver-ip.sh`](nginx/docker-entrypoint.d/15-detect-resolver-ip.sh)).

### Why the backend is no longer exposed directly
`docker-compose.yml`'s `backend` service no longer publishes port `8000` to
the host. nginx is now the **only** public entry point; it's the sole thing
that reaches the backend, over each environment's private/internal
network. This shrinks the app's public attack surface to one hardened,
well-understood front door, and is exactly the shape you want in Render/
cloud too — never give your database-talking API container a public IP if
a reverse proxy can front it instead.

## Running Without Docker (Local Dev)

If you'd rather run the backend directly with Python (e.g. to use a
debugger, or because Docker isn't available), here's how. You'll still
need a PostgreSQL server running somewhere reachable (Docker is still the
easiest way to get *just* Postgres — see the snippet below).

```bash
# 1. Start ONLY a Postgres container (skip backend/frontend containers)
docker compose up db

# 2. In a separate terminal, set up a Python virtual environment
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Point the app at that Postgres container. Easiest way: export the
#    same DATABASE_URL your .env file has, or just `export $(cat ../.env
#    | grep -v '^#' | xargs)` to load the whole .env file into your shell.
export DATABASE_URL="postgresql://admin:change-this-to-a-long-random-password@localhost:5432/asset_db"
export JWT_SECRET_KEY="any-random-string-for-local-dev"

# 4. Run the backend with live-reload
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

For the frontend, since there's no build step, you can serve the
`frontend/` folder with literally any static file server:

```bash
cd frontend
python3 -m http.server 8080
# now open http://localhost:8080
```

**One catch:** `frontend/js/api.js`'s `API_URL` is deliberately a *relative*
path (`/api`) — see [Deploying Across Environments](#deploying-across-environments-nginx-reverse-proxy)
above for why. That only resolves correctly when the frontend is served
*behind the nginx reverse proxy* (which is what `docker compose up`
gives you and does the `/api/*` → backend forwarding). A bare
`python3 -m http.server` has no such proxy, so `/api/*` calls will 404
against its own static file server. For this fully-Docker-free mode,
either:
- run `docker compose up frontend db` alongside the steps above so nginx
  still fronts things (simplest — just skip starting `backend` via
  Compose and run it with `uvicorn` instead, as shown), or
- temporarily hardcode `API_URL` back to `http://localhost:8000` in
  `frontend/js/api.js` while working this way, and revert it before
  committing.

## Environment Variables Reference

All of these live in `.env` (copied from `.env.example`, never committed —
see `.gitignore`) and are read by `backend/config.py` into a single typed
`settings` object that every other backend module imports.

| Variable | Default | Purpose |
|----------|---------|---------|
| `ENVIRONMENT` | `development` | `production` enables the startup JWT-secret strength check. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | see `.env.example` | Postgres credentials, shared by the `db` and `backend` services. |
| `DATABASE_URL` | built from the above | Full SQLAlchemy connection string. |
| `JWT_SECRET_KEY` | *(required, no insecure default allowed)* | Signs/verifies session tokens. **Must** be a long random string in production. |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm. |
| `JWT_EXPIRY_HOURS` | `12` | How long a login session stays valid. |
| `CORS_ORIGINS` | localhost variants | Comma-separated list of origins allowed to call the API. |
| `AUTO_INIT_DB` | `true` | If true, runs `create_all()` on startup (creates missing tables). Set `false` in production and use Alembic instead. |
| `AUTO_SEED_DEMO_DATA` | `true` | If true, seeds demo accounts/data on an empty DB at startup. Set `false` in production. |
| `LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL`. |
| `LOG_FORMAT` | `json` | `json` (production/log aggregators) or `text` (readable local dev). |
| `LOGIN_RATE_LIMIT_MAX` | `5` | Max `/auth/login` attempts per IP per window before HTTP 429. |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | `60` | The window (in seconds) the above limit applies over. |
| `ENABLE_API_DOCS` | `true` | Whether `/docs`, `/redoc`, `/openapi.json` exist at all. **Set `false` in Render/cloud** — see the Security Model section below. Also read by the frontend/nginx service (see the table below) as a second, independent layer. |
| `SUPER_ADMIN_USERNAME` | `superadmin` | Login identifier for the hardcoded Super Admin (root) account — see [Roles & Permissions Model](#roles--permissions-model). |
| `SUPER_ADMIN_NAME` | `Super Admin` | Display name for that account (shown in the navbar/profile, same as any other user's `name`). |
| `SUPER_ADMIN_PASSWORD` | *(placeholder, must be changed in production)* | Password for the hardcoded Super Admin. Leaving it empty fully disables that login path. **Must** be a real, unique value in production — the backend refuses to start otherwise (same idea as `JWT_SECRET_KEY`). |

The four below are read by the **`frontend`** service (the nginx reverse
proxy), not the backend — see [Deploying Across Environments](#deploying-across-environments-nginx-reverse-proxy).

| Variable | Default | Purpose |
|----------|---------|---------|
| `FRONTEND_PORT` | `80` | Port nginx listens on inside its own container. |
| `BACKEND_HOST` | `backend` | Hostname nginx proxies `/api/*` requests to. |
| `BACKEND_PORT` | `8000` | Port on that host. |
| `RESOLVER_IP` | `127.0.0.11` | Internal DNS server nginx uses to re-resolve `BACKEND_HOST` on every request. |
| `ENABLE_API_DOCS` | `true` | nginx's own copy of the backend's identically-named flag (see the table above) — blocks `/docs`/`/redoc`/`/openapi.json` at the proxy itself, before the request ever reaches the backend, if either copy is `false`. **Set `false` in Render/cloud.** |
| `ACCOUNT_LOCKOUT_MAX_ATTEMPTS` | `5` | Wrong-password attempts against **the same account** before it's locked, regardless of which IP they came from. |
| `ACCOUNT_LOCKOUT_DURATION_MINUTES` | `15` | How long that per-account lock lasts once triggered. |

## Roles & Permissions Model

Enforced **on the backend** (`deps.py`'s `require_super_admin` /
`require_privileged_role`, plus extra checks inside individual services) —
**never trust the frontend alone**, since anyone can call the API directly
with a tool like `curl` or Postman, bypassing the UI entirely.

- A JWT is issued at login and must be sent as `Authorization: Bearer
  <token>` on every other request.
- `deps.get_current_user` decodes the JWT **and** re-queries the database
  on every single request, so deactivating/deleting a user takes effect
  immediately instead of waiting for their token to expire naturally.
- A Manager can only see/manage users and audit entries in their **own**
  department (enforced server-side from the JWT's `department` claim,
  never from anything the client sends — a Manager can't just edit a
  request to claim a different department).
- Ad-hoc Outsiders never have a department (they're not tied to one), so
  the Ad-Hoc Directory shows the same list to every Manager and Admin
  alike — there's no per-department scoping for it, by design (see
  `services/outsider_service.py`'s comments if you're curious why).

### The hardcoded Super Admin

`super_admin` is treated completely differently from every other role. It
is **not** a row in the `users` table — it's a single fixed identity built
entirely from the `SUPER_ADMIN_USERNAME`/`SUPER_ADMIN_PASSWORD`/
`SUPER_ADMIN_NAME` settings (see [Environment Variables
Reference](#environment-variables-reference) and `backend/config.py`'s
docstring). That design is what makes the following true **structurally**,
not just by convention:

- **Exactly one exists, always.** There's no table row to duplicate, and
  `POST /users` explicitly rejects `role: "super_admin"` as a reserved
  value no matter who's provisioning the account (see
  `services/user_service.py`'s `RESERVED_ROLES`) — anyone who needs the
  same privileges gets the `admin` role instead (see below).
- **It can never be deleted.** `DELETE /users/{id}` only ever operates on
  real `users` rows (`services/user_service.py`'s `delete_user()`); there's
  no row for the Super Admin to be deleted from.
- **It never appears anywhere in the UI.** The User Directory, exports,
  and every other listing all come from `SELECT ... FROM users` — a query
  that structurally can never return this identity.
- **Its password lives only in the environment.** `POST
  /auth/update-password` explicitly rejects any attempt to target it (see
  `services/auth_service.py`'s `update_password()`) — change it by editing
  `SUPER_ADMIN_PASSWORD` and restarting the backend, not through the app.
- **Login is checked first, before the database.** `services/
  auth_service.py`'s `login()` compares the submitted identifier/password
  against `SUPER_ADMIN_USERNAME`/a pre-hashed `SUPER_ADMIN_PASSWORD`
  *before* ever querying `users` — see that function's comments for the
  exact flow, including why an empty `SUPER_ADMIN_PASSWORD` fully disables
  this path rather than accepting a blank password.
- **Its JWT is recognized, not re-validated against the database.**
  `deps.get_current_user` normally re-queries `users` on every request so
  deactivating/deleting an account revokes access immediately (see above)
  — there's no row to re-query for the Super Admin, so its token is simply
  trusted until it expires. To revoke Super Admin access immediately,
  rotate `JWT_SECRET_KEY` and/or unset `SUPER_ADMIN_PASSWORD`, then restart
  the backend.

`admin` exists precisely so you're not stuck using this one hardcoded
identity for everyday work: it's a normal, database-backed account with
**every privilege `super_admin` has** (`deps.py`'s `_FULL_ADMIN_ROLES`
groups them together in every permission check), but it can be created,
renamed, given a new password through the app, and soft-deleted like any
other user — see the seeded demo `admin` account in [Demo Login
Credentials](#demo-login-credentials).

## Database & Migrations (Alembic)

`backend/models.py` is the source of truth for table *shape*; Alembic
tracks how to get an existing database from one shape to the next without
losing data.

```bash
# Inside the backend container (or a local venv with the same DATABASE_URL):
cd backend
docker compose exec backend alembic upgrade head
alembic upgrade head              # apply all migrations
alembic revision --autogenerate -m "add some_column"   # after editing models.py
```

`init_db()` (`Base.metadata.create_all()`) is still safe to leave enabled
for local development — it only creates tables that don't exist yet and
never alters existing ones, so it won't fight with Alembic. In production,
disable it (`AUTO_INIT_DB=false`) and let `alembic upgrade head` be the
only thing that ever changes your schema.

**Current migrations:**
- `0001_baseline_schema.py` — the **only** migration. Creates every table
  in its full, current shape (matching `models.py` exactly) in one file —
  there's no `0002`/`0003`/... chain to apply on top of it. A fresh
  `alembic upgrade head` against an empty database only ever runs this
  one file.

> **Note on history:** this project briefly had an incremental chain
> (`0002_add_account_lockout_fields`, `0003_timezone_aware_datetimes`,
> `0004_add_username_to_users`, `0005_soft_delete_asset_types`) written as
> `models.py` evolved. Those were squashed back into a single
> `0001_baseline_schema.py` for a cleaner fresh-install experience — five
> files (and the schema-drift risk of one of them going missing, as
> happened before) is unnecessary overhead for a project with no shipped
> production data yet.
>
> **If your database was already migrated with the old 0001–0005 chain**
> (check with `alembic current` — if it shows anything other than
> `0001_baseline_schema`), do **not** just run `alembic upgrade head`;
> Alembic will look for migration files that no longer exist and error
> out. Since your tables already match the new baseline's schema exactly,
> just re-point Alembic's bookkeeping at it instead, without touching any
> table:
> ```bash
> alembic stamp 0001_baseline_schema
> ```
> Fresh installs (empty/nonexistent database) don't need this — just run
> `alembic upgrade head` as normal.

**Going forward, every schema change should be its own NEW migration**
(via `alembic revision --autogenerate -m "description"`) layered on top of
`0001_baseline_schema.py` — don't keep hand-editing the baseline itself
once any real data exists anywhere.

**When you add a new column to `models.py`, always write a migration for
it** (either by hand or via `alembic revision --autogenerate`) — don't
rely on `create_all()` alone, since it will never alter an *existing*
table that's missing a new column.

**Running `alembic upgrade head` only needs `DATABASE_URL`.** `backend/alembic/env.py`
reads its own minimal settings object for exactly that one variable — it
deliberately does **not** import `config.py`'s full `Settings` object,
because that object's startup checks refuse to even construct themselves
when `ENVIRONMENT=production` unless `JWT_SECRET_KEY` and
`SUPER_ADMIN_PASSWORD` are *also* already set to real values (see the
Security Model section). Those checks are correct for the running app
(`main.py`), but migrations have nothing to do with either secret, so
requiring them just to run `alembic upgrade head` created a chicken-and-egg
problem: every alembic command failed with a `pydantic.ValidationError`
traceback (`Refusing to start: ENVIRONMENT=production but JWT_SECRET_KEY/
SUPER_ADMIN_PASSWORD is still empty...`) regardless of what you actually
ran it with. If you still see that error, it means `DATABASE_URL` itself
is missing/wrong (or you're on a checkout from before this fix) — check
that first rather than the JWT/Super Admin variables.

## Full API Reference

Full interactive docs (auto-generated from the code, with a "Try it out"
button for every endpoint) are always available at `/docs` (Swagger UI)
once the backend is running. This table is the high-level map:

| Method & Path | Who | Purpose |
|---|---|---|
| `POST /auth/login` | anyone | Exchange email/username + password for a JWT. Rate-limited by IP; also enforces per-account lockout after repeated failures. |
| `GET /auth/me` | logged in | "Who am I?" — fresh profile data for the "My Profile" window. |
| `POST /auth/update-password` | self or Super Admin/Admin | Change a password (self-service requires the current password; a Super Admin resetting someone else's does not). |
| `GET /assets` | logged in | List asset pools. TRUE server-side pagination + search — `?limit=&offset=&search=` (searches pool name). |
| `POST /assets` | Super Admin / Admin | Create a new pool. |
| `GET /assets/{id}/details` | logged in | Full pool detail: stock breakdown, active checkouts, isolated units. |
| `PUT /assets/{id}/quantity` | Super Admin / Admin | Adjust total capacity. |
| `DELETE /assets/{id}` | Super Admin / Admin | Soft-delete a pool. |
| `POST /assets/{id}/exception` | Super Admin / Admin | Flag a serial as under repair/stolen. |
| `POST /assets/{id}/exception/{eid}/recall` | Super Admin / Admin | Return an isolated unit to service. |
| `POST /assets/{id}/checkin` | Super Admin / Admin | Reconcile newly-found stock. |
| `POST /assets/{id}/checkout_advanced` | Super Admin / Admin / Manager | Dispatch units to a Staff/Customer/Outsider. |
| `POST /assets/import` | Super Admin / Admin | Bulk-create pools from a CSV (max 5 MiB). |
| `GET /users` | Super Admin / Admin / Manager | Directory listing (Managers see their own department + all customers). TRUE server-side pagination + search — `?limit=&offset=&search=` (searches name, email, role, department, department_role). |
| `POST /users` | Super Admin / Admin / Manager | Provision a new login. |
| `GET /users/me/items` | logged in | Self-service: my own checked-out items. |
| `GET /users/me/items/export` | logged in | Self-service download of the above as `?format=csv` or `?format=pdf`. |
| `GET /users/{id}/items` | Super Admin / Admin / Manager | Someone else's custody ledger. |
| `GET /users/{id}/items/export` | Super Admin / Admin / Manager | Download one specific user's custody ledger (CSV/PDF). |
| `GET /users/export` | Super Admin / Admin / Manager | Bulk download of every active checkout across every user in the caller's scope (CSV/PDF). |
| `DELETE /users/{id}` | Super Admin / Admin | Soft-delete an account. |
| `GET /outsiders` | Super Admin / Admin / Manager | Ad-Hoc directory listing. TRUE server-side pagination + search — `?limit=&offset=&search=` (searches name, contact details, company). |
| `GET /outsiders/{id}/items` | Super Admin / Admin / Manager | An outsider's custody ledger. |
| `GET /outsiders/{id}/items/export` | Super Admin / Admin / Manager | Download one specific outsider's custody ledger (CSV/PDF). |
| `GET /outsiders/export` | Super Admin / Admin / Manager | Bulk download of every active checkout across every ad-hoc individual (CSV/PDF). |
| `POST /checkouts/{id}/return` | Super Admin / Admin / Manager | Process a (partial or full) return. |
| `GET /checkouts/overdue` | Super Admin / Admin / Manager | Dashboard alert feed of overdue checkouts. |
| `GET /audit-logs` | Super Admin / Admin / Manager | TRUE server-side paginated audit ledger — `?limit=&offset=` (no search param; see [Feature Tour](#feature-tour)). |
| `POST /audit-logs/export` | Super Admin / Admin / Manager | Enqueue a background export job — `?format=csv` (default) or `?format=pdf`, plus optional `?start_date=&end_date=`. Returns `{task_id, status}` immediately; does not return the file. |
| `GET /audit-logs/export/{task_id}/status` | Super Admin / Admin / Manager | Poll a job's progress — `{state, ready, error?}`. |
| `GET /audit-logs/export/{task_id}/download` | Super Admin / Admin / Manager | Download the finished file once `status` reports `SUCCESS` (409 if not ready yet, 404 if the task_id is unknown/expired). |
| `GET /health` | anyone | Trivial liveness check for Docker/orchestrators. |

**Every export endpoint** accepts `?format=csv` or `?format=pdf` and
responds with a real file download (`Content-Disposition: attachment`) —
you can test any of them straight from `/docs`, or with `curl -O -J` and
a bearer token.

## File & Function Reference

Route handlers in `api/*.py` are intentionally thin — they just parse the
request and call the matching function in `services/*.py`, which is where
the actual logic lives. Use this section as a map when you need to find
"where does X happen?" without grepping the whole repo.

### Backend — App Core

#### `backend/main.py`
- `on_startup()` — FastAPI startup hook; runs `init_db()`/`seed_db()` if
  their `AUTO_*` settings flags are enabled.
- `custom_openapi()` — customizes the generated OpenAPI schema (used by
  `/docs`).
- `health_check()` — `GET /health`.
- Also where the middleware stack (`RateLimitMiddleware`,
  `RequestContextMiddleware`, `CORSMiddleware`, `SecurityHeadersMiddleware`)
  and all API routers are registered — if you add a new `api/*.py` file,
  you register its router here.

#### `backend/config.py`
- `class Settings` — the single source of truth for every environment
  variable, loaded once into a shared `settings` object every other module
  imports (`from config import settings`).
- `Settings.cors_origin_list` — splits the comma-separated `CORS_ORIGINS`
  string into a Python list.
- `Settings.is_production` — `True` when `ENVIRONMENT=production`.
- `Settings._enforce_prod_jwt_secret()` — validator that **refuses to
  start** if running in production with a placeholder/weak
  `JWT_SECRET_KEY`.
- `Settings._enforce_prod_super_admin_password()` — same idea, for
  `SUPER_ADMIN_PASSWORD` (the hardcoded Super Admin's password — see
  Roles & Permissions Model).

#### `backend/database.py`
- `init_db()` — `Base.metadata.create_all()`; creates any tables that
  don't exist yet.
- `get_db()` — FastAPI dependency that yields a SQLAlchemy `Session` and
  always closes it afterwards.
- `seed_db()` — inserts demo accounts/asset pools **only if the database
  is empty**. Note there's no `super_admin` row seeded here — that
  identity is hardcoded via environment variables (see Roles &
  Permissions Model); the seeded top-privilege demo account is `admin`.

#### `backend/models.py`
- `utc_now()` — the one place "the current time" is generated app-wide,
  always timezone-aware UTC (never plain `datetime.now()`).
- `class AssetType` — an inventory pool (name, total_quantity,
  custom_fields).
- `class AssetException` — a single serial number pulled out of
  circulation (repair/lost/stolen).
- `class AuditLog` — an append-only record of every meaningful action.
- `class User` — a login account (Admin/Manager/Staff/Customer — never
  `super_admin`, which is reserved for the hardcoded root identity and is
  never a database row), including `failed_login_attempts`/`locked_until`
  for brute-force lockout.
- `class Outsider` — an ad-hoc external person with no login, who can
  still have custody of assets.
- `class AssetCheckout` — one dispatch of N units to a User or Outsider,
  with a due date and return tracking.

#### `backend/security.py`
- `hash_password(plain_password)` — Argon2id hash of a plaintext password.
- `verify_password(plain_password, hashed_password)` — constant-time
  comparison against a stored hash.
- `validate_password_strength(password)` — enforces the password
  complexity policy; raises with a specific reason on failure.
- `create_access_token(user)` — issues a signed JWT for a logged-in user.
- `decode_access_token(token)` — verifies signature + expiry and returns
  the token's claims.
- `SUPER_ADMIN_ID` / `SUPER_ADMIN_ROLE` — constants identifying the
  hardcoded Super Admin's JWT `sub`/`role` claims.
- `super_admin_password_hash()` / `SUPER_ADMIN_PASSWORD_HASH` — hashes
  `settings.SUPER_ADMIN_PASSWORD` once at startup (`None` if unset).
- `super_admin_principal()` — a `User`-shaped stand-in for the Super Admin
  so `create_access_token()` can issue it a token like any other account.

#### `backend/deps.py`
- `get_current_user(...)` — FastAPI dependency: decodes the bearer token
  AND re-queries the DB to confirm the account is still active/not
  deleted.
- `require_super_admin(user)` — dependency that 403s unless `role` is
  `super_admin` or `admin` (see `_FULL_ADMIN_ROLES`).
- `require_privileged_role(user)` — dependency that 403s unless `role` is
  `super_admin`, `admin`, or `manager`.
- Also where the hardcoded Super Admin's JWT is recognized and exempted
  from the database re-query every other account gets (see Roles &
  Permissions Model).

#### `backend/logging_config.py`
- `class RequestIdLogFilter` — attaches the current request's correlation
  ID to every log record.
- `class JsonFormatter` — renders each log record as one JSON line.
- `class TextFormatter` — renders each log record as one human-readable
  line (for local dev).
- `configure_logging(settings)` — wires the root logger up with the
  above, called once at startup.

### Backend — Middleware (`backend/middleware/`)

- **`request_context.py`** — `class RequestContextMiddleware`
  assigns/reuses an `X-Request-ID` per request, stores it for the logger,
  echoes it back on the response.
- **`rate_limit.py`** — `class RateLimitMiddleware`, an in-memory sliding-
  window limiter applied only to `POST /auth/login`.
- **`security_headers.py`** — `class SecurityHeadersMiddleware` stamps
  `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and a
  restrictive `Permissions-Policy` onto every response.

### Backend — API Routes (`backend/api/`)

- **`api/auth.py`** — `login`, `get_my_profile`, `update_password`.
- **`api/assets.py`** — `create_asset_type`, `list_assets`,
  `get_asset_details`, `update_asset_quantity`, `delete_asset_type`,
  `flag_asset_exception`, `recall_asset_exception`, `checkin_asset`,
  `checkout_advanced`, `import_assets_from_csv`.
- **`api/users.py`** — `create_user`, `get_users`,
  `get_my_assigned_items`, `export_my_assigned_items`,
  `export_all_users`, `get_user_assigned_items`,
  `export_user_assigned_items`, `delete_user`.
- **`api/outsiders.py`** — `get_outsiders`, `export_all_outsiders`,
  `get_outsider_assigned_items`, `export_outsider_assigned_items`.
- **`api/checkouts.py`** — `return_checkout`, `get_overdue_checkouts`.
- **`api/audit.py`** — `get_audit_logs`, `export_audit_logs`.

### Backend — Services (`backend/services/`) — the business logic layer

- **`services/asset_service.py`** — `create_asset_type`, `list_assets`
  (now accepts a `search` param, narrowing to pool name — see
  `services/search_utils.py`), `get_asset_details`, `update_asset_quantity`,
  `delete_asset_type`, `flag_asset_exception`, `recall_asset_exception`,
  `checkin_asset`, `checkout_advanced`, `import_assets_from_csv`.
  `MAX_CSV_UPLOAD_BYTES` caps upload size.
- **`services/auth_service.py`** — `login(db, req)` checks the hardcoded
  Super Admin identifier/password FIRST, before ever querying `users`;
  otherwise verifies credentials against the database, enforces
  per-account lockout, and issues a JWT. `_DUMMY_PASSWORD_HASH` keeps the
  "no such account" response timing-consistent with "wrong password";
  `get_profile(db, current_user)` backs `GET /auth/me` (rehydrated
  straight from JWT claims for the Super Admin, since it has no row to
  query); `update_password` changes a password and clears any lockout as a
  side effect, and rejects any attempt to target the Super Admin (whose
  password only lives in `SUPER_ADMIN_PASSWORD`).
- **`services/checkout_service.py`** — `return_checkout` processes a
  partial/full return (and records who the equipment came from in the
  audit entry); `list_overdue_checkouts` backs the overdue alert feed.
- **`services/user_service.py`** — `_derive_username` turns an email's
  local-part into a unique username, steering clear of the reserved Super
  Admin username too; `RESERVED_ROLES` blocks `role: "super_admin"` from
  ever being assigned to a database-backed account; `create_user`,
  `list_users` (now accepts a `search` param, narrowing across name/
  email/role/department/department_role), `get_my_assigned_items`,
  `get_user_assigned_items`, `delete_user` (which also rejects the Super
  Admin's sentinel id); the export trio `export_my_assigned_items`,
  `export_user_assigned_items`, `export_all_users_items`.
- **`services/outsider_service.py`** — `list_outsiders` (now accepts a
  `search` param, narrowing across name/contact_details/company),
  `get_outsider_assigned_items`; the export pair
  `export_outsider_assigned_items`, `export_all_outsiders_items`.
- **`services/audit_service.py`** — `get_audit_logs` (TRUE server-side
  paginated listing); `_filtered_audit_logs_query` (shared filter logic);
  `export_audit_logs_csv` (streamed); `export_audit_logs_pdf`.
- **`services/search_utils.py`** — `apply_search_filter(query, search,
  columns)`, the shared helper behind the `search` param on `GET /assets`,
  `GET /users`, and `GET /outsiders`: an OR-across-columns, case-
  insensitive `ILIKE`, with `_escape_like()` neutralizing literal `%`/`_`
  characters in what someone typed so they aren't misread as SQL wildcards.
- **`services/export_service.py`** — `csv_safe_cell` (neutralizes
  formula-injection payloads), `build_csv_bytes`, `build_pdf_bytes` — the
  shared CSV/PDF machinery every exporter in the app uses.
- **`services/stock.py`** — `recalculate_asset_stock(db, asset)`, the
  single shared formula for `Available = Total − Outbound − Isolated`,
  called after every mutation that could change it.

### Backend — Schemas (`backend/schemas/`)

Pure Pydantic request/response models, no logic:
- **`schemas/auth.py`** — `LoginRequest`, `PasswordUpdateRequest`
  (enforces password strength via a `field_validator`).
- **`schemas/assets.py`** — asset/checkout request bodies, including the
  server-side due-date min/max check.
- **`schemas/users.py`** — `UserCreateRequest` (also enforces password
  strength).
- **`schemas/checkouts.py`** — `ReturnRequest`.

### Frontend — Core (`frontend/js/`)

- **`js/api.js`** — `apiRequest(path, options)`, the ONE function that
  calls `fetch()`; attaches the JWT header, parses JSON, throws a
  normalized `Error` on failure. `formatErrorDetail(detail)` turns
  FastAPI's `detail` field (string OR validation-error array) into one
  readable message.
- **`js/auth.js`** — `parseJwt`, `getSession`, `logout`, `login`,
  `currentPageName`, `checkAccess`, `redirectByUserRole`,
  `startIdleWatchdog` (auto-logout after inactivity).
- **`js/dashboard.js`** — `refreshDashboard()` calls every component's
  `load*()` function together.
- **`js/main.js`** — `wireDelegatedEvents()` (one `click` listener on
  `document`, dispatched by `data-action` attributes),
  `wireTableControls()`, `wireCsvDragAndDrop(fileInput, form)`.
- **`js/ui.js`** — shared, framework-free UI helpers:
  `openModal`/`closeModal` (toggle `hidden`/`flex` together — see the
  in-code comment if you're ever tempted to "simplify" this), `escapeHtml`
  (the ONE function standing between server data and DOM injection —
  used everywhere a server value is rendered), `switchTab`, `toggleRoute`,
  `toggleCapacityEdit`, `statusBadge`. Two small pagination toolkits live
  here side by side: the CLIENT-side one (`tableState`, `registerRenderer`,
  `filterAndPaginate`, `renderPaginationBar`, `setSearch`, `setPerPage`,
  `changePage`) — now used only by My Items, which filters/pages an
  already-downloaded array in memory — and the SERVER-side one
  (`debounce`, `renderServerPaginationBar`) shared by the Asset/User/
  Outsider directories and the Audit Ledger, each of which keeps its own
  small `{ page, perPage, search, total }` state object in its own
  component file and re-fetches from the API on every change instead.

### Frontend — Components (`frontend/js/components/`) — one file per feature area

- **`assets.js`** — `loadAssets` (TRUE server-side search + pagination —
  `assetsState` + `setAssetsSearch`/`setAssetsPerPage`/`changeAssetsPage`,
  the same pattern as `audit.js`'s `auditState`, extended here), due-date
  bounds helpers, `openDispatchModal`, `submitDispatchForm`,
  `openPropsModal`, `recallException`, `saveCapacity`,
  `submitExceptionForm`, `submitCreatePoolForm`, `submitCsvImportForm`,
  `deleteAssetPool` (Super Admin only — wired both to a row-level "Delete"
  button on the Asset Inventory table and to a "Delete Asset Pool" button
  in the Properties Hub modal itself; the backend endpoint already
  existed, this just added the missing UI to reach it).
- **`audit.js`** — `loadAuditLogs` (TRUE server-side pagination —
  `auditState` + `changeAuditPage`/`setAuditPerPage`, sharing
  `js/ui.js`'s `renderServerPaginationBar()` with `assets.js`/`users.js`/
  `outsiders.js` below), `exportAuditLogs(format)` (CSV or PDF).
- **`custody.js`** — `getCurrentCustodyEntity()` (lets other modules know
  which user/outsider's ledger is open), `openCustodyModal`,
  `processReturn`, selection/bulk-return helpers.
- **`exports.js`** — `exportMyItems`, `exportCustodyItems`,
  `exportAllUsers`, `exportAllOutsiders` — all built on one shared
  `downloadExport()` helper that reads the real filename off the
  response's `Content-Disposition` header.
- **`myitems.js`** — `loadMyItems`/`renderMyItemsTable`, the
  Staff/Customer self-service view.
- **`outsiders.js`** — `loadOutsiders` (TRUE server-side search +
  pagination — `outsidersState` + `setOutsidersSearch`/
  `setOutsidersPerPage`/`changeOutsidersPage`).
- **`overdue.js`** — `loadOverdueAlerts`.
- **`profile.js`** — `openProfileModal`, `submitChangePasswordForm`,
  `setProfileFormMessage`.
- **`users.js`** — `loadUsers` (TRUE server-side search + pagination —
  `usersState` + `setUsersSearch`/`setUsersPerPage`/`changeUsersPage`;
  also separately re-fetches an unfiltered roster to populate the
  Dispatch drawer's "Assign To > Staff Member" dropdown, since that list
  must never be narrowed by whatever's currently typed into the User
  Directory's search box), `deleteProfile`, `submitCreateUserForm`.

## Making Changes Safely (A Guide For Beginners)

This section is a walkthrough of the **safe pattern** for common changes,
so you don't have to reverse-engineer it from scratch. Follow the same
shape every time and you'll rarely break something unrelated.

### The golden rule: work outward from the database, one layer at a time

```
1. models.py         (does the DATA need to change shape?)
2. alembic migration  (if #1 changed: write the migration)
3. schemas/*.py        (does the REQUEST/RESPONSE shape need to change?)
4. services/*.py        (where the actual logic goes)
5. api/*.py               (the thin route that calls #4)
6. frontend/js/*.js         (call the new/changed endpoint)
7. frontend/*.html           (add any new buttons/fields/markup)
```

You don't always need all 7 steps — a pure UI tweak might only touch #7,
a backend-only bugfix might only touch #4. But when you DO need several of
them, do them **in this order**, and test after each layer if you can
(see [Testing Your Changes](#testing-your-changes)).

### Example: "Add a `notes` field to Asset Pools"

1. **`models.py`** — add `notes = Column(String, nullable=True)` to
   `AssetType`.
2. **Migration** — `alembic revision --autogenerate -m "add notes to asset_types"`,
   then check the generated file actually looks right before running
   `alembic upgrade head`.
3. **`schemas/assets.py`** — add `notes: Optional[str] = None` to whichever
   request model creates/updates a pool.
4. **`services/asset_service.py`** — read `payload.notes` and set it on
   the `AssetType` row in `create_asset_type()`/`update_asset_quantity()`
   (or wherever makes sense).
5. **`api/assets.py`** — usually needs NO change at all, since routes just
   pass the whole validated `payload` object through to the service.
6. **`frontend/js/components/assets.js`** — include `notes` in whatever
   object `submitCreatePoolForm()` sends, and display it in
   `renderAssetsTable()`/`openPropsModal()`.
7. **`frontend/admin.html`** — add an `<input>` for it in the "Register
   New Inventory Pool" form.

### Example: "Add a brand-new endpoint" (e.g. `GET /assets/{id}/history`)

1. Decide which `services/*.py` file it belongs in (asset-related →
   `asset_service.py`) and write the actual query/logic function there
   first, in isolation — you can test it directly in a Python shell before
   wiring up any HTTP plumbing at all (see
   [Testing Your Changes](#testing-your-changes)).
2. Add a thin route in the matching `api/*.py` file that calls it — copy
   the shape of a neighboring route in the same file (same
   `Depends(get_db)`, same `Depends(require_...)` pattern).
3. If it needs a new Pydantic model for its request body, add it to the
   matching `schemas/*.py` file.
4. Register nothing extra in `main.py` — routers are already wired up
   there; a new function on an existing router's file is picked up
   automatically the next time the app restarts.
5. Add the frontend call + UI last, once you've confirmed the endpoint
   works from `/docs` directly.

### Example: "Add a new page/dashboard tab"

The four dashboard HTML files (`admin.html`, `manager.html`, `staff.html`,
`customer.html`) are the pattern to copy from — they all share the same
navbar/modal/tab structure. To add a new tab:
1. Copy an existing `<section>` block that's structured like a tab panel,
   give it a new `id`, and add a matching nav button with
   `data-action="switch-tab"` (see `ui.js`'s `switchTab()`).
2. Create a new file under `frontend/js/components/` for its logic,
   following the `load*()`/`render*Table()` naming pattern every other
   component uses.
3. Wire its `load*()` function into `js/dashboard.js`'s
   `refreshDashboard()` so it populates automatically when the dashboard
   loads.
4. Wire up any buttons via `data-action` attributes and a matching entry
   in `main.js`'s `CLICK_ACTIONS` map — **don't** add individual
   `addEventListener()` calls scattered around; the whole app uses one
   central dispatch table on purpose, so anyone can find every click
   handler in one place.

### Things to be careful about

- **Never hard-delete a `User`, `AssetType`, or anything else with
  history attached.** Always soft-delete (`is_deleted = True`,
  `deleted_at = utc_now()`) — a hard delete either crashes on a foreign
  key or silently destroys the audit trail for anything that referenced
  it.
- **Never call `datetime.datetime.utcnow()` or `datetime.datetime.now()`
  directly.** Always `from models import utc_now` and call that instead —
  see `models.py`'s big comment block on timezone handling for why this
  matters.
- **Never build a raw SQL string with an f-string/`%`/`.format()`.** This
  codebase is 100% SQLAlchemy ORM queries on purpose — that's what makes
  SQL injection "not applicable" as a risk here. Keep it that way.
- **Never insert a server-supplied string into the DOM without
  `escapeHtml()`** (`js/ui.js`). Every existing `render*Table()` function
  already does this — copy that pattern for any new one.
- **Never log a password**, hashed or plain, anywhere — not even at
  `DEBUG` level.
- **Recalculate stock after any mutation that could change it.** If you
  add a new way for units to enter/leave a pool (a new checkout type, a
  new exception type, etc.), call
  `services/stock.py -> recalculate_asset_stock(db, asset)` afterwards,
  same as every existing mutation does.
- **Write an audit log entry for anything a Super Admin/Manager does that
  changes state.** Copy the `db.add(models.AuditLog(...))` pattern from a
  neighboring function in the same service file.

## Testing Your Changes

There's no bundled automated test suite in this project yet (see
[Suggested Future Features](#suggested-future-features) for adding one) —
here's how to verify a change works in the meantime.

### Fastest option: Swagger UI (`/docs`)

With the full stack running via `docker compose up`, open
`http://localhost:8080/docs` (proxied through nginx — see
[Deploying Across Environments](#deploying-across-environments-nginx-reverse-proxy)).
If you're running the backend standalone with `uvicorn` (no nginx in
front), it's at `http://localhost:8000/docs` instead. Every
endpoint is listed with a "Try it out" button, a place to paste your JWT
(click the padlock icon, or the green "Authorize" button at the top), and
a live response. This is the quickest way to confirm a backend change
works without touching the frontend at all.

### Manual functional testing with a throwaway SQLite database

If you want to test a chain of API calls end-to-end without touching your
real Postgres data, you can point the app at a temporary SQLite file
instead — no Docker, no Postgres needed:

```bash
cd backend
pip install httpx --break-system-packages   # only needed for this test client

DATABASE_URL="sqlite:////tmp/test.db" python3 << 'EOF'
import os
os.environ["DATABASE_URL"] = "sqlite:////tmp/test.db"
import database
database.init_db()
database.seed_db()

from fastapi.testclient import TestClient
from main import app
client = TestClient(app)

# Log in as the demo Super Admin
r = client.post("/auth/login", json={"identifier": "r.adeyemi@corp.io", "password": "SuperAdmin123!"})
token = r.json()["token"]
headers = {"Authorization": f"Bearer {token}"}

# Try whatever you just built, e.g.:
r = client.get("/assets", headers=headers)
print(r.status_code, r.json())
EOF

rm -f /tmp/test.db   # clean up when you're done
```

This is exactly the pattern used to verify the exports, audit trail, and
account-lockout features described in this README while they were built —
copy/adapt the snippet above for whatever endpoint you're changing.

### Frontend

Since there's no build step, just refresh the page in your browser after
saving a `.js`/`.html` file. Open your browser's DevTools Console while
testing — `js/api.js` throws a real `Error` (with the backend's message)
on any failed request, which will show up there if something goes wrong
silently in the UI.

## Security Model

A quick reference of what's already handled, so you don't accidentally
"fix" something that's already correct, or skip something that matters
when adding a new feature.

- ✅ Passwords hashed with **Argon2id** (`pwdlib`), never stored/logged in
  plain text.
- ✅ Password complexity policy enforced server-side on every
  *set*-password path (never on login, which must always be allowed to
  fail generically).
- ✅ **JWT** sessions; the backend re-validates the user's
  `is_active`/`is_deleted` state on *every* request (instant revocation,
  not "wait for the token to expire").
- ✅ Startup **refuses to boot in production** with a placeholder/short
  JWT secret (`config.py`).
- ✅ Role-based access control enforced **server-side** for every
  privileged action (never just hidden in the UI).
- ✅ **Soft deletes** everywhere a row is referenced by audit/history, so
  the audit trail can never be silently destroyed by a delete.
- ✅ SQL injection: not applicable — 100% SQLAlchemy ORM queries, zero raw
  SQL string interpolation anywhere in the codebase.
- ✅ Stored XSS: the frontend consistently escapes every server-supplied
  string before inserting it into the DOM (`escapeHtml()` in `ui.js`).
- ✅ CSV/"formula injection" protection on every exported CSV
  (`services/export_service.py -> csv_safe_cell()`).
- ✅ Secrets (`JWT_SECRET_KEY`, `POSTGRES_PASSWORD`) live only in a
  git-ignored `.env`, never hardcoded in source or `docker-compose.yml`.
- ✅ Row-level locking (`with_for_update()`) on the checkout path prevents
  a race condition from overselling a pool under concurrent requests.
- ✅ Pagination limits (`limit`/`offset` + hard `MAX_LIMIT` caps) on every
  listing endpoint, preventing unbounded-response-size abuse.
- ✅ Login rate-limited **per IP** (`middleware/rate_limit.py`) **and**
  **per account** (`User.failed_login_attempts`/`locked_until`) — the two
  work together: IP limiting slows a single source hammering many
  accounts, account lockout stops one account being brute-forced from
  many sources.
- ✅ Login is timing-safe against username enumeration — a nonexistent
  identifier still runs a full password-hash comparison (against a
  precomputed dummy hash) so it can't be distinguished, by response time
  alone, from "wrong password for a real account" (`auth_service.py`'s
  `_DUMMY_PASSWORD_HASH`).
- ✅ Standard defensive response headers (`X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`).
- ✅ A real **`Content-Security-Policy`**, tuned against the frontend's
  actual CDN/script/font usage rather than a generic copy-pasted policy —
  see `nginx/default.conf.template`'s `Content-Security-Policy` header and
  its accompanying comment for the reasoning behind each directive.
- ✅ Exactly one **Super Admin**, hardcoded via environment variables
  rather than a database row — it can never be created, edited, or deleted
  through the app, and never appears in the User Directory or any other
  listing. See [Roles & Permissions Model](#roles--permissions-model).
- ✅ Backend container runs as an unprivileged user, not root.
- ✅ Structured, correlated logging for every login attempt and password
  change (never the password itself).
- ✅ Interactive API docs (`/docs`, `/redoc`, `/openapi.json`) can be fully
  disabled via `ENABLE_API_DOCS=false` — gated independently at **both**
  the backend (FastAPI never generates/serves the schema at all, not just
  a hidden UI) and nginx (blocks the request before it ever reaches the
  backend). Defaults to `true` for local-dev convenience; **set `false`**
  in Render/cloud (`render.yaml` already does this). See `config.py`'s
  `ENABLE_API_DOCS` docstring and the Environment Variables Reference
  above.

**Known trade-off, left as-is:** the frontend stores the JWT in
`localStorage` (see `frontend/js/auth.js`'s comment) rather than an
`httpOnly` cookie. This is a common, reasonable choice for a same-origin
SPA without a token-refresh flow, but it does mean a successful XSS
elsewhere in the page could read the token. Moving to `httpOnly` cookies
would need CSRF-token handling added at the same time — a bigger
architectural change, listed in
[Suggested Future Features](#suggested-future-features) instead of
changed silently.

## Running In Production

A checklist before you deploy this anywhere real:

- [ ] `ENVIRONMENT=production` in your `.env` (this alone makes the
      backend **refuse to start** if `JWT_SECRET_KEY` is still a
      placeholder or too short — see `config.py`).
- [ ] Generate and set a real `JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, and
      `SUPER_ADMIN_PASSWORD` (this alone makes the backend **refuse to
      start** if `SUPER_ADMIN_PASSWORD` is still empty/placeholder or too
      short — see `config.py`).
- [ ] `AUTO_INIT_DB=false` and `AUTO_SEED_DEMO_DATA=false` — run
      `alembic upgrade head` as its own explicit deploy step instead, and
      never create the public demo accounts against a real database.
- [ ] Set `CORS_ORIGINS` to your real frontend domain(s) only.
- [ ] Set `ENABLE_API_DOCS=false` for **both** the backend and frontend
      services (same `.env` key drives both locally; `render.yaml` already
      sets `false` for both services in Render). Confirm it worked by
      requesting `/docs` on your deployed URL and `/openapi.json` directly
      against the backend if it's ever reachable from anywhere but
      nginx — both should return a plain `404`, not a docs page or schema.
- [ ] This app already reverse-proxies internally via nginx (see
      [Deploying Across Environments](#deploying-across-environments-nginx-reverse-proxy)),
      but that nginx layer does **not** terminate HTTPS itself. Put TLS
      termination in front of it — a managed platform's own edge/load
      balancer (Render does this automatically), or a cloud load balancer
      / cert-manager setup if you're self-hosting nginx. This app doesn't
      set `Strict-Transport-Security` itself — see
      `middleware/security_headers.py`'s docstring for why that belongs at
      the TLS-terminating layer, not here.
- [ ] Drop `--reload` from the backend's `uvicorn` command and run with
      multiple `--workers` instead (see `backend/Dockerfile`'s comment).
- [ ] Consider swapping the in-memory login rate limiter for a
      Redis-backed one if you run more than one backend replica (see
      `middleware/rate_limit.py`'s docstring).
- [ ] Review and tighten `ACCOUNT_LOCKOUT_MAX_ATTEMPTS` /
      `ACCOUNT_LOCKOUT_DURATION_MINUTES` and
      `LOGIN_RATE_LIMIT_MAX`/`LOGIN_RATE_LIMIT_WINDOW_SECONDS` for your
      actual expected traffic pattern.
- [ ] Set up a real backup schedule for the Postgres volume — this
      project doesn't include one, since backup strategy is very
      deployment-specific (managed Postgres providers usually handle this
      for you automatically).

## Suggested Future Features

Small, well-scoped follow-ups if you want to keep extending this project:

- **An automated test suite** (`pytest` + `TestClient` + a throwaway
  SQLite or test-Postgres database) — see
  [Testing Your Changes](#testing-your-changes) for the manual pattern
  this would formalize.
- **Redis-backed rate limiting** (e.g. `slowapi` or `fastapi-limiter`) if
  the backend is ever scaled to multiple workers/replicas, so all
  instances share one counter instead of each enforcing its own limit
  independently.
- **`restore_user()` / `POST /users/{id}/restore`** — undo a soft-delete
  within a grace period, with a `deleted_by` column recording who
  performed the original deletion (good first Alembic migration exercise).
- **Case-insensitive login** (`func.lower()` comparison + a matching
  unique index) so `T.Okafor@corp.io` and `t.okafor@corp.io` are treated
  as the same account.
- **`Strict-Transport-Security` (HSTS)**, set at your TLS-terminating
  reverse proxy once deployed with HTTPS. (A real `Content-Security-Policy`
  is no longer on this list — see `nginx/default.conf.template`, which now
  sets one tuned against the frontend's actual CDN/script usage.)
- **Email notifications** for overdue checkouts — `GET /checkouts/overdue`
  is a natural data source for a scheduled job that emails Managers a
  daily digest.
- **`httpOnly` cookie sessions + CSRF tokens**, replacing the current
  `localStorage`-based JWT storage (see the trade-off noted in
  [Security Model](#security-model)).
- **OpenTelemetry tracing** — the request-ID/structured-logging
  foundation (`middleware/request_context.py`, `logging_config.py`) is a
  natural stepping stone toward full distributed tracing if this app ever
  calls out to other services.
- **Scheduled/async large exports** — today's exports are built
  synchronously in one request; if directories grow very large, a
  background-job + "email me the file when it's ready" pattern would
  scale better than holding the request open.

## Troubleshooting

- **Login (or literally any `/api/*` call) fails with `405 Method Not
  Allowed`, and the response body is just `{"detail": "Method Not
  Allowed"}`** — this means nginx is forwarding requests to the backend
  with the wrong path (commonly, every request collapsing down to just
  `/`, which only has a `GET` handler). This is a well-known nginx
  gotcha: `proxy_pass`'s usual "trailing slash strips the matched
  `location` prefix" behavior **only works when the upstream address is a
  static string** — it silently stops working the moment that address is
  a *variable* (which `nginx/default.conf.template`'s `/api/` block uses,
  so nginx re-resolves `BACKEND_HOST` on every request instead of caching
  a possibly-stale IP). The fix already in this repo uses an explicit
  `rewrite ^/api/(.*)$ /$1 break;` before `proxy_pass` instead of relying
  on that trick — if you ever edit that `location /api/` block, keep the
  `rewrite` line, or `/api/*` requests will start silently arriving at the
  backend as just `/` again. Rebuild the frontend image after any nginx
  config change: `docker compose build --no-cache frontend && docker
  compose up -d --force-recreate frontend`.
- **"Refusing to start: ENVIRONMENT=production but JWT_SECRET_KEY is
  still a placeholder..."** — expected and intentional (see `config.py`).
  Generate a real secret: `python3 -c "import secrets;
  print(secrets.token_hex(32))"` and set it in `.env`.
- **Backend crash-loops on `docker compose up`** — check `db`'s
  healthcheck passed first (`docker compose logs db`); the backend waits
  for it (`depends_on: condition: service_healthy`) but a bad
  `POSTGRES_PASSWORD`/`DATABASE_URL` mismatch will still fail the
  connection.
- **Getting `429 Too Many Requests` while testing login repeatedly** —
  that's the IP-based rate limiter (`LOGIN_RATE_LIMIT_MAX` /
  `LOGIN_RATE_LIMIT_WINDOW_SECONDS` in `.env`); wait out the window or
  raise the limit locally while developing.
- **Getting `423 Locked` when logging in** — that's the per-account
  lockout (`ACCOUNT_LOCKOUT_MAX_ATTEMPTS` consecutive wrong passwords
  against that specific account). Wait out
  `ACCOUNT_LOCKOUT_DURATION_MINUTES`, or have a Super Admin reset that
  account's password (`POST /auth/update-password`), which clears the
  lockout immediately.
- **Logs look like dense JSON and are hard to read locally** — set
  `LOG_FORMAT=text` in your `.env` for a more human-friendly single-line
  format while developing.
- **"Current password is incorrect" when changing your own password** —
  the "My Profile" window's Change Password form always requires your
  actual current password. If you (as a Super Admin) instead need to
  reset a *different*, e.g. locked-out, user's password, that flow
  doesn't require it — see `services/auth_service.py -> update_password()`.
- **A modal isn't centered / looks misplaced** — every modal's wrapper
  toggles `hidden`/`flex` together in `js/ui.js`'s `openModal()`/
  `closeModal()`; if you're building a new modal, copy an existing one's
  markup (`fixed inset-0 ... hidden items-center justify-center`) exactly
  rather than writing it from scratch, so it inherits this behavior.
- **An export button downloads an empty/near-empty file** — check the
  scope: a Manager's bulk exports only include their own department (plus
  all Customers); if you expect to see a specific user's data, confirm
  they're actually in that department, or log in as the Super Admin to
  export everyone.
