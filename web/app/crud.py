"""비즈니스 로직. 화면(pages.py)과 API(api.py)가 이 모듈만 통해 DB에 접근한다."""
import datetime as dt

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models

# ---- items ----------------------------------------------------------------


def list_items(db: Session, q: str = "", category: str = "", location: str = ""):
    query = db.query(models.Item)
    if q:
        query = query.filter(models.Item.name.contains(q))
    if category:
        query = query.filter(models.Item.category == category)
    if location:
        query = query.filter(models.Item.location == location)
    return query.order_by(models.Item.name).all()


def get_item(db: Session, item_id: int):
    return db.query(models.Item).filter(models.Item.id == item_id).first()


def get_item_by_qr(db: Session, qr_code: str):
    return db.query(models.Item).filter(models.Item.qr_code == qr_code).first()


def create_item(db: Session, name: str, category: str, location: str, total_qty: int, qr_code: str):
    item = models.Item(
        name=name,
        category=category,
        location=location,
        total_qty=total_qty,
        available_qty=total_qty,
        qr_code=qr_code,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def distinct_categories(db: Session):
    return [r[0] for r in db.query(models.Item.category).distinct().order_by(models.Item.category).all()]


def distinct_locations(db: Session):
    return [r[0] for r in db.query(models.Item.location).distinct().order_by(models.Item.location).all()]


# ---- users ------------------------------------------------------------------


def list_users(db: Session):
    return db.query(models.User).order_by(models.User.name).all()


def get_user(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()


# ---- loans -------------------------------------------------------------------


def create_loan(db: Session, user_id: int, item_id: int, days: int = 7):
    item = get_item(db, item_id)
    if not item or item.available_qty <= 0:
        return None
    item.available_qty -= 1
    loan = models.Loan(
        user_id=user_id,
        item_id=item_id,
        due_at=dt.datetime.utcnow() + dt.timedelta(days=days),
        status="대여중",
    )
    db.add(loan)
    db.commit()
    db.refresh(loan)
    return loan


def return_loan(db: Session, loan_id: int):
    loan = db.query(models.Loan).filter(models.Loan.id == loan_id).first()
    if not loan or loan.returned_at:
        return None
    loan.returned_at = dt.datetime.utcnow()
    loan.status = "반납완료"
    loan.item.available_qty += 1
    db.commit()
    db.refresh(loan)
    return loan


def return_loan_by_qr(db: Session, qr_code: str):
    """물품 QR만으로 반납 처리 — 설계문서 09번 '반납 흐름'과 동일한 규칙."""
    item = get_item_by_qr(db, qr_code)
    if not item:
        return None
    loan = (
        db.query(models.Loan)
        .filter(models.Loan.item_id == item.id, models.Loan.status == "대여중")
        .order_by(models.Loan.borrowed_at.desc())
        .first()
    )
    if not loan:
        return None
    return return_loan(db, loan.id)


def overdue_days(loan: models.Loan) -> int:
    end = loan.returned_at or dt.datetime.utcnow()
    delta = (end - loan.due_at).days
    return max(delta, 0)


def list_loans(db: Session, status: str = ""):
    query = db.query(models.Loan)
    if status:
        query = query.filter(models.Loan.status == status)
    return query.order_by(models.Loan.borrowed_at.desc()).all()


def list_loans_for_user(db: Session, user_id: int, status: str = ""):
    query = db.query(models.Loan).filter(models.Loan.user_id == user_id)
    if status:
        query = query.filter(models.Loan.status == status)
    return query.order_by(models.Loan.borrowed_at.desc()).all()


# ---- audits ------------------------------------------------------------------


def create_audit_session(db: Session, performed_by: str, checked_item_ids: set[int]):
    session = models.AuditSession(
        performed_by=performed_by,
        scanned_count=len(checked_item_ids),
        finished_at=dt.datetime.utcnow(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    for item in db.query(models.Item).all():
        if item.id not in checked_item_ids:
            db.add(
                models.AuditMismatch(
                    session_id=session.id, item_id=item.id, note="실사 시 미확인"
                )
            )
    db.commit()
    db.refresh(session)
    return session


def list_audit_sessions(db: Session):
    return db.query(models.AuditSession).order_by(models.AuditSession.id.desc()).all()


def get_audit_session(db: Session, session_id: int):
    return db.query(models.AuditSession).filter(models.AuditSession.id == session_id).first()


# ---- safety events -------------------------------------------------------------
# LabFlow v1.2 14.7 우선적용 규칙 중 로봇이 실시간으로 보내는 물리적 이상만 다룬다.
# (SR-05/06/07은 이미 AuditMismatch가 처리하므로 여기서 중복 구현하지 않는다.)


def create_safety_event(db: Session, rule_id: str, severity: str, source: str, note: str = ""):
    event = models.SafetyEvent(
        rule_id=rule_id, severity=severity, source=source, note=note, status="NEEDS_REVIEW"
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    _log_action(db, event, actor=source, action="detected", note=note)
    return event


def _log_action(db: Session, event: models.SafetyEvent, actor: str, action: str, note: str = ""):
    db.add(models.ActionLog(event_id=event.id, actor=actor, action=action, note=note))
    db.commit()


def list_safety_events(db: Session, status: str = "", severity: str = ""):
    query = db.query(models.SafetyEvent)
    if status:
        query = query.filter(models.SafetyEvent.status == status)
    if severity:
        query = query.filter(models.SafetyEvent.severity == severity)
    return query.order_by(models.SafetyEvent.detected_at.desc()).all()


def get_safety_event(db: Session, event_id: int):
    return db.query(models.SafetyEvent).filter(models.SafetyEvent.id == event_id).first()


def open_safety_count(db: Session):
    return (
        db.query(func.count(models.SafetyEvent.id))
        .filter(models.SafetyEvent.status.in_(["NEEDS_REVIEW", "OPEN", "ASSIGNED", "IN_PROGRESS"]))
        .scalar()
        or 0
    )


def confirm_safety_event(db: Session, event_id: int, actor: str):
    """검토자가 오탐이 아니라고 확인 — NEEDS_REVIEW → OPEN."""
    event = get_safety_event(db, event_id)
    if not event or event.status != "NEEDS_REVIEW":
        return None
    event.status = "OPEN"
    db.commit()
    _log_action(db, event, actor, "confirmed")
    return event


def mark_false_positive(db: Session, event_id: int, actor: str, note: str = ""):
    event = get_safety_event(db, event_id)
    if not event:
        return None
    event.status = "FALSE_POSITIVE"
    event.resolved_at = dt.datetime.utcnow()
    db.commit()
    _log_action(db, event, actor, "false_positive", note)
    return event


def assign_safety_event(db: Session, event_id: int, assignee_id: int, actor: str, due_in_days: int = 3):
    event = get_safety_event(db, event_id)
    if not event:
        return None
    event.assignee_id = assignee_id
    event.due_at = dt.datetime.utcnow() + dt.timedelta(days=due_in_days)
    if event.status in ("NEEDS_REVIEW", "OPEN"):
        event.status = "ASSIGNED"
    db.commit()
    _log_action(db, event, actor, "assigned")
    return event


def add_progress_note(db: Session, event_id: int, actor: str, note: str):
    event = get_safety_event(db, event_id)
    if not event:
        return None
    event.status = "IN_PROGRESS"
    db.commit()
    _log_action(db, event, actor, "progress", note)
    return event


def resolve_safety_event(db: Session, event_id: int, actor: str, resolution_note: str):
    event = get_safety_event(db, event_id)
    if not event:
        return None
    event.status = "RESOLVED"
    event.resolution_note = resolution_note
    event.resolved_at = dt.datetime.utcnow()
    db.commit()
    _log_action(db, event, actor, "resolved", resolution_note)
    return event


def close_safety_event(db: Session, event_id: int, actor: str):
    event = get_safety_event(db, event_id)
    if not event or event.status != "RESOLVED":
        return None
    event.status = "CLOSED"
    db.commit()
    _log_action(db, event, actor, "closed")
    return event


# ---- dashboard ----------------------------------------------------------------


def dashboard_stats(db: Session):
    total_items = db.query(func.count(models.Item.id)).scalar() or 0
    active_loans = db.query(models.Loan).filter(models.Loan.status == "대여중").all()
    overdue_count = sum(1 for loan in active_loans if overdue_days(loan) > 0)

    last_session = (
        db.query(models.AuditSession).order_by(models.AuditSession.id.desc()).first()
    )
    accuracy = None
    if last_session and total_items:
        accuracy = round((total_items - len(last_session.mismatches)) / total_items * 100)

    popular = (
        db.query(models.Item, func.count(models.Loan.id).label("cnt"))
        .join(models.Loan, models.Loan.item_id == models.Item.id)
        .group_by(models.Item.id)
        .order_by(func.count(models.Loan.id).desc())
        .limit(5)
        .all()
    )

    return {
        "total_items": total_items,
        "active_loans": len(active_loans),
        "overdue_count": overdue_count,
        "accuracy": accuracy,
        "popular": popular,
        "open_safety": open_safety_count(db),
    }
