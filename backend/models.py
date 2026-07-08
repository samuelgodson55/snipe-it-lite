"""
models.py
---------
SQLAlchemy ORM table definitions for the Snipe-IT Lite asset registry.

Tables:
  AssetType       - a "pool" of an identical asset (e.g. "MacBook Pro 14 M3")
  AssetException  - a single serial number pulled out of a pool because it's
                    under repair or missing/stolen
  AuditLog        - append-only log of every meaningful action taken
  User            - internal staff/manager/admin accounts that can log in
  Outsider        - external, non-employee people assets can be loaned to
  AssetCheckout   - one active or historical loan of N units of an AssetType
                    to either a User or an Outsider

TIMEZONE HANDLING (beginner-friendly note)
-------------------------------------------
Every timestamp column below is declared `DateTime(timezone=True)`. On
PostgreSQL that maps to a `TIMESTAMPTZ` column instead of a plain
`TIMESTAMP`. The difference matters a lot in practice:

  - A plain `TIMESTAMP` ("naive") column has NO idea what timezone the
    numbers inside it represent. If your app server and your database
    server ever run in different timezones (or one of them changes), you
    silently get wrong answers to "is this checkout overdue yet?" or
    "when exactly was this audit entry logged?".
  - A `TIMESTAMPTZ` ("timezone-aware") column always stores/returns values
    that unambiguously refer to a single instant in time (Postgres
    normalizes everything to UTC internally), and Python's
    `datetime.datetime` objects that come back from a `TIMESTAMPTZ`
    column always carry `tzinfo=datetime.timezone.utc`, so comparisons and
    arithmetic elsewhere in the codebase (e.g. "is `due_date` in the
    past?") can never accidentally mix a naive and an aware datetime and
    raise a `TypeError`, or silently compare the wrong wall-clock hour.

`utc_now()` below is the ONE function every model/service in this project
should call to get "the current time" -- it always returns a
timezone-aware `datetime` stamped as UTC. Never call the bare
`datetime.datetime.utcnow()` (it returns a *naive* datetime that looks like
UTC but isn't labelled as such) -- see services/*.py and security.py for
where this function is imported and reused instead.

Every table is created with these `TIMESTAMPTZ` columns from the start —
see `alembic/versions/0001_baseline_schema.py`, the project's single
baseline migration.
"""

import datetime
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, JSON, Boolean
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utc_now() -> datetime.datetime:
    """
    The single shared "what time is it right now?" helper for the whole
    backend. Always returns a timezone-AWARE datetime (tzinfo=UTC), never a
    naive one -- import this everywhere instead of calling
    `datetime.datetime.utcnow()` directly (that function is naive-only and
    is being phased out of this codebase on purpose).
    """
    return datetime.datetime.now(datetime.timezone.utc)


# Backwards-compatible alias -- a couple of older comments/imports in this
# project referred to this helper as `get_utc_now`. Keep both names pointing
# at the same timezone-aware implementation so nothing breaks.
get_utc_now = utc_now


class AssetType(Base):
    __tablename__ = "asset_types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    total_quantity = Column(Integer, default=0, nullable=False)
    available_quantity = Column(Integer, default=0, nullable=False)
    custom_fields = Column(JSON, default=dict, nullable=True)

    # --- Soft delete ------------------------------------------------------
    # We NEVER hard-delete an asset pool row (same rationale as User below):
    # a hard delete would either violate the foreign keys from
    # AssetCheckout.asset_id / AssetException.asset_type_id, or -- if those
    # were CASCADE -- silently erase the historical audit/custody trail for
    # every unit ever checked out of this pool. Instead "deleting" a pool
    # just flips these two flags: it disappears from active inventory
    # listings (is_deleted=True) but every historical checkout/exception
    # record referencing this asset_type_id remains perfectly intact.
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    exceptions = relationship("AssetException", back_populates="asset_type")
    checkouts = relationship("AssetCheckout", back_populates="asset")


