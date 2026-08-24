"""每 IP 每日一次的生成限额,json 文件持久化(重启不清)。"""

import json
import threading
from datetime import datetime
from pathlib import Path

from loguru import logger


class DailyLimit:
    """{ip: 'YYYY-MM-DD'} 记录;同 IP 同日只放行一次。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data: dict = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning(f"daily_limit: 限额文件损坏,重新开始: {self.path}")
        return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")

    def allow(self, ip: str, today: str | None = None) -> bool:
        """同 IP 同日首次返回 True 并记录;否则 False。today 可注入便于测试。"""
        today = today or datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            if self._data.get(ip) == today:
                return False
            self._data[ip] = today
            self._save()
            return True
