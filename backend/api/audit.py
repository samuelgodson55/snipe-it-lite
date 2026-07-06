"""
api/audit.py
------------
GET /audit-logs, GET /audit-logs/export.
"""

import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import get_db
from deps import require_privileged_role
import services.audit_service as audit_service

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("")
def get_audit_logs(
    limit: int = Query(audit_service.DEFAULT_LIMIT, ge=1, le=audit_service.MAX_LIMIT, description="Max rows to return"),
    offset: int = Query(0, ge=0, description="Rows to skip (for paging through the ledger)"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_privileged_role),
):
    return audit_service.get_audit_logs(db, user, limit, offset)


@router.get("/export")
def export_audit_logs(
    format: str = Query("csv", description="Export format: 'csv' (streamed, default) or 'pdf'."),
    start_date: Optional[datetime.date] = Query(None),
    end_date: Optional[datetime.date] = Query(None),
    db: Session = Depends(get_db),
    user: dict = Depends(require_privileged_role),
):
    fmt = format.lower()
    today = datetime.date.today()

    if fmt == "pdf":
        pdf_bytes = audit_service.export_audit_logs_pdf(db, user, start_date, end_date)
        headers = {"Content-Disposition": f"attachment; filename=audit_export_{today}.pdf"}
        return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)

    if fmt != "csv":
        raise HTTPException(status_code=400, detail="format must be 'csv' or 'pdf'.")

    csv_stream = audit_service.export_audit_logs_csv(db, user, start_date, end_date)
    headers = {"Content-Disposition": f"attachment; filename=audit_export_{today}.csv"}
    return StreamingResponse(csv_stream, media_type="text/csv", headers=headers)
