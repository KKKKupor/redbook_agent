"""运行健康登记与错误分类 — 全链路降级/兜底点统一在此记录,逐条实时推送钉钉提醒。"""

from loguru import logger

from utils.notifier import notifier

_MAX_ALERTS_PER_RUN = 10
_seen: set = set()   # (node, kind) 每运行去重
_count = 0


def reset() -> None:
    """每运行开始调用,清空去重与计数。"""
    global _seen, _count
    _seen = set()
    _count = 0


def build_alert_message(node: str, kind: str, detail: str = "") -> str:
    """组装降级提醒消息体(纯函数)。"""
    return (
        f"**环节**: {node}  \n"
        f"**降级类型**: {kind}  \n"
        f"**详情**: {detail[:300] or '(无详情)'}"
    )


def note(node: str, kind: str, detail: str = "") -> None:
    """记录一次降级并立即推送钉钉提醒。

    同一 (node, kind) 每运行只推一次;每运行最多 _MAX_ALERTS_PER_RUN 条;
    推送失败仅日志,绝不抛出(不得影响业务降级路径)。
    """
    global _count
    key = (node, kind)
    if key in _seen:
        logger.debug(f"health: 重复降级 {node}/{kind} 已提醒,跳过")
        return
    if _count >= _MAX_ALERTS_PER_RUN:
        logger.warning(f"health: 本次运行降级提醒已达上限 {_MAX_ALERTS_PER_RUN} 条")
        return
    _seen.add(key)
    _count += 1
    try:
        notifier.send(
            title="⚠️ 小红书Agent降级提醒",
            content=build_alert_message(node, kind, detail),
            level="warning",
        )
    except Exception as e:
        logger.error(f"health: 提醒推送失败: {e}")


def summary() -> list:
    """本次运行全部降级记录(供日志与测试)。"""
    return [{"node": k[0], "kind": k[1]} for k in sorted(_seen)]


# ═══ 错误分类(自愈一期:环境类 vs 代码逻辑类) ═══

_ENV_TYPES = (TimeoutError, ConnectionError, OSError)
_ENV_MSG_PATTERNS = (
    "timeout", "timed out", "connection", "429", "rate limit",
    "disk full", "no space", "dns", "resolve",
)
_CODE_TYPES = (KeyError, TypeError, ValueError, ImportError, AttributeError, IndexError)


def classify_error(error: BaseException) -> str:
    """分类致命错误:environmental(网络/限流/磁盘,恢复后重跑)| code(代码逻辑,需修复)| unknown。"""
    if isinstance(error, _ENV_TYPES):
        return "environmental"
    msg = str(error).lower()
    if any(p in msg for p in _ENV_MSG_PATTERNS):
        return "environmental"
    if isinstance(error, _CODE_TYPES):
        return "code"
    return "unknown"
