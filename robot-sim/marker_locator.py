"""카메라로 ArUco 마커를 보고 거리와 각도를 잰다.

왜 필요한가
----------
라즈봇에는 바퀴 엔코더도 IMU 도 라이다도 없다. 그래서 좌표로 이동하려 해도
"지금 내가 어디 있는지"를 알 방법이 없었다. 마커를 벽에 붙여두고 그걸 보면
마커까지의 거리와 각도가 나오고, 마커의 좌표를 알고 있으니 로봇의 위치를
역산할 수 있다. 추가 하드웨어 비용이 사실상 0 이다.

거리를 어떻게 재는가
------------------
같은 마커라도 멀리 있으면 화면에서 작게 보인다. 그 관계는 단순하다.

    거리 = (마커 실제 크기 × 초점거리) / 화면에서의 크기(px)

초점거리는 카메라 렌즈의 성질이고 픽셀 단위로 표현한다. 체스보드로 정식
캘리브레이션을 하면 가장 정확하지만, 화각(FOV)을 알면 근사할 수 있다.

    초점거리(px) = (가로 픽셀 / 2) / tan(수평화각 / 2)

ov5647 의 표준 렌즈는 수평화각이 약 53.5도다. 이 값으로 시작하고, 줄자로 잰
실제 거리와 비교해서 보정 계수를 잡는다(calibrate 명령).

각도는 어떻게 재는가
------------------
마커 중심이 화면 가운데에서 얼마나 벗어났는지를 각도로 바꾼다. 오른쪽에 있으면
양수, 왼쪽이면 음수다. 로봇이 마커를 정면으로 보려면 이 각도만큼 돌면 된다.

사용법
-----
    python3 marker_locator.py watch          # 계속 보면서 출력
    python3 marker_locator.py once           # 한 번만
    python3 marker_locator.py calibrate 100  # 마커를 정확히 100cm 앞에 두고 실행
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

# 인쇄한 마커의 '실제로 자로 잰' 한 변 길이(mm). 프린터 배율 때문에 설계값과
# 다르게 나오는 일이 흔하므로 반드시 재서 넣는다. 이 값이 틀리면 거리가 그만큼
# 통째로 틀어진다.
MARKER_SIZE_MM = float(os.environ.get("LABBOT_MARKER_MM", "150"))

# ov5647 표준 렌즈의 수평 화각(도). 정식 캘리브레이션 전까지 쓰는 근사값.
CAMERA_HFOV_DEG = float(os.environ.get("LABBOT_CAM_HFOV", "53.5"))

# calibrate 로 구한 보정 계수를 여기 저장한다.
CALIB_PATH = Path(__file__).resolve().parent / "state" / "marker_calibration.json"

ARUCO_DICT = cv2.aruco.DICT_4X4_50


def load_scale() -> float:
    """calibrate 로 구한 보정 계수. 없으면 1.0(보정 안 함)."""
    try:
        return float(json.loads(CALIB_PATH.read_text(encoding="utf-8"))["scale"])
    except Exception:
        return 1.0


def save_scale(scale: float, note: str = "") -> None:
    CALIB_PATH.parent.mkdir(parents=True, exist_ok=True)
    CALIB_PATH.write_text(
        json.dumps({"scale": scale, "note": note, "at": time.strftime("%Y-%m-%dT%H:%M:%S")},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class MarkerLocator:
    def __init__(self, marker_size_mm=MARKER_SIZE_MM, hfov_deg=CAMERA_HFOV_DEG):
        self.marker_size_mm = marker_size_mm
        self.hfov_deg = hfov_deg
        self.scale = load_scale()
        dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
        # OpenCV 4.7 에서 API 가 바뀌었다. 로봇은 4.6 이라 옛 방식을 먼저 본다.
        if hasattr(cv2.aruco, "ArucoDetector"):
            self._detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
            self._detect = lambda g: self._detector.detectMarkers(g)
        else:
            params = cv2.aruco.DetectorParameters_create()
            self._detect = lambda g: cv2.aruco.detectMarkers(g, dictionary, parameters=params)

    def focal_px(self, frame_width: int) -> float:
        return (frame_width / 2.0) / math.tan(math.radians(self.hfov_deg) / 2.0)

    def find(self, frame):
        """프레임에서 마커를 찾아 [{id, distance_cm, angle_deg, px}] 로 돌려준다."""
        if frame is None or frame.size == 0:
            return []
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        corners, ids, _ = self._detect(gray)
        if ids is None or len(ids) == 0:
            return []

        h, w = gray.shape[:2]
        focal = self.focal_px(w)
        out = []
        for corner, marker_id in zip(corners, ids.flatten()):
            pts = corner.reshape(4, 2)
            # 네 변의 길이를 평균낸다. 비스듬히 보면 변마다 길이가 다른데,
            # 평균이 한 변만 쓰는 것보다 기울기에 덜 흔들린다.
            sides = [np.linalg.norm(pts[i] - pts[(i + 1) % 4]) for i in range(4)]
            side_px = float(np.mean(sides))
            if side_px <= 1:
                continue

            distance_mm = self.marker_size_mm * focal / side_px * self.scale
            cx = float(np.mean(pts[:, 0]))
            # 화면 가운데에서 벗어난 정도를 각도로. 오른쪽이 양수.
            angle_deg = math.degrees(math.atan2(cx - w / 2.0, focal))

            out.append({
                "id": int(marker_id),
                "distance_cm": round(distance_mm / 10.0, 1),
                "angle_deg": round(angle_deg, 1),
                "px": round(side_px, 1),
                "center": (round(cx, 1), round(float(np.mean(pts[:, 1])), 1)),
            })
        out.sort(key=lambda m: m["distance_cm"])
        return out


def _open_camera():
    from picamera2 import Picamera2
    cam = Picamera2()
    cam.configure(cam.create_preview_configuration(
        main={"format": "BGR888", "size": (640, 480)},
        controls={"FrameDurationLimits": (33333, 33333)},
    ))
    cam.start()
    time.sleep(2)
    return cam


def _report(found):
    if not found:
        print("  마커 없음")
        return
    for m in found:
        side = "오른쪽" if m["angle_deg"] > 1 else ("왼쪽" if m["angle_deg"] < -1 else "정면")
        print(f"  ID {m['id']:2d}  거리 {m['distance_cm']:6.1f}cm  "
              f"각도 {m['angle_deg']:+6.1f}도({side})  화면크기 {m['px']:5.1f}px")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "watch"
    loc = MarkerLocator()
    print(f"마커 크기 {loc.marker_size_mm:.0f}mm · 화각 {loc.hfov_deg}도 · 보정계수 {loc.scale:.4f}")

    cam = _open_camera()
    try:
        if cmd == "once":
            _report(loc.find(cam.capture_array()))

        elif cmd == "calibrate":
            if len(sys.argv) < 3:
                print("사용법: calibrate <실제거리cm>   예) 마커를 정확히 100cm 앞에 두고 calibrate 100")
                return
            truth_cm = float(sys.argv[2])
            print(f"마커를 정확히 {truth_cm:.0f}cm 앞, 카메라와 마주보게 두세요. 3초 뒤 20회 측정합니다.")
            time.sleep(3)
            samples = []
            for _ in range(20):
                found = loc.find(cam.capture_array())
                if found:
                    samples.append(found[0]["distance_cm"])
                time.sleep(0.1)
            if not samples:
                print("마커를 한 번도 못 봤습니다. 조명·거리·각도를 확인하세요.")
                return
            measured = float(np.median(samples))
            new_scale = loc.scale * truth_cm / measured
            print(f"  측정값 중앙값 {measured:.1f}cm · 실제 {truth_cm:.1f}cm")
            print(f"  보정계수 {loc.scale:.4f} -> {new_scale:.4f}")
            save_scale(new_scale, f"{truth_cm:.0f}cm 기준 보정")
            print(f"  저장: {CALIB_PATH}")

        else:  # watch
            print("Ctrl+C 로 중단. 마커를 이리저리 옮겨보세요.")
            while True:
                _report(loc.find(cam.capture_array()))
                print("  " + "-" * 56)
                time.sleep(0.7)
    except KeyboardInterrupt:
        pass
    finally:
        cam.stop()
        cam.close()


if __name__ == "__main__":
    main()
