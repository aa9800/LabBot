"""Isaac/실물에서 공용으로 쓸 수 있는 append-only JSONL 주행 로그.

시뮬레이션 환경(Isaac)이든 실제 로봇이든, 특정 상태 변화나 텔레메트리
데이터를 동일한 포맷으로 남겨 디버깅/플레이백에 쓴다.
"""
import datetime
import json
import os
import threading


class JsonlRunLogger:
    def __init__(self, log_dir, source="isaac"):
        os.makedirs(log_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = os.path.join(log_dir, f"{source}_{stamp}.jsonl")
        self.source = source
        self._file = open(self.path, "a", encoding="utf-8", buffering=1)
        self.write("run_started")

    def write(self, event, **fields):
        record = {
            "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "source": self.source,
            "event": event,
            **fields,
        }
        self._file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    def close(self):
        if not self._file.closed:
            self.write("run_finished")
            self._file.close()
