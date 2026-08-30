"""인쇄용 ArUco 마커를 만든다.

왜 ArUco 인가
------------
라즈봇에는 바퀴 엔코더도 IMU 도 라이다도 없다. 그래서 "지금 내가 어디 있는지"를
알 방법이 하나도 없고, 좌표로 이동하는 순찰을 만들 수 없었다.

ArUco 마커는 그 구멍을 종이값으로 메운다. 벽이나 선반에 인쇄물을 붙여두고 카메라로
보면, 마커까지의 거리와 각도가 나온다. 마커의 위치를 알고 있으니 역산하면 로봇의
위치가 나온다. OpenCV 에 이미 들어 있어서 추가 설치도 없다.

왜 이 설정인가
-------------
- DICT_4X4_50 : 4x4 격자에 50종. 격자가 성길수록 멀리서도 잘 읽힌다. 실험실
                경유점이 수십 개를 넘지 않으므로 50종이면 충분하다.
- 여백(quiet zone) : 마커 둘레의 흰 테두리. 없으면 인식률이 크게 떨어진다.
                     규격상 최소 마커 한 칸 폭이며 여기서는 넉넉히 둔다.
- 크기 라벨 : 인쇄 후 실제 변 길이를 반드시 자로 재서 코드에 넣어야 거리가 맞는다.
              프린터 배율 때문에 지정한 크기와 다르게 나오는 일이 흔하다.

사용법
-----
    python make_aruco_markers.py                    # 0~5번, 15cm
    python make_aruco_markers.py --count 10         # 0~9번
    python make_aruco_markers.py --size-mm 100      # 10cm 짜리
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE / "aruco_markers"

DPI = 300  # 인쇄 해상도. A4 기준 이 정도면 가장자리가 깨지지 않는다.


def mm_to_px(mm: float) -> int:
    return int(round(mm / 25.4 * DPI))


def make_sheet(marker_id: int, size_mm: float, dictionary) -> np.ndarray:
    """마커 한 장을 A4 가운데에 놓고 아래에 식별 라벨을 넣는다."""
    a4_w, a4_h = mm_to_px(210), mm_to_px(297)
    sheet = np.full((a4_h, a4_w), 255, dtype=np.uint8)

    side = mm_to_px(size_mm)
    marker = cv2.aruco.generateImageMarker(dictionary, marker_id, side)

    # 마커 둘레의 흰 여백은 인식에 필수다. A4 가운데에 두면 자연히 확보된다.
    x = (a4_w - side) // 2
    y = (a4_h - side) // 2 - mm_to_px(15)
    sheet[y:y + side, x:x + side] = marker

    # 라벨. 인쇄 후 실제 변 길이를 자로 재서 적어둘 칸도 같이 만든다.
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(sheet, f"ArUco 4x4_50  ID {marker_id}",
                (x, y + side + mm_to_px(18)), font, 2.0, 0, 4, cv2.LINE_AA)
    cv2.putText(sheet, f"design size: {size_mm:.0f} mm",
                (x, y + side + mm_to_px(30)), font, 1.4, 90, 3, cv2.LINE_AA)
    cv2.putText(sheet, "measured size: ______ mm   (print later, measure with a ruler)",
                (x, y + side + mm_to_px(40)), font, 1.1, 120, 2, cv2.LINE_AA)

    # 실제 변 길이를 재기 쉽게 마커 모서리에 눈금선을 긋는다.
    cv2.line(sheet, (x, y + side + mm_to_px(4)), (x + side, y + side + mm_to_px(4)), 150, 3)
    cv2.line(sheet, (x, y + side + mm_to_px(2)), (x, y + side + mm_to_px(6)), 150, 3)
    cv2.line(sheet, (x + side, y + side + mm_to_px(2)), (x + side, y + side + mm_to_px(6)), 150, 3)
    return sheet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=6, help="만들 마커 개수 (ID 0부터)")
    ap.add_argument("--size-mm", type=float, default=150, help="마커 한 변 길이(mm)")
    args = ap.parse_args()

    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    OUT.mkdir(parents=True, exist_ok=True)

    made = []
    for i in range(args.count):
        sheet = make_sheet(i, args.size_mm, dictionary)
        path = OUT / f"aruco_{i:02d}.png"
        # cv2.imwrite 는 한글이 든 경로를 못 쓴다(이 저장소가 "바탕 화면/공부/
        # 피지컬ai" 아래에 있다). 메모리에서 인코딩하고 파이썬으로 저장한다.
        ok, buf = cv2.imencode(".png", sheet)
        if not ok:
            raise RuntimeError(f"PNG 인코딩 실패: {path}")
        path.write_bytes(buf.tobytes())
        made.append(path)

    print(f"만든 곳 : {OUT}")
    print(f"장수     : {len(made)}장 (ID 0~{args.count - 1})")
    print(f"설계 크기 : {args.size_mm:.0f} mm")
    print()
    print("인쇄 요령")
    print("  1) A4 에 '실제 크기(100%)'로 인쇄한다 — '용지에 맞춤'을 끄지 않으면 크기가 달라진다.")
    print("  2) 인쇄 후 마커 한 변을 자로 재서 종이에 적어둔다. 그 값을 코드에 넣어야 거리가 맞는다.")
    print("  3) 구겨지지 않게 두꺼운 종이에 붙이거나 코팅한다 — 휘면 각도가 틀어진다.")


if __name__ == "__main__":
    main()
