"""下载作业契约；计划复用 plan，外部进程、RPC、校验和持久通道由执行入口注入。

本模块不实现 HTTP 或散列算法：分别复用既有计划和标准库；只定义可替换的边界。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from rdp.jobs.downloads.plan import DownloadPlan, DownloadRequest, HubFile, PlanDependencies
from rdp.jobs.execution import ExecutionContext

# aria2 的 K/M/G 以 1024 为基数，输入统一为字节，避免界面和执行端解释不一致。
MIB = 1024 * 1024
GIB = 1024 * MIB
DownloadLimit = (
    Annotated[int, Field(strict=True, ge=0, le=0)] | Annotated[int, Field(strict=True, ge=1024)]
)


class DownloadParameters(BaseModel):
    """可持久化的下载请求与 aria2 参数；凭据不属于请求，也不能通过额外字段注入。

    Attributes:
        repo_type: dataset 或 model。
        repo_id: 命名空间/仓库名。
        revision: 非空版本，具体合法性由下载计划检查。
        storage_root: 已登记可写存储根名称。
        include: 包含模式，空表示全部。
        exclude: 排除模式，优先于 include。
        exclude_video: 排除全部视频。
        exclude_cameras: 排除的视频相机键。
        target_subdir: 模型目标相对路径；数据集必须为 None，由计划校验。
        max_concurrent_downloads: 同时下载文件数，1-16，默认 4。
        max_connection_per_server: 每服务器连接数，1-16，默认 4。
        split: 每文件分段数，1-16，默认 4。
        min_split_size_bytes: 最小分段大小，1 MiB-1 GiB，默认 20 MiB。
        max_overall_download_limit_bytes_per_s: 总速率，0 不限或至少 1024 bytes/s。
        max_tries: 最大尝试次数，1-20，默认 5。
        retry_wait_s: 重试间隔，0-600 秒，默认 10 秒。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    repo_type: Literal["dataset", "model"]
    repo_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    storage_root: str = Field(min_length=1)
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    exclude_video: bool = Field(default=False, strict=True)
    exclude_cameras: tuple[str, ...] = ()
    target_subdir: str | None = None
    max_concurrent_downloads: int = Field(default=4, strict=True, ge=1, le=16)
    max_connection_per_server: int = Field(default=4, strict=True, ge=1, le=16)
    split: int = Field(default=4, strict=True, ge=1, le=16)
    min_split_size_bytes: int = Field(default=20 * MIB, strict=True, ge=MIB, le=GIB)
    max_overall_download_limit_bytes_per_s: DownloadLimit = 0
    max_tries: int = Field(default=5, strict=True, ge=1, le=20)
    retry_wait_s: int = Field(default=10, strict=True, ge=0, le=600)


class DownloadAdjustment(BaseModel):
    """运行中唯一允许调整的两项；None 表示保持，不接受凭据或其他选项。"""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    max_concurrent_downloads: int | None = Field(default=None, strict=True, ge=1, le=16)
    max_overall_download_limit_bytes_per_s: DownloadLimit | None = None


@dataclass(frozen=True)
class TransferStatus:
    """RPC 观察快照，不含服务器原始响应或凭据。

    Attributes:
        gid: aria2 文件标识。
        state: 标准化状态。
        completed_bytes: 已完成字节数。
        speed_bytes_per_s: 当前速度，bytes/s。
        http_status: 已知 HTTP 状态码，否则 None。
    """

    gid: str
    state: Literal["active", "waiting", "complete", "error", "removed"]
    completed_bytes: int
    speed_bytes_per_s: int
    http_status: int | None = None


