"""사람이 보는 화면(HTML) 라우트."""
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .. import crud
from ..database import get_db
from ..qr import ensure_qr_image

router = APIRouter()

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    stats = crud.dashboard_stats(db)
    recent_loans = crud.list_loans(db)[:8]
    categories = crud.distinct_categories(db)

    current_user = None
    my_loans = []
    user_cookie = request.cookies.get("lk_user")
    if user_cookie and user_cookie.isdigit():
        current_user = crud.get_user(db, int(user_cookie))
        if current_user:
            my_loans = crud.list_loans_for_user(db, current_user.id, status="대여중")
            for loan in my_loans:
                loan.overdue = crud.overdue_days(loan)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "stats": stats,
            "recent_loans": recent_loans,
            "categories": categories,
            "users": crud.list_users(db),
            "current_user": current_user,
            "my_loans": my_loans,
        },
    )


@router.post("/whoami")
def set_current_user(user_id: int = Form(...)):
    resp = RedirectResponse(url="/", status_code=303)
    resp.set_cookie("lk_user", str(user_id), max_age=60 * 60 * 24 * 30, httponly=True, samesite="lax")
    return resp


@router.get("/items")
def items_list(
    request: Request,
    q: str = "",
    category: str = "",
    location: str = "",
    db: Session = Depends(get_db),
):
    items = crud.list_items(db, q=q, category=category, location=location)
    return templates.TemplateResponse(
        request,
        "items_list.html",
        {
            "items": items,
            "q": q,
            "category": category,
            "location": location,
            "categories": crud.distinct_categories(db),
            "locations": crud.distinct_locations(db),
        },
    )


@router.get("/items/new")
def item_new_form(request: Request):
    return templates.TemplateResponse(request, "item_form.html", {})


@router.post("/items/new")
def item_new(
    name: str = Form(...),
    category: str = Form(...),
    location: str = Form(...),
    total_qty: int = Form(1),
    db: Session = Depends(get_db),
):
    qr_code = secrets.token_hex(4).upper()
    item = crud.create_item(db, name, category, location, total_qty, qr_code)
    ensure_qr_image(item.qr_code)
    return RedirectResponse(url=f"/items/{item.id}", status_code=303)


@router.get("/items/{item_id}")
def item_detail(item_id: int, request: Request, db: Session = Depends(get_db)):
    item = crud.get_item(db, item_id)
    qr_url = ensure_qr_image(item.qr_code)
    return templates.TemplateResponse(
        request,
        "item_detail.html",
        {
            "item": item,
            "qr_url": qr_url,
            "loans": item.loans,
            "users": crud.list_users(db),
        },
    )


@router.post("/loans/new")
def loan_new(
    item_id: int = Form(...),
    user_id: int = Form(...),
    days: int = Form(7),
    db: Session = Depends(get_db),
):
    crud.create_loan(db, user_id, item_id, days)
    return RedirectResponse(url="/loans", status_code=303)


@router.get("/loans")
def loans_list(request: Request, status: str = "", db: Session = Depends(get_db)):
    loans = crud.list_loans(db, status=status)
    for loan in loans:
        loan.overdue = crud.overdue_days(loan)
    return templates.TemplateResponse(
        request, "loans_list.html", {"loans": loans, "status": status}
    )


@router.post("/loans/{loan_id}/return")
def loan_return(loan_id: int, next: str = Form("/loans"), db: Session = Depends(get_db)):
    crud.return_loan(db, loan_id)
    return RedirectResponse(url=next, status_code=303)


@router.get("/audits")
def audits_list(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request, "audits_list.html", {"sessions": crud.list_audit_sessions(db)}
    )


@router.get("/audits/new")
def audit_new_form(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request, "audit_form.html", {"items": crud.list_items(db)}
    )


