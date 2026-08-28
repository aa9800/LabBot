"""Roboflow API 및 Universe 연동 클라이언트."""
import os
import sys
import json
import urllib.request
import urllib.parse
from typing import List, Dict, Any, Optional

from ai_vision.config import ROBOFLOW_API_KEY, WORKSPACE_NAME, PROJECT_NAME

class RoboflowManager:
    """Roboflow 플랫폼 연동 매니저."""
    def __init__(self, api_key: str = ROBOFLOW_API_KEY):
        self.api_key = api_key
        self.base_url = "https://api.roboflow.com"

    def get_workspace_info(self) -> Dict[str, Any]:
        """현재 API 키의 워크스페이스 정보 반환."""
        url = f"{self.base_url}/?api_key={self.api_key}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def search_universe(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Roboflow Universe에서 공개 데이터셋 검색."""
        encoded_q = urllib.parse.quote(query)
        url = f"{self.base_url}/universe/search?q={encoded_q}&api_key={self.api_key}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results = data.get("results", [])
                formatted = []
                for r in results[:limit]:
                    ws = r.get("workspace", {}).get("url", "")
                    url_slug = r.get("url", "").split("/")[-1]
                    proj_id = f"{ws}/{url_slug}" if ws and url_slug else r.get("id", "")
                    formatted.append({
                        "id": proj_id,
                        "name": r.get("name"),
                        "classes": r.get("classes", []),
                        "images": r.get("images", 0),
                        "url": r.get("url"),
                        "latest_version": r.get("latestVersion", 1),
                    })
                return formatted
        except Exception as e:
            print(f"[Roboflow] Universe search error for '{query}': {e}")
            return []

    def download_dataset(self, project_id: str, version: int = 1, model_format: str = "yolov11", target_dir: str = "datasets") -> str:
        """Roboflow SDK를 통해 지정한 데이터셋 다운로드."""
        try:
            from roboflow import Roboflow
            rf = Roboflow(api_key=self.api_key)
            
            parts = project_id.split("/")
            if len(parts) == 2:
                ws_name, proj_name = parts
                project = rf.workspace(ws_name).project(proj_name)
            else:
                project = rf.workspace().project(project_id)
            
            dataset = project.version(version).download(model_format, location=target_dir)
            print(f"[Roboflow] Dataset downloaded to: {dataset.location}")
            return dataset.location
        except Exception as e:
            print(f"[Roboflow] Download error for '{project_id}': {e}")
            return ""
