"""只读监控入口：系统信息来自内核，worker 身份来自持久化心跳。"""

from collections import deque
from datetime import datetime
from pathlib import Path
from threading import Lock
from time import monotonic as _monotonic
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from rdp.api.account_auth import AccountRequestContext, get_authenticated_context
from rdp.api.database import get_read_session, get_session
from rdp.infra.db.models import MonitoringMirrorRow, MonitoringResourcesRow
from rdp.jobs.models import DownloadAdjustmentRow, JobRow, WorkerHeartbeatRow
from rdp.jobs.types import WorkerHeartbeat
from rdp.jobs.worker import heartbeat_online
from rdp.monitoring.mirror import MirrorStatus
from rdp.monitoring.proc import ProcSample, read_sample, sample_rates
from rdp.monitoring.resources import WorkerResourceSnapshot
from rdp.monitoring.vpn import PROXY_VARIABLES, Signal, vpn_status

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])
PROC_ROOT = Path("/proc")
NETWORK_INTERFACES = Path("/sys/class/net")


class VpnResponse(BaseModel):
    """脱敏的 VPN 和代理迹象。

    Attributes:
        interfaces: 隧道网卡状态。
        processes: 已知代理进程状态。
        proxy: worker 代理环境变量状态。
        proxy_hosts: 代理主机端口，不包含认证信息。
    """

    interfaces: Signal
    processes: Signal
    proxy: Signal
    proxy_hosts: tuple[str, ...]


def _process_names() -> list[str] | None:
    """读取可见进程名；无法列举进程时结果未知。"""
    try:
        entries = list(PROC_ROOT.iterdir())
    except OSError:
        return None
    names: list[str] = []
    for entry in entries:
        if entry.name.isdecimal():
            try:
                names.append((entry / "comm").read_text().strip())
            except FileNotFoundError:
                # 进程可在遍历中退出，不影响其他进程的检查。
                continue
            except OSError:
                # 无法读取进程时不能误报没有代理。
                return None
    return names


def _worker_environment(pid: int | None) -> dict[str, str] | None:
    """只读取在线 worker 的环境；不能读取时返回未知。"""
    if pid is None:
        return None
    try:
        data = (PROC_ROOT / str(pid) / "environ").read_bytes()
    except OSError:
        return None
    environment: dict[str, str] = {}
    for entry in data.decode(errors="replace").split("\0"):
        key, separator, value = entry.partition("=")
        if separator and key.lower() in PROXY_VARIABLES:
            environment[key] = value
    return environment


@router.get("/vpn", response_model=VpnResponse, operation_id="get_monitoring_vpn")
def get_monitoring_vpn(
    account: Annotated[AccountRequestContext, Depends(get_authenticated_context)],
    session: Annotated[Session, Depends(get_read_session, scope="function")],
) -> VpnResponse:
    """返回本机 VPN 迹象和 worker 的脱敏代理地址。

    Args:
        account: 已认证账号及请求时钟。
        session: 当前请求的只读数据库会话。

    Returns:
        网卡、代理进程及 worker 环境的状态与不含凭据的地址。

    Raises:
        ExternalError: 数据库不可用。
        DefectError: 数据库心跳损坏。

    Side Effects:
        只读内核进程信息、网卡目录和数据库，不修改网络设置。

    Time Semantics:
        在线状态按请求时钟和最近心跳判断；结果为本次请求快照。
    """
    row = session.get(WorkerHeartbeatRow, 1)
    pid = None
    if row is not None:
        heartbeat = WorkerHeartbeat(row.instance_id, row.pid, row.started_at, row.last_seen_at)
        if heartbeat_online(heartbeat, now=account.now):
            pid = row.pid
    result = vpn_status(NETWORK_INTERFACES, _process_names(), _worker_environment(pid))
    return VpnResponse(
        interfaces=result.interfaces,
        processes=result.processes,
        proxy=result.proxy,
        proxy_hosts=result.proxy_hosts,
    )


class MirrorResponse(BaseModel):
    """worker 最近一次镜像检查，未检查时结果和时间均为空。

    Attributes:
        status: 生效、不生效或未知；尚未检查时为空。
        checked_at: 检查时间，带时区；尚未检查时为空。
    """

    status: MirrorStatus | None
    checked_at: datetime | None