class Aria2Rpc(Protocol):
    """仅允许本地 RPC，RPC 密钥与文件凭据不得写入日志或作业记录。"""

    def add_file(self, url: str, target: Path, file: HubFile, token: str | None) -> str:
        """添加单文件并为 LFS 指定 sha256，令牌仅经请求头传递。

        Args:
            url: 镜像 resolve 地址；每次传输重定向必须即时拦截，预检不能代替拦截。
            target: 暂存目录内的文件路径。
            file: 文件大小及哈希元数据。
            token: 可选凭据，不进入参数、命令行或日志。

        Returns:
            aria2 的 GID。

        Raises:
            ExternalError: RPC 或下载地址不满足契约。

        Side Effects:
            调用 aria2.addUri，可能创建或续写暂存文件。

        Time Semantics:
            单次有界 RPC；不自行重试。
        """
        raise NotImplementedError

    def status(self, gid: str) -> TransferStatus:
        """读取指定文件的进度快照。

        Args:
            gid: add_file 返回的非空标识。

        Returns:
            当前状态及 bytes、bytes/s。

        Raises:
            ExternalError: RPC 失败或响应不合法。

        Side Effects:
            向本地 aria2 发送只读 RPC。

        Time Semantics:
            只代表本次观察，不保证后续状态不变。
        """
        raise NotImplementedError

    def change_global_options(self, adjustment: DownloadAdjustment) -> None:
        """调用 changeGlobalOption 应用允许的选项。

        Args:
            adjustment: 非空修改项，速率单位 bytes/s。

        Returns:
            无；RPC 确认后才能记录生效值。

        Raises:
            ExternalError: RPC 拒绝或不可达。

        Side Effects:
            改变当前 aria2 全局选项。

        Time Semantics:
            以 RPC 成功响应为生效时刻。
        """
        raise NotImplementedError

    def stop(self, gids: tuple[str, ...]) -> None:
        """依次 forceRemove 未完成项并 shutdown，不删除暂存目录。

        Args:
            gids: 本次执行的未完成文件标识。

        Returns:
            无。

        Raises:
            ExternalError: RPC 停止失败；调用方仍须终止进程组。

        Side Effects:
            停止 aria2 文件及服务。

        Time Semantics:
            RPC 有界等待，先移除再关闭。
        """
        raise NotImplementedError


class Aria2Process(Protocol):
    """由已有进程组设施实现的 aria2 生命周期边界。"""

    def start(self, parameters: DownloadParameters) -> Aria2Rpc:
        """启动仅监听回环的 aria2 RPC 进程。

        Args:
            parameters: 已验证选项，不含凭据。

        Returns:
            连接该进程的 RPC 客户端。

        Raises:
            ExternalError: 可执行文件不可用或启动超时。

        Side Effects:
            创建进程组；生成随机 RPC secret，仅监听 127.0.0.1，禁用代理，
            启用续传、关闭自动重命名和预分配；凭据不放进程命令行。

        Time Semantics:
            进程就绪后返回，随机 RPC 密钥不得进入日志。
        """
        raise NotImplementedError

    def terminate(self) -> None:
        """通过现有进程组策略 TERM 后 KILL。

        Args:
            无。

        Returns:
            无。

        Raises:
            ExternalError: 进程无法终止。

        Side Effects:
            终止进程组；不删除暂存文件。

        Time Semantics:
            TERM 与 KILL 顺序和期限由 M0 进程设施控制。
        """
        raise NotImplementedError


class CurlFallback(Protocol):
    """可替换的单文件 curl 兜底边界。"""

    def download(
        self, url: str, target: Path, token: str | None, parameters: DownloadParameters
    ) -> None:
        """对单文件续传，逐跳验证地址并沿用限速与重试。

        Args:
            url: 初始镜像地址。
            target: 暂存文件路径。
            token: 可选凭据，不进入命令行或日志。
            parameters: 限速 bytes/s 与最大尝试次数。

        Returns:
            无；返回不代表文件校验通过。

        Raises:
            ExternalError: 下载失败、重定向违规或次数耗尽。

        Side Effects:
            调用 curl 并续写暂存文件；不跟随官方站。

        Time Semantics:
            最多指定次数，等待可被作业取消打断。
        """
        raise NotImplementedError


class FileVerifier(Protocol):
    """文件大小与 Git blob SHA-1 或 LFS SHA-256 校验边界。"""

    def verify(self, path: Path, file: HubFile) -> bool:
        """校验文件大小与清单指定的散列。

        Args:
            path: 暂存目录内的文件。
            file: 期望大小及散列。

        Returns:
            大小和散列均匹配为 True，否则 False。

        Raises:
            ExternalError: 无法读取文件。

        Side Effects:
            只读文件，不改变内容。

        Time Semantics:
            校验观察期间文件须不被其他写入者修改。
        """
        raise NotImplementedError


@dataclass(frozen=True)
class DownloadStatus:
    """下载详情增量快照；其余通用进度仍由 M0 作业接口提供。

    Attributes:
        requested_version: 最近提交版本，非负。
        applied_version: 最近应用版本，非负且不超过请求版本。
        requested: 用户要求的完整并发和限速。
        effective: 当前实际并发和限速，可能被 429 降低。
        speed_bytes_per_s: 传输速度，非负 bytes/s。
        total_files: 清单文件总数，非负。
        completed_files: 成功下载且校验的文件数，非负，不含跳过。
        failed_files: 失败文件数，非负。
        skipped_files: 已校验跳过文件数，非负。
    """

    requested_version: int
    applied_version: int
    requested: DownloadAdjustment
    effective: DownloadAdjustment
    speed_bytes_per_s: int
    total_files: int
    completed_files: int
    failed_files: int
    skipped_files: int


