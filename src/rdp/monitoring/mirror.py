"""worker 使用既有下载探测并保存最近一次结果；Web 只读取结果。"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import text
from sqlalchemy.engine import Engine

from rdp.infra.db.utc import format_utc_text
from rdp.infra.diagnostics import ExternalError
from rdp.jobs.downloads.plan import HttpTransport, probe_mirror

MirrorStatus = Literal["effective", "ineffective", "unknown"]
# 工单建议每分钟刷新一次，单位秒。
MIRROR_CHECK_INTERVAL_S = 60


@dataclass(frozen=True)
class MirrorResult:
    """最近一次镜像检查的结论。

    Attributes:
        status: 生效、不生效或未知。
        checked_at: 检查完成时刻，带时区。
    """

    status: MirrorStatus
    checked_at: datetime


def check_mirror(
    engine: Engine, transport: HttpTransport, *, now: datetime, sleep: Callable[[float], None]
) -> MirrorResult:
    """检查镜像并把结果保存到数据库。

    Args:
        engine: 平台数据库引擎。
        transport: 不走代理、不跟随重定向的镜像传输。
        now: 本次检查的带时区时间。
        sleep: 下载探测的重试等待，参数单位秒。

    Returns:
        本次结果；外部探测失败转换为未知或不生效。

    Raises:
        SQLAlchemyError: 结果写入失败。
        InputError: now 不含有效时区。

    Side Effects:
        访问镜像并更新数据库中的唯一结果。

    Time Semantics:
        复用下载探测的有界超时和重试；时间由调用方提供。
    """
    timestamp = format_utc_text(now)
    try:
        probe_mirror(transport, sleep=sleep)
        status: MirrorStatus = "effective"
    except ExternalError as error:
        status = (
            "ineffective"
            if any(item.rule == "download.mirror_redirect" for item in error.diagnostics)
            else "unknown"
        )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO monitoring_mirror (id, status, checked_at) VALUES (1, :status, :time) "
                "ON CONFLICT(id) DO UPDATE SET status=excluded.status, checked_at=excluded.checked_at"
            ),
            {"status": status, "time": timestamp},
        )
    return MirrorResult(status, datetime.fromisoformat(timestamp))


def latest_mirror(engine: Engine) -> MirrorResult | None:
    """读取最近一次已保存的镜像结果。

    Args:
        engine: 平台数据库引擎。

    Returns:
        最近一次结果；从未检查时为 None。

    Raises:
        SQLAlchemyError: 读取数据库失败。

    Side Effects:
        只读取数据库，不访问网络。

    Time Semantics:
        返回最后完成并保存的检查时间。
    """
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT status, checked_at FROM monitoring_mirror WHERE id=1")
        ).first()
    if row is None or row.checked_at is None:
        return None
    status: MirrorStatus = row.status
    return MirrorResult(status, datetime.fromisoformat(row.checked_at))
