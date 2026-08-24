"""데모 데이터. 서버 최초 기동 시 비어있으면 자동으로 채운다."""
import secrets

from . import models
from .database import Base, SessionLocal, engine
from .qr import ensure_qr_image

DEMO_USERS = [
    ("여해동", "2021001", "admin"),
    ("김지훈", "2021002", "admin"),
    ("테스트학생", "2021099", "user"),
]

DEMO_ITEMS = [
    ("니퍼", "공구", "A-1"),
    ("드라이버 세트", "공구", "A-1"),
    ("멀티미터", "계측", "A-2"),
    ("납땜기", "공구", "A-2"),
    ("아두이노 우노", "전자부품", "B-1"),
    ("브레드보드", "전자부품", "B-1"),
    ("점퍼케이블 세트", "전자부품", "B-2"),
    ("오실로스코프", "계측", "C-1"),
]


def run():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(models.User).count() == 0:
            for name, student_no, role in DEMO_USERS:
                db.add(models.User(name=name, student_no=student_no, role=role))
            db.commit()

        if db.query(models.Item).count() == 0:
            for name, category, location in DEMO_ITEMS:
                qr_code = secrets.token_hex(4).upper()
                db.add(
                    models.Item(
                        name=name,
                        category=category,
                        location=location,
                        qr_code=qr_code,
                        total_qty=3,
                        available_qty=3,
                    )
                )
            db.commit()

        for item in db.query(models.Item).all():
            ensure_qr_image(item.qr_code)
    finally:
        db.close()


if __name__ == "__main__":
    run()