class AdjustmentChannel(Protocol):
    """版本化调参通道；旧应答不能覆盖更新的请求。"""

    def submit(self, job_id: int, adjustment: DownloadAdjustment) -> int:
        """原子合并新调整并增加请求版本。

        Args:
            job_id: 正整数下载作业编号，必须仍在运行。
            adjustment: 至少一项非空；速率单位 bytes/s。

        Returns:
            新的正整数版本号。

        Raises:
            InputError: 参数无效或作业不是下载类型。
            ConflictError: 作业不在运行或并发更新冲突。
            ExternalError: 数据库不可用。

        Side Effects:
            同事务更新请求完整目标，不发送 RPC。

        Time Semantics:
            版本在事务提交时生效，不能覆盖并发提交的另一字段。
        """
        raise NotImplementedError

    def read(self, job_id: int) -> DownloadStatus:
        """读取调参与进度的单事务快照。

        Args:
            job_id: 正整数下载作业编号。

        Returns:
            已提交、已应用选项和文件进度快照。

        Raises:
            InputError: 作业不存在或不是下载类型。
            ExternalError: 数据库读取失败。

        Side Effects:
            只读数据库。

        Time Semantics:
            数据截至最近一次 worker 上报，并非实时网络速率。
        """
        raise NotImplementedError

    def report(self, job_id: int, status: DownloadStatus) -> None:
        """发布下载速度和文件计数，不覆盖并发提交的请求。

        Args:
            job_id: 正整数下载作业编号。
            status: 当前完整快照，速度为 bytes/s；只写进度字段。

        Returns:
            无。

        Raises:
            ExternalError: 数据库写入失败。
            DefectError: 计数为负、相互矛盾或超出总文件数。

        Side Effects:
            同事务写入速度及文件计数，不写请求或生效版本。

        Time Semantics:
            由单调时钟限频每秒最多一次，最终快照可强制保存。
        """
        raise NotImplementedError

    def pending(self, job_id: int) -> tuple[int, DownloadAdjustment] | None:
        """读取待生效调整的版本和完整目标值。

        Args:
            job_id: 正整数作业编号。

        Returns:
            待生效版本和目标值；无待处理时为 None。

        Raises:
            ExternalError: 数据库读取失败。

        Side Effects:
            只读数据库。

        Time Semantics:
            返回读取时的快照；版本单调递增。
        """
        raise NotImplementedError

    def acknowledge(self, job_id: int, version: int, effective: DownloadAdjustment) -> None:
        """RPC 成功后按版本确认生效值，不覆盖较新的待处理请求。

        Args:
            job_id: 正整数作业编号。
            version: 已应用的正整数请求版本。
            effective: 实际生效的完整选项，速率为 bytes/s。

        Returns:
            无。

        Raises:
            ExternalError: 数据库写入失败。

        Side Effects:
            事务更新生效版本及生效值。

        Time Semantics:
            必须在 RPC 成功后写入；与并发提交使用版本比较。
        """
        raise NotImplementedError


@dataclass(frozen=True)
class DownloadDependencies:
    """worker 注入的外部边界；计划和存储检查沿用 M0、01 的依赖。

    Attributes:
        plan: 现有计划使用的配置、存储检查和 HTTP 边界。
        process: 受控 aria2 进程及 RPC 客户端工厂。
        curl: 逐文件 curl 兜底。
        verifier: 文件大小与哈希校验。
        adjustments: 持久化运行中调整通道。
    """

    plan: PlanDependencies
    process: Aria2Process
    curl: CurlFallback
    verifier: FileVerifier
    adjustments: AdjustmentChannel


def request_from_parameters(parameters: DownloadParameters) -> DownloadRequest:
    """将持久参数转换为已批准的下载计划请求，不携带 token。

    Args:
        parameters: 已校验的下载作业参数。

    Returns:
        与参数选择一致的 DownloadRequest。

    Raises:
        DefectError: 参数类型不符合内部契约。

    Side Effects:
        无。

    Time Semantics:
        同步转换，不读取配置或时间。
    """
    raise NotImplementedError


