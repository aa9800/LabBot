"""실물 Raspbot과 Isaac Sim이 함께 쓰는 야간 경비 상태 머신.

주간에는 기존 대여 안내/자동 주행을 방해하지 않는다. 야간에는 짧은 정기 순찰 뒤
모터를 끄고 센서만 감시하며, 초음파 변화가 일정 시간 지속되거나 카메라가 사람을
확인했을 때만 조사 주행을 시작한다.
"""
from __future__ import annotations

import datetime as dt
import os
import threading
import time


STATE_LABELS = {
    "daytime": "주간 대여 보조",
    "disabled": "야간 경비 꺼짐",
    "scheduled_patrol": "야간 정기 순찰",
    "standby": "정차 센서 감시",
    "verifying": "이상 신호 재확인",
    "investigating": "이상 신호 조사 중",
}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class NightGuardScheduler:
    """시간대·센서 신호를 받아 로봇이 주행해야 하는지만 결정한다.

    시간은 테스트 가능하도록 monotonic 함수를 주입한다. 모든 공개 메서드는 HTTP
    서버 스레드와 제어 루프에서 동시에 호출해도 안전하다.
    """

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        start_hour: int | None = None,
        end_hour: int | None = None,
        patrol_interval_s: float | None = None,
        patrol_duration_s: float | None = None,
        investigation_duration_s: float | None = None,
        trigger_hold_s: float | None = None,
        sonar_delta_cm: float | None = None,
        sonar_near_cm: float | None = None,
        monotonic=time.monotonic,
    ):
        self.enabled = _env_bool("LABKEEPER_NIGHT_GUARD", True) if enabled is None else bool(enabled)
        self.start_hour = self._hour(os.environ.get("LABKEEPER_NIGHT_START", start_hour if start_hour is not None else 22))
        self.end_hour = self._hour(os.environ.get("LABKEEPER_NIGHT_END", end_hour if end_hour is not None else 8))
        interval_default = float(os.environ.get("LABKEEPER_NIGHT_PATROL_MINUTES", "30")) * 60.0
        self.patrol_interval_s = max(60.0, float(patrol_interval_s if patrol_interval_s is not None else interval_default))
        self.patrol_duration_s = max(5.0, float(patrol_duration_s if patrol_duration_s is not None else os.environ.get("LABKEEPER_NIGHT_PATROL_DURATION", "300")))
        self.investigation_duration_s = max(5.0, float(investigation_duration_s if investigation_duration_s is not None else os.environ.get("LABKEEPER_NIGHT_INVESTIGATION_DURATION", "90")))
        self.trigger_hold_s = max(0.1, float(trigger_hold_s if trigger_hold_s is not None else os.environ.get("LABKEEPER_NIGHT_TRIGGER_HOLD", "0.8")))
        self.sonar_delta_cm = max(5.0, float(sonar_delta_cm if sonar_delta_cm is not None else os.environ.get("LABKEEPER_NIGHT_SONAR_DELTA", "30")))
        self.sonar_near_cm = max(40.0, float(sonar_near_cm if sonar_near_cm is not None else os.environ.get("LABKEEPER_NIGHT_SONAR_NEAR", "180")))
        self._clock = monotonic
        self._lock = threading.RLock()
        self.state = "daytime"
        self.reason = ""
        self.state_since = self._clock()
        self.last_patrol_at = None
        self.next_patrol_at = None
        self._night_session_active = False
        self._candidate_since = None
        self._candidate_reason = ""
        self._sonar_baseline = None
        self._external_trigger = None
        self._force_night = False
        self._transition_id = 0

    @staticmethod
    def _hour(value) -> int:
        return max(0, min(23, int(value)))

    def _is_night(self, now: dt.datetime) -> bool:
        if self._force_night:
            return True
        hour = now.hour
        if self.start_hour == self.end_hour:
            return True
        if self.start_hour < self.end_hour:
            return self.start_hour <= hour < self.end_hour
        return hour >= self.start_hour or hour < self.end_hour

    def _set_state(self, state: str, now_mono: float, reason: str = "") -> bool:
        if self.state == state and self.reason == reason:
            return False
        self.state = state
        self.reason = reason
        self.state_since = now_mono
        self._transition_id += 1
        return True

    def configure(self, **values):
        """관리자 화면에서 런타임 정책을 안전한 범위 안에서 변경한다."""
        with self._lock:
            if "enabled" in values:
                self.enabled = bool(values["enabled"])
            if "force_night" in values:
                self._force_night = bool(values["force_night"])
            if "start_hour" in values:
                self.start_hour = self._hour(values["start_hour"])
            if "end_hour" in values:
                self.end_hour = self._hour(values["end_hour"])
            if "patrol_interval_minutes" in values:
                self.patrol_interval_s = max(60.0, min(6 * 3600.0, float(values["patrol_interval_minutes"]) * 60.0))
            return self.status()

    def trigger(self, source="camera", person=False):
        """AI 카메라/웹 테스트 등 외부 확정 신호를 다음 제어 틱에 전달한다."""
        with self._lock:
            self._external_trigger = {
                "source": str(source or "camera")[:40],
                "person": bool(person),
                "at": self._clock(),
            }
            return self.status()

    def _sonar_triggered(self, distance_cm) -> bool:
        try:
            distance = float(distance_cm)
        except (TypeError, ValueError):
            return False
        valid = 2.0 <= distance < 900.0
        if not valid:
            if self._sonar_baseline is None:
                self._sonar_baseline = 999.0
            return False
        if self._sonar_baseline is None:
            self._sonar_baseline = distance
            return False
        changed = abs(self._sonar_baseline - distance) >= self.sonar_delta_cm
        approached = distance < self._sonar_baseline and distance <= self.sonar_near_cm
        if not changed:
            # 천천히 변하는 실내 환경에는 따라가되, 갑작스러운 접근은 기준에 섞지 않는다.
            self._sonar_baseline = self._sonar_baseline * 0.92 + distance * 0.08
        return changed and approached

    def update(self, *, now: dt.datetime | None = None, sonar_cm=None, motion=False, person=False):
        now_wall = now or dt.datetime.now()
        now_mono = self._clock()
        with self._lock:
            night = self.enabled and self._is_night(now_wall)
            transition = False

            if not self.enabled:
                self._night_session_active = False
                transition = self._set_state("disabled", now_mono)
                return self._result(night=False, should_move=True, transitioned=transition)

            if not night:
                self._night_session_active = False
                self._candidate_since = None
                self._sonar_baseline = None
                transition = self._set_state("daytime", now_mono)
                return self._result(night=False, should_move=True, transitioned=transition)

            if not self._night_session_active:
                self._night_session_active = True
                self.last_patrol_at = now_mono
                self.next_patrol_at = now_mono + self.patrol_interval_s
                transition = self._set_state("scheduled_patrol", now_mono, "야간 시작 확인 순찰")

            external = self._external_trigger
            self._external_trigger = None
            trigger_reason = ""
            immediate = False
            if person or (external and external.get("person")):
                trigger_reason = "카메라 사람 감지"
                immediate = True
            elif external:
                trigger_reason = f"{external['source']} 이상 감지"
                immediate = True
            elif motion and self.state in {"standby", "verifying"}:
                trigger_reason = "카메라 움직임 감지"
            elif self.state in {"standby", "verifying"} and self._sonar_triggered(sonar_cm):
                trigger_reason = "초음파 거리 변화"

            if self.state == "scheduled_patrol":
                if trigger_reason:
                    transition = self._set_state("investigating", now_mono, trigger_reason) or transition
                elif now_mono - self.state_since >= self.patrol_duration_s:
                    try:
                        distance = float(sonar_cm)
                        self._sonar_baseline = distance if 2.0 <= distance < 900.0 else 999.0
                    except (TypeError, ValueError):
                        self._sonar_baseline = None
                    transition = self._set_state("standby", now_mono) or transition
            elif self.state == "investigating":
                if trigger_reason:
                    # 새 확정 신호가 오면 조사 시간을 다시 확보한다.
                    self.state_since = now_mono
                    self.reason = trigger_reason
                elif now_mono - self.state_since >= self.investigation_duration_s:
                    self._sonar_baseline = None
                    transition = self._set_state("standby", now_mono) or transition
            else:
                if self.next_patrol_at is not None and now_mono >= self.next_patrol_at:
                    self.last_patrol_at = now_mono
                    self.next_patrol_at = now_mono + self.patrol_interval_s
                    self._candidate_since = None
                    transition = self._set_state("scheduled_patrol", now_mono, "30분 정기 순찰") or transition
                elif trigger_reason and immediate:
                    self._candidate_since = None
                    transition = self._set_state("investigating", now_mono, trigger_reason) or transition
                elif trigger_reason:
                    if self._candidate_reason != trigger_reason:
                        self._candidate_since = now_mono
                        self._candidate_reason = trigger_reason
                    if self._candidate_since is not None and now_mono - self._candidate_since >= self.trigger_hold_s:
                        self._candidate_since = None
                        transition = self._set_state("investigating", now_mono, trigger_reason) or transition
                    else:
                        transition = self._set_state("verifying", now_mono, trigger_reason) or transition
                else:
                    self._candidate_since = None
                    self._candidate_reason = ""
                    if self.state == "verifying":
                        transition = self._set_state("standby", now_mono) or transition

            return self._result(
                night=True,
                should_move=self.state in {"scheduled_patrol", "investigating"},
                transitioned=transition,
            )

    def _result(self, *, night, should_move, transitioned=False):
        data = self._status_unlocked()
        data.update({"active": night, "should_move": should_move, "transitioned": transitioned})
        return data

    def _status_unlocked(self):
        now_mono = self._clock()
        remaining = None
        if self.next_patrol_at is not None:
            remaining = max(0, int(round(self.next_patrol_at - now_mono)))
        return {
            "enabled": self.enabled,
            "force_night": self._force_night,
            "state": self.state,
            "label": STATE_LABELS.get(self.state, self.state),
            "reason": self.reason,
            "start_hour": self.start_hour,
            "end_hour": self.end_hour,
            "patrol_interval_minutes": int(round(self.patrol_interval_s / 60.0)),
            "next_patrol_in_seconds": remaining,
            "transition_id": self._transition_id,
        }

    def status(self):
        with self._lock:
            data = self._status_unlocked()
            data["active"] = self._night_session_active and self.enabled
            data["should_move"] = self.state in {"scheduled_patrol", "investigating"}
            return data
