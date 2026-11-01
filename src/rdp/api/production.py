"""Web 生产适配（11），装配已有接口并管理 uvicorn 生命周期，不依赖 ops。

使用已有 create_app/configure_jobs/configure_storage；输入采用本模块类型，
包顶层组合入口将公共运行资源转换为此类型，避免 api 与 ops 相互 import。
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol, TypedDict, Unpack

from fastapi import FastAPI
from sqlalchemy import Engine

from rdp.api import create_app
from rdp.api.datasets import configure_datasets
from rdp.api.jobs import configure_jobs
from rdp.api.shutdown import drain_error_reports
from rdp.api.storage import configure_storage
from rdp.infra.config import StorageConfig, WebConfig
from rdp.infra.state import StatePaths
from rdp.infra.storage import MountInspector
from rdp.jobs.dataset_browser.service import DatasetBrowserService, read_unregistered_robot_models
from rdp.jobs.file_viewer import FileViewerService
from rdp.jobs.registry import JobRegistry
from rdp.jobs.scheduling_types import SchedulingCatalog

logger = logging.getLogger(__name__)

# 给已接收请求 30 秒完成；外部报错线程另有独立预算，不让长请求阻止 systemd 正常停机。
WEB_REQUEST_STOP_TIMEOUT_S = 30
# 报错数据库锁最多约 5 秒，另留同等调度/I/O 余量；超时不提前 dispose。
ERROR_REPORT_DRAIN_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class WebRuntime:
    """生产Web资源；原文件查看器独立取得只读访问预算，其余浏览查询仍只读导航。

    Attributes:
        dist: <部署目录>/src/web/dist 绝对路径，包含普通 index.html。
        settings: 配置的监听地址和端口，端口 1-65535。
        engine: 必填受管数据库引擎；本入口接管释放责任。
        paths: 已初始化状态目录，用于读取作业日志。
        registry: 完整生产登记表，已检查存储根名字。
        scheduling: 与 worker 相同规则构造的调度目录。
        inspector: 仅从挂载表和 UUID 判断存储根状态的检查器。
        clock: 返回 UTC aware datetime 的请求时钟。
        version: 启动时读取的版本文字，1-128 个码点，无控制字符。
        storage_options: 原文件查看器每次只读操作的秒级总预算，沿用存储配置。
        nav_root: 显式绝对导航根；生产CLI必传，None仅兼容不使用数据集接口的独立装配。
    """

    dist: Path
    settings: WebConfig
    engine: Engine
    paths: StatePaths
    registry: JobRegistry
    scheduling: SchedulingCatalog
    inspector: MountInspector
    clock: Callable[[], datetime]
    version: str
    nav_root: Path | None = None
    storage_options: StorageConfig = StorageConfig()


class UvicornOptions(TypedDict):
    """生产运行器必传的具名选项，直接对应 uvicorn.run，不复制框架全部配置。

    Attributes:
        host: 配置监听地址。
        port: 配置端口，1-65535。
        log_config: 固定 None，不覆盖统一日志配置。
        access_log: 固定 False，不重启访问日志。
        workers: 固定 1，覆盖 WEB_CONCURRENCY，保证日志单写者。
        timeout_graceful_shutdown: 请求退出宽限秒数，取 WEB_REQUEST_STOP_TIMEOUT_S。
    """

    host: str
    port: int
    log_config: None
    access_log: Literal[False]
    workers: Literal[1]
    timeout_graceful_shutdown: int


class UvicornRunner(Protocol):
    """已批准 uvicorn.run 的窄调用面，测试用不占用端口的运行替身。"""

    def __call__(self, app: FastAPI, **options: Unpack[UvicornOptions]) -> None:
        """运行一个已配置应用，保留平台日志输出与单进程模式。

        Args:
            app: 完成数据库、调度、存储与版本装配的应用。
            options: UvicornOptions 的全部具名参数，不能省略单进程、日志或退出预算字段。

        Returns:
            无；停止接收请求并完成应用生命周期后返回。

        Raises:
            Exception: 运行器故障向 Web 边界传播。
            SystemExit: uvicorn 启动/绑定失败的退出向 Web 边界传播。

        Side Effects:
            生产绑定监听 socket，workers 显式固定为 1，不 reload；测试替身只调用进程内应用。

        Time Semantics:
            持续运行到服务停止；已有请求最多宽限 WEB_REQUEST_STOP_TIMEOUT_S，
            使用 uvicorn 既有信号与异步运行器收尾，不重新安装 worker 信号。
        """
        ...


def start_web(runtime: WebRuntime, *, runner: UvicornRunner) -> int:
    """启动完整 Web 应用并在报错写入安全结束后释放数据库。

    Args:
        runtime: 完整且版本匹配的资源；engine 不允许 None，dist 不允许依赖 cwd。
        runner: uvicorn.run 或替身，显式传 log_config=None、access_log=False、workers=1，
            timeout_graceful_shutdown=WEB_REQUEST_STOP_TIMEOUT_S。

    Returns:
        正常停止为 0；应用装配、监听或运行失败为 1；报错线程清理超时也为 1。

    Raises:
        BaseException: 除 Exception 和 SystemExit 外的进程终止，完成可安全执行的清理后传播。

    Side Effects:
        create_app(dist, database=engine, clock=clock, platform_version=version) 内登记版本，
        返回后 configure_jobs(..., scheduling=...)、configure_storage(..., inspector=...)，
        导航根非空时configure_datasets，再单进程调用 runner，不二次 configure_version。
        启动时不访问存储根内容；M1.5查看器请求独立带超时只读。失败在本边界写一次诊断；数据库版本不匹配明确提示 rdp migrate。
        runner 结束/异常后调用 drain_error_reports；仅返回 True 才 dispose engine。
        超时保留引擎至进程退出，记录失败，不声称迟到线程已回收，不在同进程重启。
        调用运行器前以INFO记录平台版本；清理结束后另记退出码，正常为INFO、失败为ERROR，
        生命周期结束记录不重复原异常诊断或堆栈。

    Time Semantics:
        先停止接收请求，后等报错线程，最后关引擎；drain 最多 ERROR_REPORT_DRAIN_TIMEOUT_S 秒。
        uvicorn 的事件循环收尾由其运行器负责；永久磁盘阻塞最终由 systemd 停止期限结束进程。
    """
    app: FastAPI | None = None
    code = 1
    try:
        app = create_app(
            runtime.dist,
            database=runtime.engine,
            clock=runtime.clock,
            platform_version=runtime.version,
        )
        configure_jobs(app, runtime.paths, runtime.registry, scheduling=runtime.scheduling)
        configure_storage(app, inspector=runtime.inspector)
        if runtime.nav_root is not None:
            configure_datasets(
                app,
                DatasetBrowserService(
                    runtime.engine,
                    runtime.nav_root,
                    app.state.job_service,
                    read_unregistered_robot_models,
                ),
            )
        if runtime.nav_root is not None:
            app.state.file_viewer_service = FileViewerService(
                runtime.engine, runtime.nav_root, runtime.inspector, runtime.storage_options
            )
        logger.info("Web开始运行", extra={"fields": {"platform_version": runtime.version}})
        runner(
            app,
            host=runtime.settings.host,
            port=runtime.settings.port,
            log_config=None,
            access_log=False,
            workers=1,
            timeout_graceful_shutdown=WEB_REQUEST_STOP_TIMEOUT_S,
        )
        code = 0
    except FileNotFoundError:
        logger.error("前端构建产物缺失，请先构建")
        code = 1
    except (Exception, SystemExit):
        logger.error("Web运行失败，请查看诊断", exc_info=True)
        code = 1
    finally:
        try:
            if app is None or drain_error_reports(app, timeout_s=ERROR_REPORT_DRAIN_TIMEOUT_S):
                runtime.engine.dispose()
            else:
                logger.error("Web报错线程尚未结束，保留数据库引擎至进程退出")
                code = 1
        except BaseException:
            # 清理异常仍按原路径传播，但不能把本次入口结束误记为成功。
            code = 1
            raise
        finally:
            logger.log(
                logging.INFO if code == 0 else logging.ERROR,
                "Web结束运行：%s",
                "正常停止" if code == 0 else "失败退出",
                extra={"fields": {"exit_code": code}},
            )
    return code