@router.get("/mirror", response_model=MirrorResponse, operation_id="get_monitoring_mirror")
def get_monitoring_mirror(
    account: Annotated[AccountRequestContext, Depends(get_authenticated_context)],
    session: Annotated[Session, Depends(get_read_session, scope="function")],
) -> MirrorResponse:
    """读取 worker 最近一次镜像检查结果。

    Args:
        account: 已认证账号。
        session: 当前请求的只读数据库会话。

    Returns:
        上次保存的状态及检查时间；从未检查时两个字段为空。

    Raises:
        ExternalError: 数据库不可用。
        ValueError: 数据库检查时间格式损坏。

    Side Effects:
        只读数据库，不执行网络检查。

    Time Semantics:
        检查时间来自 worker 的保存结果，不代表当前实时状态。
    """
    del account
    row = session.get(MonitoringMirrorRow, 1)
    if row is None:
        return MirrorResponse(status=None, checked_at=None)
    return MirrorResponse.model_validate(
        {
            "status": row.status,
            "checked_at": datetime.fromisoformat(row.checked_at) if row.checked_at else None,
        }
    )


class MirrorCheckResponse(BaseModel):
    """手动检查请求已被记录。

    Attributes:
        accepted: 标记已写入的请求，并不代表检查已完成。
    """

    accepted: bool


@router.post(
    "/mirror/check",
    response_model=MirrorCheckResponse,
    status_code=202,
    operation_id="request_monitoring_mirror_check",
)
def request_monitoring_mirror_check(
    account: Annotated[AccountRequestContext, Depends(get_authenticated_context)],
    session: Annotated[Session, Depends(get_session, scope="function")],
) -> MirrorCheckResponse:
    """请求 worker 尽快执行镜像检查，不创建作业。

    Args:
        account: 已认证账号。
        session: 当前请求的数据库写会话。

    Returns:
        请求已提交的标记，不承诺检查完成。

    Raises:
        ExternalError: 数据库不可用。
        ConflictError: 数据库写锁竞争。

    Side Effects:
        仅递增单行请求序号；不访问网络和存储根，不创建作业。

    Time Semantics:
        提交后由 worker 下一轮观察；检查进行中追加的请求不会被覆盖。
    """
    del account
    statement = sqlite_insert(MonitoringMirrorRow).values(id=1, requested_seq=1, completed_seq=0)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[MonitoringMirrorRow.id],
            set_={"requested_seq": MonitoringMirrorRow.requested_seq + 1},
        )
    )
    return MirrorCheckResponse(accepted=True)


# 页面每两秒刷新，保留三分钟的网速曲线。
RESOURCE_SAMPLE_INTERVAL_S = 2.0
RESOURCE_HISTORY_POINTS = 90


class InterfaceRate(BaseModel):
    """单个网卡的平均收发速率。

    Attributes:
        receive_bytes_per_s: 接收字节每秒。
        send_bytes_per_s: 发送字节每秒。
    """

    receive_bytes_per_s: float
    send_bytes_per_s: float


class ResourcePoint(BaseModel):
    """一次采样区间的网速。

    Attributes:
        timestamp: 单调时钟秒，仅供同进程曲线排序。
        network: 网卡名称到收发速率的映射。
    """

    timestamp: float
    network: dict[str, InterfaceRate]


class ResourceResponse(BaseModel):
    """CPU、内存和网卡速率历史。

    Attributes:
        cpu_percent: CPU 忙碌百分比，首次采样为 None。
        memory_total_bytes: 内存总字节数。
        memory_available_bytes: 可用内存字节数。
        swap_total_bytes: 交换区总字节数。
        swap_free_bytes: 交换区空闲字节数。
        history: 最近几分钟的速率点。
        download_speed_bytes_per_s: 运行中下载作业的速度总和，单位字节每秒。
        worker: worker 资源快照；尚未采集时为 None。
    """

    cpu_percent: float | None
    memory_total_bytes: int
    memory_available_bytes: int
    swap_total_bytes: int
    swap_free_bytes: int
    history: list[ResourcePoint]
    download_speed_bytes_per_s: int
    worker: WorkerResourceSnapshot | None


