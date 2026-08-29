import os
from pathlib import Path
from dotenv import load_dotenv

_ROOT_DIR = Path(__file__).resolve().parent.parent
_ENV_PATH = _ROOT_DIR / '.env'
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)

ROBOFLOW_API_KEY = os.getenv("ROBOFLOW_API_KEY", "")
WORKSPACE_NAME = 'yy-y-awq8j'
PROJECT_NAME = 'labkeeper-vision-guard'

TARGET_CLASSES = [
    'microscope',
    'centrifuge',
    'pipette',
    'beaker',
    'flask',
    'reagent_bottle',
    'fire_extinguisher',
    'spill_kit',
    'flammable_cabinet',
    'biohazard_bin',
    'person'
]

CLASS_METADATA = {
    'microscope': {'name_kr': '현미경', 'color': (255, 180, 50), 'type': 'ASSET'},
    'centrifuge': {'name_kr': '원심분리기', 'color': (255, 120, 50), 'type': 'ASSET'},
    'pipette': {'name_kr': '마이크로피펫', 'color': (200, 220, 50), 'type': 'ASSET'},
    'beaker': {'name_kr': '비커', 'color': (150, 230, 100), 'type': 'ASSET'},
    'flask': {'name_kr': '플라스크', 'color': (100, 220, 180), 'type': 'ASSET'},
    'reagent_bottle': {'name_kr': '화학 시약병', 'color': (50, 200, 255), 'type': 'ASSET'},
    'fire_extinguisher': {'name_kr': '소화기 [방재]', 'color': (50, 50, 255), 'type': 'SAFETY'},
    'spill_kit': {'name_kr': '스필키트 [방재]', 'color': (50, 150, 255), 'type': 'SAFETY'},
    'flammable_cabinet': {'name_kr': '인화성 보관함 [안전]', 'color': (0, 215, 255), 'type': 'SAFETY'},
    'biohazard_bin': {'name_kr': '생물 유해폐기물 [위험]', 'color': (200, 50, 200), 'type': 'SAFETY'},
    'person': {'name_kr': '사람/침입자', 'color': (0, 0, 255), 'type': 'SECURITY'},
}

DEFAULT_CONFIDENCE_THRESHOLD = 0.40
DEFAULT_IOU_THRESHOLD = 0.45