@router.post("/audits/new")
async def audit_new(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    performed_by = form.get("performed_by") or "관리자"
    checked_ids = {int(v) for v in form.getlist("checked_items")}
    session = crud.create_audit_session(db, performed_by, checked_ids)
    return RedirectResponse(url=f"/audits/{session.id}", status_code=303)


@router.get("/audits/{session_id}")
def audit_detail(session_id: int, request: Request, db: Session = Depends(get_db)):
    session = crud.get_audit_session(db, session_id)
    return templates.TemplateResponse(
        request, "audit_detail.html", {"session": session}
    )


# ---- safety -----------------------------------------------------------------


@router.get("/safety")
def safety_list(request: Request, status: str = "", db: Session = Depends(get_db)):
    events = crud.list_safety_events(db, status=status)
    return templates.TemplateResponse(
        request, "safety_list.html", {"events": events, "status": status}
    )


@router.get("/safety/{event_id}")
def safety_detail(event_id: int, request: Request, db: Session = Depends(get_db)):
    event = crud.get_safety_event(db, event_id)
    return templates.TemplateResponse(
        request, "safety_detail.html", {"event": event, "users": crud.list_users(db)}
    )


@router.post("/safety/{event_id}/confirm")
def safety_confirm(event_id: int, db: Session = Depends(get_db)):
    crud.confirm_safety_event(db, event_id, actor="관리자")
    return RedirectResponse(url=f"/safety/{event_id}", status_code=303)


@router.post("/safety/{event_id}/false-positive")
def safety_false_positive(event_id: int, note: str = Form(""), db: Session = Depends(get_db)):
    crud.mark_false_positive(db, event_id, actor="관리자", note=note)
    return RedirectResponse(url=f"/safety/{event_id}", status_code=303)


@router.post("/safety/{event_id}/assign")
def safety_assign(event_id: int, assignee_id: int = Form(...), db: Session = Depends(get_db)):
    crud.assign_safety_event(db, event_id, assignee_id, actor="관리자")
    return RedirectResponse(url=f"/safety/{event_id}", status_code=303)


@router.post("/safety/{event_id}/progress")
def safety_progress(event_id: int, note: str = Form(...), db: Session = Depends(get_db)):
    crud.add_progress_note(db, event_id, actor="담당자", note=note)
    return RedirectResponse(url=f"/safety/{event_id}", status_code=303)


@router.post("/safety/{event_id}/resolve")
def safety_resolve(event_id: int, resolution_note: str = Form(...), db: Session = Depends(get_db)):
    crud.resolve_safety_event(db, event_id, actor="담당자", resolution_note=resolution_note)
    return RedirectResponse(url=f"/safety/{event_id}", status_code=303)


@router.post("/safety/{event_id}/close")
def safety_close(event_id: int, db: Session = Depends(get_db)):
    crud.close_safety_event(db, event_id, actor="안전관리자")
    return RedirectResponse(url=f"/safety/{event_id}", status_code=303)


# ---- admin (LabBot 스타일 탭 페이지 — 재고관리/대여이력/실사/Safety) ----------


@router.get("/admin")
def admin_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "stats": crud.dashboard_stats(db),
            "items": crud.list_items(db),
            "categories": crud.distinct_categories(db),
            "loans": crud.list_loans(db),
            "audit_sessions": crud.list_audit_sessions(db)[:10],
            "safety_events": crud.list_safety_events(db)[:10],
        },
    )


@router.post("/admin/items")
def admin_item_add(
    name: str = Form(...),
    category: str = Form(...),
    location: str = Form(...),
    total_qty: int = Form(1),
    db: Session = Depends(get_db),
):
    qr_code = secrets.token_hex(4).upper()
    item = crud.create_item(db, name, category, location, total_qty, qr_code)
    ensure_qr_image(item.qr_code)
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/admin/items/{item_id}/update")
def admin_item_update(
    item_id: int,
    available_qty: int = Form(...),
    total_qty: int = Form(...),
    db: Session = Depends(get_db),
):
    crud.update_item_stock(db, item_id, available_qty, total_qty)
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/admin/items/{item_id}/delete")
def admin_item_delete(item_id: int, db: Session = Depends(get_db)):
    crud.delete_item(db, item_id)
    return RedirectResponse(url="/admin", status_code=303)
