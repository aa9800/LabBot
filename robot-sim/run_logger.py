"""Isaac/실물에서 공용으로 쓸 수 있는 append-only JSONL 주행 로그.

시뮬레이션 환경(Isaac)이든 실제 로봇이든, 특정 상태 변화나 텔레메트리
데이터를 동일한 포맷으로 남겨 디버깅/플레이백에 쓴다.
"""
import datetime
import json
import os
import threading


# 남겨둘 로그 파일 수. 서비스를 재시작할 때마다 파일이 하나씩 생기는데,
# 개발 중에는 하루에도 수십 번 재시작한다. 지우는 코드가 없어서 155개 26MB 까지
# 쌓인 적이 있다. SD카드가 차면 라즈베리파이는 알아보기 힘든 방식으로 죽으므로,
# 오래된 것부터 지운다. 최근 것은 문제 추적에 실제로 쓰이므로 넉넉히 남긴다.
KEEP_RUNS = 30


def prune_old_runs(log_dir, source, keep=KEEP_RUNS):
    """오래된 주행 로그를 지운다. 지운 개수를 돌려준다."""
    try:
        names = sorted(n for n in os.listdir(log_dir)
                       if n.startswith(f"{source}_") and n.endswith(".jsonl"))
    except OSError:
        return 0
    removed = 0
    for name in names[:-keep] if len(names) > keep else []:
        try:
            os.remove(os.path.join(log_dir, name))
            removed += 1
        except OSError:
            pass
    return removed


class JsonlRunLogger:
    def __init__(self, log_dir, source="isaac"):
        os.makedirs(log_dir, exist_ok=True)
        dropped = prune_old_runs(log_dir, source)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = os.path.join(log_dir, f"{source}_{stamp}.jsonl")
        self.source = source
        self._file = open(self.path, "a", encoding="utf-8", buffering=1)
        self.write("run_started", pruned_old_logs=dropped)
        if dropped:
            print(f"[run_logger] 오래된 주행 로그 {dropped}개 정리 "
                  f"(최근 {KEEP_RUNS}개 유지)")

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
