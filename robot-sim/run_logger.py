"""Webots/Isaac/실물에서 공용으로 쓸 수 있는 append-only JSONL 주행 로그.

한 줄이 독립 JSON이라 실행 중 중단되어도 앞부분이 보존되고, 나중에 속도·회전·정지거리
파라미터를 비교할 때 pandas 등으로 바로 읽을 수 있다. 비밀키나 사진은 기록하지 않는다.
"""
import datetime
import json
import os


class JsonlRunLogger:
    def __init__(self, log_dir, source="webots"):
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
