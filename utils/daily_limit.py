"""每 IP 每日一次的生成限额,json 文件持久化(重启不清)。"""

import json
import threading
from datetime import datetime
from pathlib import Path

from loguru import logger

# 回环地址默认白名单(本机测试不受限);IPv4-mapped 形式一并防御
DEFAULT_LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}


class DailyLimit:
    """{ip: 'YYYY-MM-DD'} 记录;同 IP 同日只放行一次。白名单 IP 不限次、不记录。"""

    def __init__(self, path: Path, whitelist: set | None = None):
        self.path = Path(path)
        self.whitelist = DEFAULT_LOOPBACK if whitelist is None else set(whitelist)
        self._lock = threading.Lock()
        self._data: dict = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    logger.warning(f"daily_limit: 限额文件格式异常(非对象),重新开始: {self.path}")
                    return {}
                return data
            except Exception:
                logger.warning(f"daily_limit: 限额文件损坏,重新开始: {self.path}")
        return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")

    def allow(self, ip: str, today: str | None = None) -> bool:
        """同 IP 同日首次返回 True 并记录;否则 False。today 可注入便于测试。

        白名单 IP 直接放行,不记录、不消耗配额。
        """
        if ip in self.whitelist:
            return True
        today = today or datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            if self._data.get(ip) == today:
                return False
            self._data[ip] = today
            self._save()
            return True