@dataclass(frozen=True)
class DownloadExecutor:
    """作业类型绑定的执行器，Web 可登记无执行能力的实例。

    Attributes:
        dependencies: worker 的执行依赖；Web 只校验参数时为 None。
    """

    dependencies: DownloadDependencies | None

    def execute(self, context: ExecutionContext) -> None:
        """执行探测、计划、下载和校验，最终使用 M0 计数计算结果。

        Args:
            context: fresh 或 resume 的下载作业上下文，参数为 DownloadParameters。

        Returns:
            无；数据集保留暂存，模型全部成功后同文件系统不覆盖改名。

        Raises:
            InputError: 镜像不生效、目标已存在或存储根不可写。
            ExternalError: 计划、进程、数据库或存储发生不可恢复故障。
            JobCancelledError: 收到取消，先 RPC 停止再终止进程组。
            WorkerStoppingError: worker 停止，保留暂存及续跑状态。
            DefectError: worker 未注入依赖或内部契约被破坏。

        Side Effects:
            仅在登记为可写的存储根创建暂存产物，报告进度、条目及诊断；不输出凭据。

        Time Semantics:
            每次执行重新生成计划；续跑以上次进度为计数基线，累计计数不得回退；
            单调时间限频至每秒最多一次，等待可取消。
        """
        raise NotImplementedError


def run_download(
    context: ExecutionContext, plan: DownloadPlan, dependencies: DownloadDependencies
) -> None:
    """使用注入边界执行已预检的下载计划。

    Args:
        context: 作业上下文；报告、取消和等待沿用 M0。
        plan: 固定 commit 的下载计划，存储根已经预检。
        dependencies: aria2、curl、校验及调参替身或生产适配器。

    Returns:
        无；每个文件计一个条目，包括校验通过而跳过的文件。

    Raises:
        ExternalError: 无法继续执行或持久化。
        JobCancelledError: 取消后保留暂存。
        WorkerStoppingError: 中断后保留暂存以供恢复。

    Side Effects:
        在可写暂存区下载、校验并记录结果；不写已入库数据。
        成功校验后在同目录原子替换 .rdp-verified-v1.json；失败不写通过记录，
        不跟随缓存或目标文件的软链接。

    Time Semantics:
        先校验已完成文件，再续传；每次执行重新读取计划，调参确认在 RPC 成功后。
        同一作业恢复时按持久检查点识别已计数文件，避免重复累计；重新提交按新作业独立计数。
    """
    raise NotImplementedError


def validate_download_redirect(current_url: str, location: str) -> str:
    """逐跳解析下载重定向并拒绝官方站与非 HTTPS 地址。

    Args:
        current_url: 当前 HTTPS 地址，不包含用户信息。
        location: 服务端返回的相对或绝对 Location，不含凭据。

    Returns:
        解析归一化后的下一跳 HTTPS URL，不保证该 URL 的后续跳转安全。

    Raises:
        InputError: 格式非法、目标是 huggingface.co 或其子域、含用户信息或非 HTTPS。

    Side Effects:
        无；不解析 DNS 或发出网络请求。

    Time Semantics:
        每个真实响应均须调用，预检不能代替传输时逐跳检查。
    """
    raise NotImplementedError


def cached_file_is_valid(path: Path, file: HubFile, manifest: Path) -> bool:
    """仅在缓存身份与当前文件和清单均匹配时复用校验结果。

    Args:
        path: 暂存文件的安全路径。
        file: 本次清单的相对路径、大小与期望哈希。
        manifest: 同一暂存目录下 .rdp-verified-v1.json；JSON 顶层含 version=1 和 entries，
            entries 以相对路径为键，每项记录期望算法、散列、大小和设备号、inode、mtime_ns、ctime_ns。

    Returns:
        完整身份匹配返回 True；缓存缺失、损坏或身份变化返回 False。

    Raises:
        ExternalError: 无法安全读取文件或缓存。

    Side Effects:
        只读文件元信息和缓存，不计算哈希、不修改文件。

    Time Semantics:
        身份包含设备号、inode、大小、mtime_ns、ctime_ns 和期望哈希；缓存是优化而非抗恶意篡改证明。
    """
    raise NotImplementedError


def concurrency_after_throttling(
    consecutive_429: int, quiet_seconds: float, current: int, requested: int
) -> int:
    """按照连续限流和稳定期计算文件并发目标，不超过用户设置。

    Args:
        consecutive_429: 自最近一次成功后观察到的连续 429 次数，非负。
        quiet_seconds: 距最近一次 429 的单调时长，单位秒，非负。
        current: 当前实际并发，1 至 16。
        requested: 用户目标并发，1 至 16。

    Returns:
        连续每 3 次 429 将当前值减半向下取整且最少 1；无新 429 连续 60 秒则每 60 秒加 1，最多 requested。

    Raises:
        DefectError: 入参越界或时间非有限数。

    Side Effects:
        无；调用方负责通过 RPC 应用并持久化实际生效值。

    Time Semantics:
        单调时钟计算稳定期；每一组 3 次 429 和每个 60 秒稳定期只能消费一次。
    """
    raise NotImplementedError
