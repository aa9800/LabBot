"""RTX 50 시리즈에서 반응성과 화질을 균형있게 유지하는 Isaac Sim 렌더 프리셋."""
import os

import carb


PRESETS = {
    "performance": {"render_mode": "RealTimePathTracing", "dlss_mode": 0},
    "balanced": {"render_mode": "RealTimePathTracing", "dlss_mode": 1},
    # RTX 5070 기본값: 실시간 레이트레이싱 + DLSS Quality.
    "high": {"render_mode": "RealTimePathTracing", "dlss_mode": 2},
    # 스크린샷용. 로봇을 조작할 때는 high를 권장한다.
    "cinematic": {"render_mode": "PathTracing", "dlss_mode": 2},
}


def configure_rtx_quality(preset=None):
    """SimulationApp 생성 후 호출하여 RTX 렌더러와 DLSS를 설정한다."""
    requested = (preset or os.environ.get("LABKEEPER_RENDER_QUALITY", "high")).strip().lower()
    selected = requested if requested in PRESETS else "high"
    config = PRESETS[selected]
    settings = carb.settings.get_settings()
    settings.set("/rtx/rendermode", config["render_mode"])
    settings.set("rtx/post/dlss/execMode", config["dlss_mode"])
    return selected, dict(config)
