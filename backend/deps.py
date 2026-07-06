"""
deps.py
-------
Shared FastAPI dependencies used across every router in `api/`: decoding and
validating the bearer JWT (`get_current_user`), and the two role gates
(`require_super_admin`, `require_privileged_role`) built on top of it.

Kept as one small standalone module (rather than living inside main.py or
any single router) specifically so every `api/*.py` file can import from
here without creating a dependency on main.py itself.
"""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import jwt

import models
from database import get_db
from security import decode_access_token

security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> dict:
    """
    Decodes and validates the bearer JWT. Returns a small dict describing
    who's logged in: {sub, name, email, role, department}. Any route that
    depends on this simply requires "you must be logged in".
    """
    token = credentials.credentials
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")

    # Requirement #4 (Auth/User routes must exclude soft-deleted records):
    # the JWT itself is stateless and stays cryptographically valid until it
    # naturally expires (up to JWT_EXPIRY_HOURS later). Without re-checking
    # the database here, a Super Admin soft-deleting or deactivating a user
    # would NOT actually revoke that user's access -- their existing token
    # would keep working on every protected route until it happened to
    # expire. Re-querying on every request makes revocation immediate.
    db_user = db.query(models.User).filter(models.User.id == int(payload["sub"])).first()
    if not db_user or db_user.is_deleted or not db_user.is_active:
        raise HTTPException(status_code=401, detail="This account is no longer active. Please log in again.")

    return payload


def require_super_admin(user: dict = Depends(get_current_user)) -> dict:
    """Gate for actions only a Super Admin may perform."""
    if user["role"] != "super_admin":
        raise HTTPException(status_code=403, detail="Forbidden: Operation requires Super Admin privileges.")
    return user


def require_privileged_role(user: dict = Depends(get_current_user)) -> dict:
    """Gate for actions either a Super Admin OR a Manager may perform."""
    if user["role"] not in ("super_admin", "manager"):
        raise HTTPException(status_code=403, detail="Forbidden: View permission requires elevated administrative rights.")
    return user
