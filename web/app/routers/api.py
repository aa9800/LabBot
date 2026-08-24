"""로봇/아두이노 연동을 위해 미리 열어두는 JSON API.
이름은 설계문서 07번 API 개요와 동일하게 맞춰서, 이후 단계에서 그대로 확장할 수 있게 한다.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db

router = APIRouter(prefix="/api")


@router.get("/items", response_model=list[schemas.ItemOut])
def api_list_items(
    q: str = "", category: str = "", location: str = "", db: Session = Depends(get_db)
):
    return crud.list_items(db, q=q, category=category, location=location)


@router.post("/loans", response_model=schemas.LoanOut)
def api_create_loan(payload: schemas.LoanCreate, db: Session = Depends(get_db)):
    loan = crud.create_loan(db, payload.user_id, payload.item_id, payload.days)
    if loan is None:
        raise HTTPException(status_code=400, detail="재고 없음")
    return loan


@router.patch("/loans/{loan_id}/return", response_model=schemas.LoanOut)
def api_return_loan(loan_id: int, db: Session = Depends(get_db)):
    loan = crud.return_loan(db, loan_id)
    if loan is None:
        raise HTTPException(status_code=404, detail="대출 기록 없음 또는 이미 반납됨")
    return loan


@router.get("/stats/overview")
def api_stats_overview(db: Session = Depends(get_db)):
    return crud.dashboard_stats(db)


@router.post("/safety-events", response_model=schemas.SafetyEventOut)
def api_create_safety_event(payload: schemas.SafetyEventCreate, db: Session = Depends(get_db)):
    """robot-sim(또는 실물 Raspbot)이 장애물 등을 감지했을 때 호출한다.
    항상 NEEDS_REVIEW 상태로 시작 — 오탐 가능성이 있으므로 사람이 검토한다."""
    return crud.create_safety_event(db, payload.rule_id, payload.severity, payload.source, payload.note)


@router.post("/audit-sessions")
def api_create_audit_session(payload: schemas.AuditSessionCreate, db: Session = Depends(get_db)):
    """robot-sim이 순찰하며 스캔한 물품 id 목록을 실제 실사 세션으로 등록한다.
    사람이 /audits/new 체크리스트에서 체크하는 것과 완전히 같은 로직(crud.create_audit_session)을 탄다."""
    session = crud.create_audit_session(db, payload.performed_by, set(payload.checked_item_ids))
    return {
        "id": session.id,
        "performed_by": session.performed_by,
        "scanned_count": session.scanned_count,
        "mismatch_count": len(session.mismatches),
        "mismatches": [
            {"item_id": m.item_id, "item_name": m.item.name, "note": m.note}
            for m in session.mismatches
        ],
    }
