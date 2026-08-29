"""실행 중인 LabBot 로봇의 FPS/온도/메모리/서비스 상태를 JSONL로 기록한다."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from urllib.request import Request, urlopen


def fetch_json(url: str, timeout: float = 3.0) -> dict:
    with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def run_text(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=3, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def parse_temperature(raw: str | None) -> float | None:
    if not raw or "=" not in raw:
        return None
    try:
        return float(raw.split("=", 1)[1].replace("'C", ""))
    except ValueError:
        return None


def service_properties(service_name: str) -> dict:
    raw = run_text([
        "systemctl", "show", service_name,
        "--property=ActiveState,SubState,MainPID,NRestarts", "--no-pager",
    ])
    if raw is None:
        return {}
    return dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)


def process_rss_kib(pid: str | int | None) -> int | None:
    try:
        if not pid or int(pid) <= 0:
            return None
        for line in Path(f"/proc/{int(pid)}/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (OSError, ValueError):
        return None
    return None


def sample(robot_url: str, service_name: str) -> dict:
    base_url = robot_url.rstrip("/")
    service = service_properties(service_name)
    record = {
        "type": "sample",
        "at": datetime.now(timezone.utc).isoformat(),
        "monotonic": time.monotonic(),
        "errors": [],
        "temperature_c": parse_temperature(run_text(["vcgencmd", "measure_temp"])),
        "throttled": run_text(["vcgencmd", "get_throttled"]),
        "service_active": service.get("ActiveState"),
        "service_substate": service.get("SubState"),
        "service_restarts": int(service.get("NRestarts", 0) or 0),
        "service_pid": int(service.get("MainPID", 0) or 0),
    }
    record["rss_kib"] = process_rss_kib(record["service_pid"])
    for endpoint, key in (("/status", "camera"), ("/ai/status", "ai"), ("/telemetry", "telemetry")):
        try:
            record[key] = fetch_json(base_url + endpoint)
        except Exception as exc:  # 기록기는 실패를 삼키지 않고 샘플에 남긴다.
            record[key] = None
            record["errors"].append(f"{endpoint}: {type(exc).__name__}: {exc}")
    return record


def _numbers(records: list[dict], getter) -> list[float]:
    values = []
    for record in records:
        try:
            value = getter(record)
            if value is not None:
                values.append(float(value))
        except (KeyError, TypeError, ValueError):
            pass
    return values


def summarize(records: list[dict], min_ai_fps: float) -> dict:
    camera_fps = _numbers(records, lambda item: item["camera"]["fps"])
    ai_fps = _numbers(records, lambda item: item["ai"]["actual_fps"])
    temperatures = _numbers(records, lambda item: item["temperature_c"])
    rss = _numbers(records, lambda item: item["rss_kib"])
    restart_counts = _numbers(records, lambda item: item["service_restarts"])
    errors = [error for record in records for error in record.get("errors", [])]
    throttled = [str(record.get("throttled", "")) for record in records]
    throttle_detected = any(value not in {"", "throttled=0x0"} for value in throttled)
    restart_delta = int(max(restart_counts) - min(restart_counts)) if restart_counts else None
    active_all = bool(records) and all(record.get("service_active") == "active" for record in records)
    ai_min = min(ai_fps) if ai_fps else None
    return {
        "type": "summary",
        "sample_count": len(records),
        "duration_seconds": round(records[-1]["monotonic"] - records[0]["monotonic"], 1) if len(records) > 1 else 0.0,
        "camera_fps": _stats(camera_fps),
        "ai_fps": _stats(ai_fps),
        "temperature_c": _stats(temperatures),
        "rss_kib": _stats(rss),
        "service_restart_delta": restart_delta,
        "service_active_all_samples": active_all,
        "throttle_detected": throttle_detected,
        "error_count": len(errors),
        "errors": errors[-20:],
        "pass": bool(
            records
            and not errors
            and active_all
            and restart_delta == 0
            and not throttle_detected
            and ai_min is not None
            and ai_min >= min_ai_fps
        ),
        "minimum_required_ai_fps": min_ai_fps,
    }


def _stats(values: list[float]) -> dict | None:
    if not values:
        return None
    return {
        "min": round(min(values), 2),
        "mean": round(statistics.fmean(values), 2),
        "max": round(max(values), 2),
    }


def append_record(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="LabBot 라즈봇 내구성 모니터")
    parser.add_argument("--robot-url", default="http://127.0.0.1:8080")
    parser.add_argument("--service", default="labkeeper-robot.service")
    parser.add_argument("--duration-seconds", type=float, default=1800.0)
    parser.add_argument("--interval-seconds", type=float, default=30.0)
    parser.add_argument("--min-ai-fps", type=float, default=9.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.duration_seconds <= 0 or args.interval_seconds <= 0:
        parser.error("duration과 interval은 0보다 커야 합니다.")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    waiter = Event()
    records = []
    started = time.monotonic()
    while True:
        record = sample(args.robot_url, args.service)
        records.append(record)
        append_record(args.output, record)
        elapsed = time.monotonic() - started
        print(
            f"{elapsed:7.1f}s camera={((record.get('camera') or {}).get('fps'))} "
            f"ai={((record.get('ai') or {}).get('actual_fps'))} "
            f"temp={record.get('temperature_c')} errors={len(record['errors'])}",
            flush=True,
        )
        if elapsed >= args.duration_seconds:
            break
        waiter.wait(min(args.interval_seconds, args.duration_seconds - elapsed))

    result = summarize(records, args.min_ai_fps)
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    append_record(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
