"""물품 QR 이미지 생성. 설계문서의 '개체 식별 = QR' 원칙을 그대로 따른다."""
from pathlib import Path

import qrcode

QR_DIR = Path(__file__).resolve().parent / "static" / "qrcodes"
QR_DIR.mkdir(parents=True, exist_ok=True)


def ensure_qr_image(qr_code: str) -> str:
    """qr_code에 대한 PNG가 없으면 생성하고, 웹에서 쓸 상대 경로를 돌려준다."""
    path = QR_DIR / f"{qr_code}.png"
    if not path.exists():
        img = qrcode.make(qr_code)
        img.save(str(path))
    return f"/static/qrcodes/{qr_code}.png"