class AssetException(Base):
    __tablename__ = "asset_exceptions"

    id = Column(Integer, primary_key=True, index=True)
    asset_type_id = Column(Integer, ForeignKey("asset_types.id"), nullable=False)
    serial_number = Column(String, nullable=False, unique=True)
    status_label = Column(String, nullable=False, default="Undeployable")  # e.g., "Under Repair", "Stolen"
    notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    # --- Isolation / Recall lifecycle ---------------------------------------
    # "isolated"  -> unit is currently pulled out of the Available pool
    #                (Under Repair / Stolen / Missing). Counts against the
    #                "Isolated" term in the Available formula.
    # "recalled"  -> an administrator has recovered/repaired the unit and
    #                returned it to service. No longer counted as isolated.
    isolation_status = Column(String, nullable=False, default="isolated")
    recalled_at = Column(DateTime(timezone=True), nullable=True)

    asset_type = relationship("AssetType", back_populates="exceptions")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    operator = Column(String, nullable=False)  # email of whoever performed the action
    action = Column(String, nullable=False)
    target_type = Column(String, nullable=False)
    target_id = Column(Integer, nullable=False)
    details = Column(String, nullable=False)
    timestamp = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)

    # --- Username login (Data Quality & Usability requirement #6) ---------
    # Auto-derived from the local part of the email address the FIRST time
    # an account is created (see services/user_service.py's
    # `_derive_username()`), e.g. "t.okafor@corp.io" -> "t.okafor". Kept
    # `nullable=True` since this column is created fresh (nothing to
    # backfill) by `alembic/versions/0001_baseline_schema.py`, the
    # project's single baseline migration -- every account created from
    # this point forward always gets one. `POST /auth/login` accepts
    # EITHER this value or the email address interchangeably.
    username = Column(String, unique=True, index=True, nullable=True)

    # "admin" | "manager" | "staff" | "customer" -- NEVER "super_admin".
    # That role is reserved for the single hardcoded root identity (see
    # security.py's super_admin_principal()) and is never stored as a
    # database row; services/user_service.py's create_user() enforces
    # this at the API layer too.
    role = Column(String, default="staff")
    password_hash = Column(String, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # --- Per-account brute-force lockout (SECURITY) ------------------------
    # middleware/rate_limit.py already throttles POST /auth/login by CLIENT
    # IP, but that's coarse: an attacker distributing guesses across many
    # IPs (or sharing a NAT/VPN with legitimate users) isn't meaningfully
    # slowed down by it. These two columns add a SECOND, per-ACCOUNT layer
    # on top of that: services/auth_service.py's login() increments
    # `failed_login_attempts` on every wrong password and, once it reaches
    # `settings.ACCOUNT_LOCKOUT_MAX_ATTEMPTS`, sets `locked_until` far
    # enough in the future that further attempts against THIS account are
    # rejected outright (HTTP 423) no matter which IP they come from --
    # until the lockout window naturally expires, the correct password is
    # tried again after that point, or a Super Admin resets the account's
    # password (which also clears both fields early, as a recovery path).
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)

    # --- Soft delete ------------------------------------------------------
    # We NEVER hard-delete a user row from the database. Deleting the row
    # would either cascade-delete their entire checkout history (destroying
    # the audit trail) or crash on the foreign key constraint from
    # AssetCheckout.user_id -> users.id. Instead, "deleting" a profile just
    # flips these two flags: the account can no longer log in
    # (is_active=False) and disappears from directory listings
    # (is_deleted=True), but every historical checkout record referencing
    # this user_id remains perfectly intact.
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # --- Department scoping (used by the Manager dashboard) ---
    # `department` groups users into teams (e.g. "Engineering", "Design").
    # A manager only ever sees users/audit activity within their own
    # department; a super_admin sees everything regardless of department.
    department = Column(String, nullable=True)
    department_role = Column(String, nullable=True)  # e.g. "Senior Engineer", "Product Designer"

    checkouts = relationship("AssetCheckout", back_populates="user")


class Outsider(Base):
    __tablename__ = "outsiders"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    contact_details = Column(String, nullable=False)
    company = Column(String, nullable=True)

    checkouts = relationship("AssetCheckout", back_populates="outsider")


class AssetCheckout(Base):
    __tablename__ = "asset_checkouts"
    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(Integer, ForeignKey("asset_types.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    outsider_id = Column(Integer, ForeignKey("outsiders.id"), nullable=True)

    # `quantity` always stays the ORIGINAL amount checked out -- it is the
    # permanent historical record and must never be mutated after creation.
    # `quantity_returned` accumulates how many of those units have been
    # handed back so far (supports partial returns -- see
    # POST /checkouts/{id}/return). The amount still outstanding is always
    # `quantity - quantity_returned`.
    quantity = Column(Integer, default=1, nullable=False)
    quantity_returned = Column(Integer, default=0, nullable=False)
    checkout_date = Column(DateTime(timezone=True), default=utc_now)
    due_date = Column(DateTime(timezone=True), nullable=True)
    returned_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, default="active")  # "active" | "returned"

    asset = relationship("AssetType", back_populates="checkouts")
    user = relationship("User", back_populates="checkouts")
    outsider = relationship("Outsider", back_populates="checkouts")
