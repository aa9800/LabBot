"""라즈봇 카메라에서 현장 검증용 원본 이미지를 안전하게 수집한다.

이미지는 로봇 로컬 디스크에만 저장하며 자동 업로드나 자동 라벨링을 하지 않는다.
로봇이 수동 모드로 완전히 정지해 있지 않으면 수집을 시작하거나 계속하지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from urllib.error import URLError
from urllib.request import Request, urlopen


ALLOWED_PURPOSES = {
    "background-negative",
    "lab-object-validation",
    "person-validation",
}
MIN_INTERVAL_SECONDS = 0.5
MAX_IMAGE_COUNT = 500


def validate_request(
    purpose: str,
    count: int,
    interval_seconds: float,
    site_authorization_confirmed: bool,
    person_consent_confirmed: bool,
) -> None:
    if purpose not in ALLOWED_PURPOSES:
        raise ValueError(f"허용되지 않은 수집 목적입니다: {purpose}")
    if not site_authorization_confirmed:
        raise ValueError("연구실 촬영 권한 확인이 필요합니다.")
    if purpose == "person-validation" and not person_consent_confirmed:
        raise ValueError("사람 데이터 수집은 촬영 대상자의 명시적 동의가 필요합니다.")
    if not 1 <= count <= MAX_IMAGE_COUNT:
        raise ValueError(f"이미지 수는 1~{MAX_IMAGE_COUNT}장이어야 합니다.")
    if interval_seconds < MIN_INTERVAL_SECONDS:
        raise ValueError(
            f"수집 간격은 {MIN_INTERVAL_SECONDS:.1f}초 이상이어야 합니다. "
            "연속 영상 덤프 대신 서로 다른 장면을 수집하세요."
        )


def is_robot_stationary(telemetry: dict, tolerance: float = 0.001) -> bool:
    return (
        telemetry.get("mode") == "manual"
        and abs(float(telemetry.get("speed", 0.0))) <= tolerance
        and abs(float(telemetry.get("turn", 0.0))) <= tolerance
    )


def fetch_json(url: str, timeout: float = 3.0) -> dict:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_jpeg(url: str, timeout: float = 5.0) -> bytes:
    request = Request(url, headers={"Accept": "image/jpeg"})
    with urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "")
        image = response.read()
    if "image/jpeg" not in content_type.lower() or not image.startswith(b"\xff\xd8"):
        raise ValueError("로봇 스냅샷 응답이 유효한 JPEG가 아닙니다.")
    return image


def append_manifest(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LabBot 실제 연구실 데이터 안전 수집")
    parser.add_argument("--robot-url", default="http://127.0.0.1:8080")
    parser.add_argument("--purpose", required=True, choices=sorted(ALLOWED_PURPOSES))
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--output-root", type=Path, default=Path("datasets/real_lab"))
    parser.add_argument("--scene-note", default="")
    parser.add_argument("--site-authorization-confirmed", action="store_true")
    parser.add_argument("--person-consent-confirmed", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_request(
            args.purpose,
            args.count,
            args.interval_seconds,
            args.site_authorization_confirmed,
            args.person_consent_confirmed,
        )
    except ValueError as exc:
        print(f"[거부] {exc}", file=sys.stderr)
        return 2

    session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    session_dir = args.output_root / f"{session_id}_{args.purpose}"
    session_dir.mkdir(parents=True, exist_ok=False)
    manifest_path = session_dir / "manifest.jsonl"
    base_url = args.robot_url.rstrip("/")

    append_manifest(
        manifest_path,
        {
            "type": "session",
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "purpose": args.purpose,
            "scene_note": args.scene_note,
            "site_authorization_confirmed": True,
            "person_consent_confirmed": bool(args.person_consent_confirmed),
            "automatic_upload": False,
            "automatic_labels": False,
        },
    )

    waiter = Event()
    try:
        for index in range(args.count):
            telemetry = fetch_json(f"{base_url}/telemetry")
            if not is_robot_stationary(telemetry):
                raise RuntimeError(
                    "로봇이 수동 정지 상태가 아니어서 수집을 중단했습니다 "
                    f"(mode={telemetry.get('mode')}, speed={telemetry.get('speed')}, "
                    f"turn={telemetry.get('turn')})."
                )

            image = fetch_jpeg(f"{base_url}/snapshot")
            filename = f"frame_{index + 1:04d}.jpg"
            target = session_dir / filename
            partial = target.with_suffix(".jpg.part")
            partial.write_bytes(image)
            partial.replace(target)
            append_manifest(
                manifest_path,
                {
                    "type": "image",
                    "index": index + 1,
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "file": filename,
                    "sha256": hashlib.sha256(image).hexdigest(),
                    "bytes": len(image),
                    "robot_mode": telemetry.get("mode"),
                    "robot_speed": telemetry.get("speed"),
                    "robot_turn": telemetry.get("turn"),
                },
            )
            print(f"[{index + 1}/{args.count}] {target}")
            if index + 1 < args.count:
                waiter.wait(args.interval_seconds)
    except (OSError, RuntimeError, ValueError, URLError) as exc:
        append_manifest(
            manifest_path,
            {"type": "aborted", "at": datetime.now(timezone.utc).isoformat(), "reason": str(exc)},
        )
        print(f"[중단] {exc}", file=sys.stderr)
        return 1

    append_manifest(
        manifest_path,
        {"type": "completed", "at": datetime.now(timezone.utc).isoformat(), "count": args.count},
    )
    print(f"완료: {session_dir} (자동 업로드/자동 라벨링 없음)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
