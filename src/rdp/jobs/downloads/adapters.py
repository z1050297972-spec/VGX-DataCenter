"""下载的实际外部适配器；协议与编排在 job，散列使用标准库 hashlib。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import stat
import tempfile
import time
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import urlsplit

from rdp.infra.config import JobsConfig
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    ExternalError,
)

# 同包下载适配器共用隔离子进程；暂不移动旧计划模块的内部边界，以保留现有替身和默认行为。
from rdp.jobs.downloads._context import adjustment, current, recheck
from rdp.jobs.downloads.job import (
    MAX_REDIRECT_HOPS,
    DownloadAdjustment,
    DownloadParameters,
    MirrorRangeTransport,
    RedirectTransport,
    TransferStatus,
    resolve_download_url,
    validate_download_redirect,
)
from rdp.jobs.downloads.plan import (
    MIRROR_ENDPOINT,
    HttpResponse,
    HubFile,
    _bounded_request,  # pyright: ignore[reportPrivateUsage]
)
from rdp.jobs.processes import ManagedExternalProcess, ToolCommand

# 每次处理 1 MiB 后检查取消，避免大文件校验期间长时间不检查信号。
_HASH_BLOCK_BYTES = 1024 * 1024


class HashFileVerifier:
    """使用标准库计算文件散列；可注入检查点以响应取消。"""

    def __init__(self, checkpoint: Callable[[], None] | None = None) -> None:
        """绑定文件校验时使用的检查点。

        Args:
            checkpoint: 每块读入后调用；None 表示调用方自行管理检查点。

        Returns:
            无。

        Raises:
            无。

        Side Effects:
            无。

        Time Semantics:
            构造时不读取文件和时钟。
        """
        self._checkpoint = checkpoint

    def verify(self, path: Path, file: HubFile) -> bool:
        """校验文件大小及 LFS SHA-256 或 git blob SHA-1。

        Args:
            path: 暂存目录内的文件路径，末项不能是软链接。
            file: 清单中的非负字节数和期望散列。

        Returns:
            大小、散列及校验前后文件身份一致时为 True，否则为 False。

        Raises:
            ExternalError: 文件无法安全打开或读取。
            Exception: 检查点抛出的取消或停止异常原样传递。

        Side Effects:
            只读文件，不修改文件内容。

        Time Semantics:
            每读取至多 1 MiB 检查一次信号；比较校验前后文件身份和修改时间。
        """
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size != file.size_bytes:
                    return False
                if file.lfs_sha256 is None:
                    digest = hashlib.sha1(usedforsecurity=False)
                    digest.update(f"blob {file.size_bytes}\0".encode("ascii"))
                    expected = file.blob_sha1
                else:
                    digest = hashlib.sha256()
                    expected = file.lfs_sha256
                while chunk := stream.read(_HASH_BLOCK_BYTES):
                    digest.update(chunk)
                    if self._checkpoint is not None:
                        self._checkpoint()
                after = os.fstat(stream.fileno())
                return (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                    before.st_ctime_ns,
                ) == (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                ) and digest.hexdigest() == expected
        except OSError as error:
            raise ExternalError(
                (
                    Diagnostic(
                        level=DiagnosticLevel.ERROR,
                        category=DiagnosticCategory.EXTERNAL,
                        stage="校验",
                        source="平台",
                        objects=(),
                        rule="download.hash_read",
                        actual="无法安全读取待校验文件",
                        expected="文件可读且不是软链接",
                        consequence="无法校验该文件",
                        next_step="检查暂存区权限和文件类型后重试",
                    ),
                )
            ) from error


class RedirectHttpTransport:
    """复用计划的隔离子进程，访问已校验的后续 HTTPS 跳转。"""

    def request(self, url: str, *, timeout_s: float) -> HttpResponse:
        """读取后续跳转的状态和至多一个字节，不携带凭据。

        Args:
            url: 已校验的无用户信息 HTTPS 地址。
            timeout_s: 正数连接和读取超时，单位秒。

        Returns:
            未自动跳转的响应，响应体最多一个字节。

        Raises:
            ExternalError: URL 非法、子进程失败或总截止超时。

        Side Effects:
            启动隔离子进程，以 GET 和 Range 请求地址；不使用代理或令牌。

        Time Semantics:
            单次总时长不超过 HTTP_TOTAL_DEADLINE_S，不重试。
        """
        try:
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
                or parsed.port == 0
                or timeout_s <= 0
            ):
                failure = ValueError("unsafe url")
                raise failure
            return _bounded_request(
                "GET", url, {"Range": "bytes=0-0"}, timeout_s, first_byte_only=True
            )
        except (ValueError, OSError) as error:
            raise ExternalError(
                (
                    Diagnostic(
                        level=DiagnosticLevel.ERROR,
                        category=DiagnosticCategory.EXTERNAL,
                        stage="下载",
                        source="平台",
                        objects=(),
                        rule="download.redirect_request",
                        actual="后续跳转地址不可用",
                        expected="安全的 HTTPS 地址可访问",
                        consequence="当前文件下载失败",
                        next_step="检查镜像和网络后重试",
                    ),
                )
            ) from error


class _IsolatedRequest(Protocol):
    """隔离子进程请求的可注入边界，保留已有总截止和响应大小预算。"""

    def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        timeout_s: float,
        *,
        first_byte_only: bool = False,
    ) -> HttpResponse:
        """发送一次受限请求。"""
        ...


class MirrorRangeHttpTransport:
    """只对镜像执行首跳 Range 请求，不改变计划的公开传输。"""

    def __init__(self, *, send: _IsolatedRequest = _bounded_request) -> None:
        """绑定隔离请求能力，不读取配置和网络。

        Args:
            send: 单跳隔离请求，默认复用下载计划的内部设施。

        Returns:
            无。

        Raises:
            无。

        Side Effects:
            无。

        Time Semantics:
            构造时不等待、不访问网络。
        """
        self._send = send

    def request(
        self, method: str, url: str, *, headers: Mapping[str, str], timeout_s: float
    ) -> HttpResponse:
        """向镜像发送首跳 Range 请求，响应体至多读取一个字节。

        Args:
            method: 只接受 GET。
            url: hf-mirror.com 的 HTTPS 地址，不能有用户信息或片段。
            headers: Range bytes=0-0 和可选 Authorization；不输出内容。
            timeout_s: 正数连接和读取超时，单位秒。

        Returns:
            不自动重定向的响应，包含状态、头及最多一个字节。

        Raises:
            ExternalError: 地址、方法或头不合法，或连接失败。

        Side Effects:
            发送一次不走代理的 HTTPS 请求，可向镜像发送令牌。

        Time Semantics:
            共用计划传输的总时长和响应体预算，不自行重试。
        """
        try:
            parsed = urlsplit(url)
            if (
                method != "GET"
                or parsed.scheme != "https"
                or parsed.netloc != urlsplit(MIRROR_ENDPOINT).netloc
                or parsed.fragment
                or timeout_s <= 0
                or headers.get("Range") != "bytes=0-0"
                or any(key not in ("Range", "Authorization") for key in headers)
            ):
                failure = ValueError("invalid mirror request")
                raise failure
            return self._send(method, url, headers, timeout_s, first_byte_only=True)
        except (ValueError, OSError) as error:
            raise ExternalError(
                (
                    Diagnostic(
                        level=DiagnosticLevel.ERROR,
                        category=DiagnosticCategory.EXTERNAL,
                        stage="下载",
                        source="平台",
                        objects=(),
                        rule="download.mirror_range",
                        actual="镜像首跳请求无效或不可用",
                        expected="安全镜像地址可访问",
                        consequence="该文件失败",
                        next_step="检查镜像连接后重试",
                    ),
                )
            ) from error


class _RestartCurlError(Exception):
    """全局限速变化时停止当前 curl，并以已生效参数续传。"""

    def __init__(self, parameters: DownloadParameters) -> None:
        """携带已经确认的新限速供 curl 续传。"""
        self.parameters = parameters
        super().__init__()


class CurlDownloader:
    """串行执行 curl 兜底，敏感请求头仅从标准输入传递。"""

    def __init__(
        self,
        executable: Path,
        mirror: MirrorRangeTransport,
        redirects: RedirectTransport,
        *,
        run: Callable[[tuple[str, ...], bytes], HttpResponse] | None = None,
    ) -> None:
        """绑定 curl 程序和跳转传输。

        Args:
            executable: curl 程序路径或 PATH 中的名称。
            mirror: 首跳镜像单字节传输。
            redirects: 后续无令牌的单跳传输。
            run: 可注入的单次 curl 运行器；None 使用 M0 进程设施。

        Returns:
            无。

        Raises:
            无。

        Side Effects:
            无；不启动进程。

        Time Semantics:
            无等待或时钟读取。
        """
        self._executable = executable
        self._mirror = mirror
        self._redirects = redirects
        self._run = run if run is not None else _run_curl

    def download(
        self, url: str, target: Path, token: str | None, parameters: DownloadParameters
    ) -> None:
        """逐跳校验后以 curl 续传单文件。

        Args:
            url: 镜像 resolve 地址。
            target: 暂存文件路径。
            token: 可选令牌，不进入命令行或日志。
            parameters: 生效限速和重试参数。

        Returns:
            无；调用方仍需执行文件校验。

        Raises:
            ExternalError: 传输失败或跳转不符合策略。
            InputError: 跳转指向被禁止的地址。

        Side Effects:
            在暂存区续写目标；进程接受标准输入中的敏感配置。

        Time Semantics:
            逐跳至多五次，重试次数和限速由参数指定。
        """
        selected = resolve_download_url(url, token, self._mirror, self._redirects)
        executable = shutil.which(str(self._executable))
        if executable is None:
            failure = _adapter_error("未找到 curl 可执行文件")
            raise failure
        hop = 0
        while hop <= MAX_REDIRECT_HOPS:
            # 302 可能附带响应体，保留原大小以便丢弃被错误追加的正文。
            before = target.stat().st_size if target.exists() else 0
            args = [
                executable,
                "-q",
                "--noproxy",
                "*",
                "--proto",
                "=https",
                "--silent",
                "--show-error",
                "--fail",
                "--retry",
                str(parameters.max_tries),
                "-C",
                "-",
                "-K",
                "-",
                "--output",
                str(target),
            ]
            if parameters.max_overall_download_limit_bytes_per_s:
                args.extend(
                    ("--limit-rate", str(parameters.max_overall_download_limit_bytes_per_s))
                )
            args.append(selected)
            request_token = (
                token if urlsplit(selected).netloc == urlsplit(MIRROR_ENDPOINT).netloc else None
            )
            encoded = b""
            if request_token is not None:
                escaped = request_token.replace("\\", "\\\\").replace('"', '\\"')
                encoded = f'header = "Authorization: Bearer {escaped}"\n'.encode("ascii")
            try:
                response = self._run(tuple(args), encoded)
            except _RestartCurlError as change:
                parameters = change.parameters
                continue
            if response.status in (200, 206):
                return
            if 300 <= response.status < 400 and hop < MAX_REDIRECT_HOPS:
                location = next(
                    (value for key, value in response.headers.items() if key.lower() == "location"),
                    None,
                )
                if location is not None:
                    if target.exists():
                        with target.open("r+b") as stream:
                            stream.truncate(before)
                    selected = validate_download_redirect(selected, location)
                    hop += 1
                    continue
            failure = _adapter_error("curl 响应无效或重定向超限")
            raise failure
        failure = _adapter_error("curl 重定向循环异常")
        raise failure


def _run_curl(argv: tuple[str, ...], stdin_data: bytes) -> HttpResponse:
    """使用 M0 进程组运行 curl，读取有界响应头且不记录敏感配置。"""
    context = current()
    with tempfile.TemporaryDirectory(prefix="rdp-curl-") as directory:
        header_path = Path(directory) / "headers"
        command = ToolCommand(
            "curl",
            (*argv[:-1], "--dump-header", str(header_path), argv[-1]),
            Path(directory),
            7 * 24 * 3600.0,
        )
        process = ManagedExternalProcess(
            command, context.reporter, context.log, context.clock, stdin_data=stdin_data
        )
        try:
            process.start()
            deadline = time.monotonic() + command.timeout_s
            while process.running():
                context.reporter.check_cancelled()
                recheck()
                changed = adjustment()
                if isinstance(changed, DownloadParameters):
                    raise _RestartCurlError(changed)
                if time.monotonic() >= deadline:
                    failure = _adapter_error("curl 超过执行时限")
                    raise failure
                context.reporter.wait(0.05)
            if process.returncode() != 0:
                failure = _adapter_error("curl 传输失败")
                raise failure
        finally:
            process.stop()
        try:
            data = header_path.read_bytes()
            if len(data) > 128 * 1024:
                raise ValueError("oversize headers")
            blocks = data.decode("iso-8859-1").replace("\r\n", "\n").strip().split("\n\n")
            lines = blocks[-1].split("\n")
            status = int(lines[0].split()[1])
            headers: dict[str, str] = {}
            for line in lines[1:]:
                key, separator, value = line.partition(":")
                if separator:
                    headers[key] = value.strip()
            return HttpResponse(status, headers, b"")
        except (OSError, ValueError, IndexError) as error:
            failure = _adapter_error("curl 响应头无效")
            raise failure from error


class Aria2Supervisor:
    """通过已配置的 aria2c 可执行文件管理单次下载所需的进程。"""

    def __init__(self, config: JobsConfig, state_dir: Path) -> None:
        """保存 aria2 可执行文件与状态目录配置。

        Args:
            config: 包含 aria2c_path 的作业配置。
            state_dir: 平台状态目录绝对路径。

        Returns:
            无。

        Raises:
            DefectError: 状态目录不是绝对路径。

        Side Effects:
            无；不启动进程或读取文件。

        Time Semantics:
            同步构造，实际工具定位由执行阶段完成。
        """
        if not state_dir.is_absolute():
            raise DefectError()
        self.executable = Path(config.aria2c_path)
        self.state_dir = state_dir
        self._process: ManagedExternalProcess | None = None
        self._config_path: Path | None = None

    def start(self, parameters: DownloadParameters) -> Aria2JsonRpc:
        """启动受管 aria2 进程并连接本机 RPC。

        Args:
            parameters: 已校验的下载参数，不包含令牌。

        Returns:
            本地 RPC 客户端。

        Raises:
            ExternalError: 可执行文件、进程或 RPC 启动失败。
            DefectError: 缺少作业上下文或重复启动。

        Side Effects:
            创建权限 0600 的临时 RPC 配置文件并启动独立进程组。

        Time Semantics:
            RPC 就绪最多等待 15 秒；取消和 worker 停止可中断等待。
        """
        if self._process is not None:
            raise DefectError()
        context = current()
        resolved = shutil.which(str(self.executable))
        if resolved is None:
            failure = _adapter_error("未找到 aria2c 可执行文件")
            raise failure
        # 使用内核分配的临时端口；端口交接存在竞争，启动后通过 RPC 就绪检查失败收口。
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        secret = secrets.token_hex(32)
        try:
            descriptor, name = tempfile.mkstemp(prefix=".aria2-rpc-", dir=self.state_dir)
            self._config_path = Path(name)
            with os.fdopen(descriptor, "w", encoding="ascii") as config_file:
                config_file.write(f"rpc-secret={secret}\n")
            command = ToolCommand(
                "aria2c",
                (
                    resolved,
                    f"--conf-path={name}",
                    "--enable-rpc=true",
                    "--rpc-listen-all=false",
                    f"--rpc-listen-port={port}",
                    "--continue=true",
                    "--auto-file-renaming=false",
                    "--allow-overwrite=true",
                    "--file-allocation=none",
                    "--all-proxy=",
                    "--http-proxy=",
                    "--https-proxy=",
                    "--quiet=true",
                    "--console-log-level=error",
                    "--summary-interval=0",
                    f"--max-concurrent-downloads={parameters.max_concurrent_downloads}",
                    f"--max-connection-per-server={parameters.max_connection_per_server}",
                    f"--split={parameters.split}",
                    f"--min-split-size={parameters.min_split_size_bytes}",
                    f"--max-overall-download-limit={parameters.max_overall_download_limit_bytes_per_s}",
                    f"--max-tries={parameters.max_tries}",
                    f"--retry-wait={parameters.retry_wait_s}",
                ),
                self.state_dir,
                365 * 24 * 3600.0,
            )
            self._process = ManagedExternalProcess(
                command, context.reporter, context.log, context.clock
            )
            self._process.start()
            sender = _LocalRpc(port, secret)
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                context.reporter.check_cancelled()
                if not self._process.running():
                    failure = _adapter_error("aria2 启动后立即退出")
                    raise failure
                try:
                    sender("aria2.getVersion", [])
                    return Aria2JsonRpc(sender)
                except ExternalError:
                    context.reporter.wait(0.05)
            failure = _adapter_error("aria2 RPC 就绪超时")
            raise failure
        except BaseException:
            self.terminate()
            raise

    def terminate(self) -> None:
        """按 M0 进程组规则回收 aria2 和 RPC 临时配置。

        Args:
            无。

        Returns:
            无；重复调用安全。

        Raises:
            ExternalError: 进程或临时配置无法回收。

        Side Effects:
            TERM 后 KILL 进程组，并删除临时 RPC 配置。

        Time Semantics:
            清理由 M0 的有界等待策略控制。
        """
        try:
            if self._process is not None:
                self._process.stop()
                self._process = None
        finally:
            if self._config_path is not None:
                self._config_path.unlink(missing_ok=True)
                self._config_path = None


class _LocalRpc:
    """只对本机 aria2 RPC 发起 JSON 请求，不暴露密钥或响应正文。"""

    def __init__(self, port: int, secret: str) -> None:
        """绑定随机端口和每次启动生成的密钥。"""
        self._url = f"http://127.0.0.1:{port}/jsonrpc"
        self._secret = secret
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def __call__(self, method: str, args: Sequence[object]) -> object:
        """发送单次有界调用，拒绝异常或不完整响应。"""
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "rdp",
                "method": method,
                "params": [f"token:{self._secret}", *args],
            }
        ).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 - 地址由构造函数固定为本机 127.0.0.1。
            self._url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with self._opener.open(request, timeout=0.5) as response:
                raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("oversize response")
            result: object = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("invalid response")
            data = cast(dict[str, object], result)
            if data.get("id") != "rdp" or "error" in data or "result" not in data:
                raise ValueError("RPC error")
            return data["result"]
        except (OSError, ValueError) as error:
            failure = _adapter_error("本机 aria2 RPC 不可用或返回错误")
            raise failure from error


class Aria2JsonRpc:
    """将类型化下载操作转换成 aria2 JSON-RPC 参数。"""

    def __init__(self, send: Callable[[str, Sequence[object]], object]) -> None:
        """绑定单次本地 JSON-RPC 传输。

        Args:
            send: 接收方法名和参数并返回结果的有界调用。

        Returns:
            无。

        Raises:
            无。

        Side Effects:
            无；不连接 RPC。

        Time Semantics:
            每个方法调用时才发送请求。
        """
        self._send = send

    def add_file(self, url: str, target: Path, file: HubFile, token: str | None) -> str:
        """为单文件提交镜像预解析后的 URL 和可选校验。

        Args:
            url: 经预解析校验的下载地址。
            target: 暂存文件的绝对路径。
            file: 清单文件大小和散列。
            token: 可选镜像令牌，仅允许发给镜像主机。

        Returns:
            非空 aria2 GID。

        Raises:
            ExternalError: URI 或 RPC 返回无效。

        Side Effects:
            在本地 aria2 中登记文件，可能开始下载。

        Time Semantics:
            一个有界 RPC 调用，不等待下载完成。
        """
        options: dict[str, object] = {"dir": str(target.parent), "out": target.name}
        if file.lfs_sha256 is not None:
            options["checksum"] = f"sha-256={file.lfs_sha256}"
        if token is not None:
            if urlsplit(url).netloc != urlsplit(MIRROR_ENDPOINT).netloc:
                failure = _adapter_error("拒绝向非镜像发送令牌")
                raise failure
            options["header"] = [f"Authorization: Bearer {token}"]
        result = self._send("aria2.addUri", [[url], options])
        if not isinstance(result, str) or not result:
            failure = _adapter_error("aria2 返回的文件标识无效")
            raise failure
        return result

    def status(self, gid: str) -> TransferStatus:
        """读取单个 GID 的状态与可见错误码。

        Args:
            gid: add_file 返回的非空标识。

        Returns:
            非负字节、速率和归一化状态；无 HTTP 状态时为 None。

        Raises:
            ExternalError: RPC 响应不符合协议。

        Side Effects:
            发送一个只读 RPC。

        Time Semantics:
            值只反映本次观察。
        """
        result = self._send(
            "aria2.tellStatus",
            [
                gid,
                ["gid", "status", "completedLength", "downloadSpeed", "errorCode", "errorMessage"],
            ],
        )
        if not isinstance(result, dict):
            failure = _adapter_error("aria2 状态响应无效")
            raise failure
        data = cast(dict[str, object], result)
        state = data.get("status")
        if state == "paused":
            state = "waiting"
        if (
            state not in ("active", "waiting", "complete", "error", "removed")
            or data.get("gid") != gid
        ):
            failure = _adapter_error("aria2 状态或文件标识无效")
            raise failure
        try:
            completed = int(cast(str, data.get("completedLength", "0")))
            speed = int(cast(str, data.get("downloadSpeed", "0")))
            error_code = int(cast(str, data["errorCode"])) if "errorCode" in data else None
        except (ValueError, TypeError) as error:
            failure = _adapter_error("aria2 进度字段无效")
            raise failure from error
        if completed < 0 or speed < 0:
            failure = _adapter_error("aria2 进度出现负数")
            raise failure
        message = data.get("errorMessage")
        match = re.search(r"(?<!\d)(403|410)(?!\d)", message) if isinstance(message, str) else None
        http_status = int(match.group(1)) if match else None
        return TransferStatus(
            gid,
            state,
            completed,
            speed,
            http_status,
            error_code,
        )

    def change_global_options(self, adjustment: DownloadAdjustment) -> None:
        """应用文件并发或总限速调整。

        Args:
            adjustment: 至少一项非空，速率单位 bytes/s。

        Returns:
            无；RPC 成功后返回。

        Raises:
            ExternalError: 调整为空或 RPC 拒绝。

        Side Effects:
            更新 aria2 全局下载选项。

        Time Semantics:
            以 RPC 成功响应为生效时刻。
        """
        options: dict[str, str] = {}
        if adjustment.max_concurrent_downloads is not None:
            options["max-concurrent-downloads"] = str(adjustment.max_concurrent_downloads)
        if adjustment.max_overall_download_limit_bytes_per_s is not None:
            options["max-overall-download-limit"] = str(
                adjustment.max_overall_download_limit_bytes_per_s
            )
        if not options:
            failure = _adapter_error("调整项为空")
            raise failure
        self._send("aria2.changeGlobalOption", [options])

    def stop(self, gids: tuple[str, ...]) -> None:
        """移除活动文件并关闭 RPC 服务，失败仍继续清理。

        Args:
            gids: 尚未完成的文件标识。

        Returns:
            无。

        Raises:
            ExternalError: 任一移除或关闭调用失败。

        Side Effects:
            停止 aria2 中指定文件并请求关闭服务。

        Time Semantics:
            按输入顺序移除，最后发送 shutdown。
        """
        failure: ExternalError | None = None
        for gid in gids:
            try:
                self._send("aria2.forceRemove", [gid])
            except ExternalError as error:
                if failure is None:
                    failure = error
        try:
            self._send("aria2.shutdown", [])
        except ExternalError as error:
            if failure is None:
                failure = error
        if failure is not None:
            raise failure


def _adapter_error(actual: str) -> ExternalError:
    """构造不含外部响应或令牌的进程诊断。"""
    return ExternalError(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=DiagnosticCategory.EXTERNAL,
                stage="下载",
                source="平台",
                objects=(),
                rule="download.aria2",
                actual=actual,
                expected="本机下载工具正常工作",
                consequence="无法继续该文件",
                next_step="检查下载工具和网络后重试",
            ),
        )
    )
