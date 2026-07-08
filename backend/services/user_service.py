"""
services/user_service.py
--------------------------
System-user account CRUD and self-service/custody lookups. Used by
api/users.py.
"""

from typing import Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

import models
from models import utc_now
from config import settings
from security import hash_password, SUPER_ADMIN_ID, SUPER_ADMIN_ROLE
from schemas.users import UserCreateRequest
import services.export_service as export_service
from services.search_utils import apply_search_filter

# Roles a Manager is allowed to hand out when provisioning a new login.
# A Manager can create Staff and Customer accounts, but must NEVER be able
# to create another Manager or an Admin account for themselves -- that
# would be an easy privilege-escalation hole. Admins/Super Admin are not
# limited by this list (checked in create_user below).
MANAGER_PROVISIONABLE_ROLES = ("staff", "customer")

# "super_admin" is reserved for the single hardcoded root identity (see
# security.py's super_admin_principal()) -- it is never a valid role for a
# database-backed account, no matter who is provisioning it. Anyone who
# needs Super-Admin-equivalent privileges on a normal, deletable account
# gets the "admin" role instead (see deps.py's _FULL_ADMIN_ROLES).
RESERVED_ROLES = (SUPER_ADMIN_ROLE,)

# Directories can grow large over time -- these caps stop a single request
# from ever having to load an unbounded number of rows into memory at once
# (Data Quality & Usability requirement #4). `DEFAULT_LIMIT` is generous
# enough that the existing frontend (which still does its own fast
# client-side search/pagination over whatever page it receives -- see
# js/ui.js's `filterAndPaginate()`) behaves exactly as before for any
# realistic demo/small-team dataset, while `MAX_LIMIT` guarantees a request
# can never accidentally (or maliciously) ask for "everything".
DEFAULT_LIMIT = 500
MAX_LIMIT = 1000


def _derive_username(db: Session, email: str) -> str:
    """
    Auto-derives a login username from the local part of an email address
    (the part before '@'), e.g. "t.okafor@corp.io" -> "t.okafor".

    If that base username is already taken by another account (two people
    could share the same local part on different domains, e.g.
    "j.smith@corp.io" and "j.smith@partner.io"), we append "2", "3", etc.
    until we find one that's free -- so every account always ends up with a
    guaranteed-unique username without asking whoever is provisioning the
    account to type one in separately.
    """
    base = email.split("@")[0].strip().lower()
    candidate = base
    suffix = 2
    # Also steer clear of the reserved Super Admin username (not a `users`
    # row, so the query above alone wouldn't catch it) -- letting a real
    # account share it would let that account get silently shadowed by the
    # hardcoded Super Admin login path, which checks that identifier FIRST
    # (see auth_service.py -> login()).
    reserved = settings.SUPER_ADMIN_USERNAME.strip().lower()
    while candidate == reserved or db.query(models.User).filter(models.User.username == candidate).first():
        candidate = f"{base}{suffix}"
        suffix += 1
    return candidate


