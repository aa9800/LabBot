"""LabKeeper 야간 방범 순찰 & 침입자 감지/추적 (Intruder Tracking & Buzzer Alarm) 모듈."""
import time
import cv2
import numpy as np
from typing import Tuple, Optional, Dict, Any

class IntruderTracker:
    """방범 모드에서 사람(침입자)을 감지하고 추적 및 경보 명령을 생성하는 클래스."""

    def __init__(self, frame_width: int = 320, frame_height: int = 240):
        self.frame_w = frame_width
        self.frame_h = frame_height
        self.center_x = frame_width // 2
        
        # 추적 튜닝 파라미터
        self.deadzone_px = 35       # 화면 중앙 불감증 영역 (+-35px)
        self.follow_speed = 80      # 사람 추적 전진 속도 (PWM 0~100) — 기존 50에서 80으로 상향
        self.turn_gain = 60         # 사람 추적 회전 속도 (PWM 0~100) — 기존 40에서 60으로 상향
        self.min_safe_dist_cm = 55.0 # 안전 정지 거리 (55cm)

        self.intruder_locked = False
        self.last_seen_time = 0.0

    def compute_tracking_command(
        self,
        person_box: Optional[Tuple[int, int, int, int]],
        obstacle_dist_cm: float = 999.0,
    ) -> Dict[str, Any]:
        """사람 바운딩 박스와 초음파 거리를 기반으로 로봇 모터 및 부저/LED 명령 생성."""
        now = time.time()

        if person_box is None:
            # 2초 이상 사람이 안 보이면 추적 해제
            if self.intruder_locked and now - self.last_seen_time > 2.0:
                self.intruder_locked = False

            return {
                "detected": False,
                "speed": 0,
                "turn": 0,
                "buzzer": False,
                "siren_led": False,
                "action": "PATROL_SEARCHING",
            }

        # 사람이 감지됨
        self.intruder_locked = True
        self.last_seen_time = now

        x1, y1, x2, y2 = person_box
        box_cx = (x1 + x2) // 2
        box_area = (x2 - x1) * (y2 - y1)
        offset_x = box_cx - self.center_x

        # 1. 조향 계산 (사람이 화면 좌/우 어디에 있는지)
        turn = 0
        if offset_x < -self.deadzone_px:
            turn = -self.turn_gain  # 좌회전
        elif offset_x > self.deadzone_px:
            turn = self.turn_gain   # 우회전

        # 2. 전진 속도 계산 (안전 거리 55cm 이상일 때만 전진 추적)
        speed = 0
        if obstacle_dist_cm > self.min_safe_dist_cm and box_area < (self.frame_w * self.frame_h * 0.5):
            speed = self.follow_speed
        else:
            # 너무 가까우면 제자리에서 사람 방향만 조준
            speed = 0

        return {
            "detected": True,
            "speed": speed,
            "turn": turn,
            "buzzer": True,          # 🚨 부저 경보 울림!
            "siren_led": True,       # 🚨 경광등 LED 점멸!
            "box": person_box,
            "action": f"TRACKING_INTRUDER (offset={offset_x}, dist={obstacle_dist_cm:.1f}cm)",
        }
