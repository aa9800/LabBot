"""데이터 모델 — 설계문서 04번 ERD와 동일한 구조."""
import datetime as dt

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    student_no = Column(String, unique=True, nullable=False)
    role = Column(String, default="user")  # user | admin

    loans = relationship("Loan", back_populates="user")


class Item(Base):
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    location = Column(String, nullable=False)
    qr_code = Column(String, unique=True, nullable=False)
    total_qty = Column(Integer, default=1)
    available_qty = Column(Integer, default=1)
    status = Column(String, default="정상")  # 정상 | 고장 | 폐기
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    loans = relationship("Loan", back_populates="item")


class Loan(Base):
    __tablename__ = "loans"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    borrowed_at = Column(DateTime, default=dt.datetime.utcnow)
    due_at = Column(DateTime, nullable=False)
    returned_at = Column(DateTime, nullable=True)
    status = Column(String, default="대여중")  # 대여중 | 반납완료

    user = relationship("User", back_populates="loans")
    item = relationship("Item", back_populates="loans")


class AuditSession(Base):
    """재고 실사 세션. 로봇 연동 전까지는 사람이 체크리스트로 직접 입력한다."""

    __tablename__ = "audit_sessions"

    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, default=dt.datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    performed_by = Column(String, nullable=False)
    scanned_count = Column(Integer, default=0)

    mismatches = relationship("AuditMismatch", back_populates="session")


class AuditMismatch(Base):
    __tablename__ = "audit_mismatches"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("audit_sessions.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    note = Column(Text, default="")

    session = relationship("AuditSession", back_populates="mismatches")
    item = relationship("Item")


class SafetyEvent(Base):
    """LabFlow v1.2 14장의 축소 데이터모델을 그대로 따른다.

    SR-05/06/07(위치·재고 불일치, 점검누락)은 이미 AuditMismatch가 처리하므로
    여기서는 로봇이 실시간으로 감지하는 물리적 이상(SR-01/02/03/08 등)만 다룬다.
    """

    __tablename__ = "safety_events"

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(String, nullable=False)  # 예: SR-01
    severity = Column(String, default="MEDIUM")  # HIGH | MEDIUM | LOW
    status = Column(String, default="NEEDS_REVIEW")
    # NEEDS_REVIEW | OPEN | ASSIGNED | IN_PROGRESS | RESOLVED | CLOSED | FALSE_POSITIVE
    source = Column(String, default="manual")  # robot-sim | raspbot | manual
    note = Column(Text, default="")
    detected_at = Column(DateTime, default=dt.datetime.utcnow)
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    due_at = Column(DateTime, nullable=True)
    resolution_note = Column(Text, default="")
    resolved_at = Column(DateTime, nullable=True)

    assignee = relationship("User")
    action_logs = relationship("ActionLog", back_populates="event", order_by="ActionLog.created_at")


class ActionLog(Base):
    """SafetyEvent의 상태 변화 감사이력 — 14.6 축소 데이터모델의 ActionLog."""

    __tablename__ = "action_logs"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("safety_events.id"), nullable=False)
    actor = Column(String, nullable=False)
    action = Column(String, nullable=False)  # 예: assigned, resolved, closed, false_positive
    note = Column(Text, default="")
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    event = relationship("SafetyEvent", back_populates="action_logs")