def create_user(db: Session, req: UserCreateRequest, user: dict) -> dict:
    """
    Provisions a brand-new login. Both Super Admins and Managers may call
    this, but a Manager's power here is intentionally narrower:

      1. A Manager may only create "staff" or "customer" accounts -- never
         "manager" or "admin" (and never "super_admin" either, which is
         reserved for the hardcoded root account and blocked for EVERY
         caller, not just Managers -- see RESERVED_ROLES below). This is
         enforced on the BACKEND (not just hidden in the UI), so a Manager
         can't grant themselves admin rights via a raw API call either.
      2. A Manager-created "staff" account is automatically pinned to the
         MANAGER'S OWN department -- whatever the request body says is
         ignored for department. This keeps the "Team Allocation Matrix"
         department-scoping model intact (a Manager could otherwise plant
         a fake account in someone else's department to see their data).
      3. A Manager-created "customer" account never gets a department at
         all (customers aren't tied to any internal department).

    Super Admins are unrestricted, exactly like before.
    """
    requested_role = req.role.lower()

    # "super_admin" is reserved for the one hardcoded root identity -- it
    # can never be assigned to a database-backed account, even by another
    # Super Admin/Admin. See RESERVED_ROLES above.
    if requested_role in RESERVED_ROLES:
        raise HTTPException(
            status_code=400,
            detail="The 'super_admin' role is reserved for the hardcoded root account and cannot be assigned. Use 'admin' instead.",
        )

    if user["role"] == "manager" and requested_role not in MANAGER_PROVISIONABLE_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Managers may only provision Staff or Customer accounts.",
        )

    existing = db.query(models.User).filter(models.User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="A user with this email already exists.")

    # Work out the department to actually save. Super Admins get whatever
    # they typed in the form; Managers are locked to the rules above.
    if user["role"] == "manager":
        department = user["department"] if requested_role == "staff" else None
    else:
        department = req.department

    new_user = models.User(
        name=req.name, email=req.email, role=requested_role,
        username=_derive_username(db, req.email),
        password_hash=hash_password(req.password),
        department=department, department_role=req.department_role,
        is_verified=False, is_active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    db.add(models.AuditLog(
        operator=user["email"], action="USER_PROVISIONED", target_type="User", target_id=new_user.id,
        details=f"Created account for {new_user.name} ({new_user.role}).",
    ))
    db.commit()
    return {"message": f"User {new_user.name} created successfully."}


def list_users(db: Session, user: dict, limit: int = DEFAULT_LIMIT, offset: int = 0, search: Optional[str] = None) -> dict:
    """
    Super Admins see the entire directory. Managers see:
      - every account in their own department (their "Team Allocation
        Matrix"), PLUS
      - every "customer" account, regardless of department, since Customers
        are never assigned to a department and a Manager needs to be able
        to find them in order to dispatch equipment to a "Linked Customer
        Account" (one of the three dispatch channels).
    This is enforced here on the backend using the Manager's OWN department
    from their verified JWT (`user["department"]`) -- never from anything
    the client sends -- so a Manager cannot widen their own view by editing
    a request.

    We build a plain dict per user with only the fields the frontend
    actually needs, so `password_hash` (and other internal-only columns)
    never leave the server. We also compute `checkout_count` here (sum of
    outstanding units across that user's active checkouts) so the "Custody"
    column on the User Directory / Team Allocation Matrix shows a real
    number instead of always reading 0.

    PAGINATION + SEARCH (Data Quality & Usability requirement #4, extended
    to true server-side search): `limit`/`offset` bound how many rows a
    single request can return -- see the DEFAULT_LIMIT/MAX_LIMIT constants
    above this function. `search` -- when present -- narrows the directory
    to rows where name, email, role, department, or department_role
    case-insensitively contains it, the same set of fields the User
    Directory table's search box has always searched by (see
    js/components/users.js). We run `query.count()` for the (search-scoped)
    total BEFORE slicing with `.offset()/.limit()`, so the caller always
    knows the true total size of the directory even though it only
    received one page of it -- and we only compute the (relatively
    expensive) per-user `checkout_count` aggregation for the rows actually
    being returned, not the entire table.
    """
    query = db.query(models.User).filter(models.User.is_deleted == False)
    if user["role"] == "manager":
        query = query.filter(
            or_(models.User.department == user["department"], models.User.role == "customer")
        )
    query = apply_search_filter(query, search, [
        models.User.name, models.User.email, models.User.role,
        models.User.department, models.User.department_role,
    ])

    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)

    total = query.count()
    users = query.order_by(models.User.id).offset(offset).limit(limit).all()

    results = []
    for u in users:
        outstanding = sum(
            (c.quantity - c.quantity_returned) for c in u.checkouts if c.status == "active"
        )
        results.append({
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "username": u.username,
            "role": u.role,
            "department": u.department,
            "department_role": u.department_role,
            "checkout_count": outstanding,
        })
    return {"items": results, "total": total, "limit": limit, "offset": offset}


def get_my_assigned_items(db: Session, user: dict) -> dict:
    """
    Self-service version of get_user_assigned_items: lets ANY logged-in
    account (staff, customer, manager, super_admin) see their own
    checked-out items, without needing elevated privileges. Powers
    staff.html and customer.html.
    """
    target = db.query(models.User).filter(models.User.id == int(user["sub"])).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    active_checkouts = db.query(models.AssetCheckout).filter(
        models.AssetCheckout.user_id == target.id, models.AssetCheckout.status == "active"
    ).all()
    items = [{
        "checkout_id": c.id, "asset_name": c.asset.name if c.asset else "Unknown Asset",
        "quantity": c.quantity, "quantity_returned": c.quantity_returned, "outstanding": c.quantity - c.quantity_returned,
        "checkout_date": c.checkout_date.strftime("%Y-%m-%d %H:%M:%S") if c.checkout_date else None,
        "due_date": c.due_date.strftime("%Y-%m-%d") if c.due_date else "No Fixed Due Date",
    } for c in active_checkouts]

    return {
        "user_id": target.id, "name": target.name, "email": target.email, "role": target.role,
        "department": target.department, "department_role": target.department_role, "assigned_items": items,
    }