class ResourceSampler:
    """单个 Web 应用内的采样器，线程间共享有界历史。"""

    def __init__(self) -> None:
        """初始化空历史，不读取系统文件。

        Args:
            无。

        Returns:
            无。

        Raises:
            无。

        Side Effects:
            创建当前实例的锁和空历史。

        Time Semantics:
            同步初始化，不读取时钟。
        """
        self._lock = Lock()
        self._previous: ProcSample | None = None
        self._cpu: float | None = None
        self._history: deque[ResourcePoint] = deque(maxlen=RESOURCE_HISTORY_POINTS)

    def sample(
        self,
        proc: Path,
        timestamp: float,
        download_speed: int,
        worker: WorkerResourceSnapshot | None,
    ) -> ResourceResponse:
        """在最短间隔后读取并累计一次内核采样。

        Args:
            proc: 内核 proc 目录。
            timestamp: 单调时间，单位秒。
            download_speed: 运行中下载作业速度总和，单位字节每秒。
            worker: worker 已发布的磁盘与 GPU 快照。

        Returns:
            内存、CPU 和有界网络速率历史。

        Raises:
            OSError: 内核文件不可读。
            ValueError: 文件数值非法。
            KeyError: 缺少内存字段。

        Side Effects:
            只读内核文件并更新当前应用的内存快照。

        Time Semantics:
            两次采样至少间隔 RESOURCE_SAMPLE_INTERVAL_S；并发请求串行共享结果。
        """
        with self._lock:
            before = self._previous
            if before is None or timestamp - before.timestamp >= RESOURCE_SAMPLE_INTERVAL_S:
                current = read_sample(
                    proc / "net" / "dev", proc / "stat", proc / "meminfo", timestamp
                )
                if before is not None:
                    rates = sample_rates(before, current)
                    self._cpu = rates.cpu_percent
                    self._history.append(
                        ResourcePoint(
                            timestamp=timestamp,
                            network={
                                name: InterfaceRate(
                                    receive_bytes_per_s=rate[0], send_bytes_per_s=rate[1]
                                )
                                for name, rate in rates.network.items()
                            },
                        )
                    )
                self._previous = current
            current = cast(ProcSample, self._previous)
            total, available, swap_total, swap_free = current.memory_bytes
            return ResourceResponse(
                cpu_percent=self._cpu,
                memory_total_bytes=total,
                memory_available_bytes=available,
                swap_total_bytes=swap_total,
                swap_free_bytes=swap_free,
                history=list(self._history),
                download_speed_bytes_per_s=download_speed,
                worker=worker,
            )


@router.get("/resources", response_model=ResourceResponse, operation_id="get_monitoring_resources")
def get_monitoring_resources(
    request: Request,
    account: Annotated[AccountRequestContext, Depends(get_authenticated_context)],
    session: Annotated[Session, Depends(get_read_session, scope="function")],
) -> ResourceResponse:
    """读取本机 CPU、内存及网卡速率。

    Args:
        request: 当前 Web 请求，提供应用级采样器。
        account: 已认证账号。
        session: 只读数据库会话，用于读取运行中下载作业速度。

    Returns:
        本次采样与内存中最近网速历史。

    Raises:
        OSError: 内核文件不可读。
        ValueError: 内核计数格式非法。

    Side Effects:
        只读本机内核文件并更新内存，不访问存储根。

    Time Semantics:
        按请求触发采样，间隔和历史上限由具名常量限定。
    """
    del account
    sampler = cast(ResourceSampler, request.app.state.monitoring_sampler)
    speed = session.scalar(
        select(func.coalesce(func.sum(DownloadAdjustmentRow.speed_bytes_per_s), 0))
        .join(JobRow, JobRow.job_id == DownloadAdjustmentRow.job_id)
        .where(JobRow.type_name == "download", JobRow.state == "running")
    )
    row = session.get(MonitoringResourcesRow, 1)
    worker = WorkerResourceSnapshot.model_validate_json(row.snapshot) if row else None
    return sampler.sample(PROC_ROOT, _monotonic(), speed or 0, worker)
