"""API(로봇 연동용) 요청/응답 스키마. 사람이 보는 화면은 Jinja2 템플릿을 직접 쓰므로 여기엔 없다."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    location: str
    qr_code: str
    total_qty: int
    available_qty: int
    status: str


class LoanCreate(BaseModel):
    user_id: int
    item_id: int
    days: int = 7


class LoanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    item_id: int
    borrowed_at: datetime
    due_at: datetime
    returned_at: Optional[datetime] = None
    status: str


class SafetyEventCreate(BaseModel):
    rule_id: str
    severity: str = "MEDIUM"
    source: str = "robot-sim"
    note: str = ""


class AuditSessionCreate(BaseModel):
    performed_by: str = "robot-sim"
    checked_item_ids: list[int] = []


class SafetyEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_id: str
    severity: str
    status: str
    source: str
    note: str
    detected_at: datetime