def get_user_assigned_items(db: Session, user_id: int, user: dict) -> dict:
    target = db.query(models.User).filter(models.User.id == user_id, models.User.is_deleted == False).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # A manager may only inspect custody for someone in their own department.
    if user["role"] == "manager" and target.department != user["department"]:
        raise HTTPException(status_code=403, detail="You may only view custody records for your own department.")

    active_checkouts = db.query(models.AssetCheckout).filter(
        models.AssetCheckout.user_id == user_id, models.AssetCheckout.status == "active"
    ).all()
    items = [{
        "checkout_id": c.id, "asset_name": c.asset.name if c.asset else "Unknown Asset",
        "quantity": c.quantity, "quantity_returned": c.quantity_returned, "outstanding": c.quantity - c.quantity_returned,
        "checkout_date": c.checkout_date.strftime("%Y-%m-%d %H:%M:%S") if c.checkout_date else None,
        "due_date": c.due_date.strftime("%Y-%m-%d") if c.due_date else "No Fixed Due Date",
    } for c in active_checkouts]

    return {
        "user_id": target.id, "name": target.name, "email": target.email, "role": target.role,
        "department": target.department, "department_role": target.department_role, "assigned_items": items,
    }


# ---------------------------------------------------------------------------
# PROPERTIES-ASSIGNED EXPORTS (CSV / PDF)
# ---------------------------------------------------------------------------
# Three flavors, all sharing the same row shape/headers via
# `_build_items_export()` below:
#   - export_my_assigned_items    -- self-service (staff/customer/anyone):
#                                    only their own items.
#   - export_user_assigned_items  -- Super Admin/Manager: one specific
#                                    user's items (same access rule as
#                                    get_user_assigned_items above).
#   - export_all_users_items      -- Super Admin/Manager: EVERY user in
#                                    their scope, one row per active
#                                    checkout (not one row per user).
# Each returns (file_bytes, media_type, filename) so the router
# (api/users.py) only has to wrap it in a `Response`.
_ITEM_EXPORT_HEADERS = ["Asset", "Quantity", "Quantity Returned", "Outstanding", "Checked Out", "Due Date"]


def _item_export_rows(items: list) -> list:
    """Turns the `assigned_items` list shape (see get_my_assigned_items /
    get_user_assigned_items above) into plain rows for
    export_service.build_csv_bytes()/build_pdf_bytes()."""
    return [
        [i["asset_name"], i["quantity"], i["quantity_returned"], i["outstanding"], i["checkout_date"] or "", i["due_date"]]
        for i in items
    ]


def _build_items_export(title: str, subtitle: str, items: list, fmt: str, filename_stub: str):
    """Shared CSV/PDF builder used by all three export_* functions below."""
    rows = _item_export_rows(items)
    today = utc_now().strftime("%Y-%m-%d")
    if fmt == "pdf":
        pdf_bytes = export_service.build_pdf_bytes(title, subtitle, _ITEM_EXPORT_HEADERS, rows)
        return pdf_bytes, "application/pdf", f"{filename_stub}_{today}.pdf"
    csv_bytes = export_service.build_csv_bytes(_ITEM_EXPORT_HEADERS, rows)
    return csv_bytes, "text/csv", f"{filename_stub}_{today}.csv"


def export_my_assigned_items(db: Session, user: dict, fmt: str = "csv"):
    """Self-service export of GET /users/me/items -- any logged-in account
    (staff, customer, manager, super_admin) can download their OWN custody
    ledger as a CSV or PDF, no elevated privileges required."""
    data = get_my_assigned_items(db, user)
    subtitle = f"{data['name']} ({data['email']}) · Exported {utc_now().strftime('%Y-%m-%d %H:%M UTC')}"
    return _build_items_export("Properties Assigned To Me", subtitle, data["assigned_items"], fmt, "my_properties")


def export_user_assigned_items(db: Session, user_id: int, user: dict, fmt: str = "csv"):
    """
    Privileged export of one specific user's custody ledger. Reuses
    get_user_assigned_items() above, so it automatically inherits the same
    access rule: a Super Admin may export anyone, a Manager only someone in
    their own department (a 403 is raised there otherwise).
    """
    data = get_user_assigned_items(db, user_id, user)
    subtitle = f"{data['name']} ({data['email']}) · Exported by {user['email']}"
    return _build_items_export(f"Properties Assigned To {data['name']}", subtitle, data["assigned_items"], fmt, f"user_{user_id}_properties")


