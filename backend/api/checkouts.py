"""
api/checkouts.py
-----------------
POST /checkouts/{id}/return -- quantified return processing.
GET  /checkouts/overdue     -- dashboard alert feed of overdue checkouts.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from deps import require_privileged_role
from schemas.checkouts import ReturnRequest
import services.checkout_service as checkout_service

router = APIRouter(prefix="/checkouts", tags=["checkouts"])


@router.post("/{checkout_id}/return")
def return_checkout(checkout_id: int, req: ReturnRequest, db: Session = Depends(get_db), user: dict = Depends(require_privileged_role)):
    return checkout_service.return_checkout(db, checkout_id, req, user)


# NOTE ON ROUTE ORDERING: this is registered AFTER "/{checkout_id}/return"
# in this file, but that's fine -- "/overdue" has no path parameter, so
# FastAPI/Starlette matches it as its own distinct, literal route rather
# than accidentally being captured by "/{checkout_id}/return" (which
# requires a trailing "/return" segment anyway). If you ever add a plain
# "/{checkout_id}" GET route, define "/overdue" ABOVE it in this file, or a
# request for "/checkouts/overdue" could incorrectly match "/checkouts/{id}"
# with checkout_id="overdue" instead.
@router.get("/overdue")
def get_overdue_checkouts(
    limit: int = Query(checkout_service.DEFAULT_LIMIT, ge=1, le=checkout_service.MAX_LIMIT, description="Max rows to return"),
    offset: int = Query(0, ge=0, description="Rows to skip (for paging through a large overdue list)"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_privileged_role),
):
    """Dashboard alert feed: active checkouts whose due date has passed."""
    return checkout_service.list_overdue_checkouts(db, user, limit, offset)