def export_all_users_items(db: Session, user: dict, fmt: str = "csv"):
    """
    Bulk export: every currently-ACTIVE checkout across every user in the
    caller's scope, one row per checkout (so a single person holding
    multiple different assets still gets one row per asset, not one
    combined row). Scope mirrors list_users() exactly: a Super Admin gets
    the entire directory; a Manager gets their own department plus every
    "customer" account (customers are never tied to a department).
    """
    query = db.query(models.User).filter(models.User.is_deleted == False)
    if user["role"] == "manager":
        query = query.filter(or_(models.User.department == user["department"], models.User.role == "customer"))
    users = query.order_by(models.User.id).all()

    headers = ["User", "Email", "Department", "Role", "Asset", "Quantity", "Outstanding", "Checked Out", "Due Date"]
    rows = []
    for u in users:
        for c in u.checkouts:
            if c.status != "active":
                continue
            rows.append([
                u.name, u.email, u.department or "—", u.role,
                c.asset.name if c.asset else "Unknown Asset",
                c.quantity, c.quantity - c.quantity_returned,
                c.checkout_date.strftime("%Y-%m-%d %H:%M:%S") if c.checkout_date else "",
                c.due_date.strftime("%Y-%m-%d") if c.due_date else "No Fixed Due Date",
            ])

    today = utc_now().strftime("%Y-%m-%d")
    title = "Properties Assigned — All Users"
    subtitle = f"Exported by {user['email']} · {len(rows)} active checkout(s) across {len(users)} account(s)"
    if fmt == "pdf":
        pdf_bytes = export_service.build_pdf_bytes(title, subtitle, headers, rows)
        return pdf_bytes, "application/pdf", f"all_users_properties_{today}.pdf"
    csv_bytes = export_service.build_csv_bytes(headers, rows)
    return csv_bytes, "text/csv", f"all_users_properties_{today}.csv"


def delete_user(db: Session, user_id: int, user: dict) -> dict:
    """
    Deleting an account is a Super Admin-only action. Managers cannot do this.

    Safeguards:
      1. SOFT DELETE ONLY -- we never `db.delete()` the row. A hard delete
         would either violate the foreign key from AssetCheckout.user_id
         (if RESTRICT) or silently wipe that user's name out of the
         historical custody ledger (if CASCADE/SET NULL) -- neither is
         acceptable for an audit trail. Instead we flip is_deleted/is_active
         so the row -- and every checkout that references it -- stays
         intact forever, while the account can no longer log in or appear
         in directory listings.
      2. SUPER ADMIN SELF-DELETE BLOCK -- a logged-in Super Admin can never
         delete their own account, even via a raw API call, regardless of
         what the frontend does.
      3. ACTIVE CUSTODY GUARD -- an account still holding outstanding
         checked-out items cannot be deleted until those items are returned,
         so inventory can't silently "disappear" with the deleted account.
    """
    if user_id == int(user["sub"]):
        raise HTTPException(status_code=403, detail="You cannot delete your own account while logged in as it.")

    # Defense in depth: the hardcoded Super Admin (see security.py's
    # SUPER_ADMIN_ID) isn't a `users` table row, so the query below would
    # already return nothing for it -- this just gives a clearer error
    # than a generic 404 if it's ever targeted directly.
    if user_id == SUPER_ADMIN_ID:
        raise HTTPException(status_code=400, detail="The Super Admin account cannot be deleted.")

    target = db.query(models.User).filter(models.User.id == user_id, models.User.is_deleted == False).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    outstanding_items = db.query(func.coalesce(func.sum(
        models.AssetCheckout.quantity - models.AssetCheckout.quantity_returned
    ), 0)).filter(
        models.AssetCheckout.user_id == user_id, models.AssetCheckout.status == "active"
    ).scalar() or 0
    if outstanding_items > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete: this user still has {outstanding_items} item(s) in active custody. Process their returns first.",
        )

    target.is_deleted = True
    target.is_active = False
    target.deleted_at = utc_now()

    db.add(models.AuditLog(
        operator=user["email"], action="USER_DELETED", target_type="User", target_id=user_id,
        details=f"Soft-deleted account for {target.name} (login disabled, checkout history preserved).",
    ))
    db.commit()
    return {"message": "User profile successfully removed"}


# TODO (suggested future feature): a restore_user() service + POST
# /users/{user_id}/restore endpoint that flips is_deleted/is_active back for
# a soft-deleted account within some grace period (e.g. 30 days), for "oops,
# wrong person" recovery. Would pair nicely with a `deleted_by` column
# (added via a new Alembic migration) recording which Super Admin performed
# the original deletion.
