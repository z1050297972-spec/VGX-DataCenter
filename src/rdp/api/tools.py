"""工具库 HTTP 入口（M4-01），成员只读；状态及诊断均由工具领域生成。

ADR 0006 的例外仅允许读登记包与工具程序的 stat/指纹，不访问其他存储根文件。
不执行转换工具、不写工具库或数据库；列表请求可只读探测 LeRobot 环境。
应用装配和 OpenAPI 导出不触发工具文件读取或环境探测。
"""

from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request

from rdp.api.account_auth import AccountRequestContext, get_authenticated_context
from rdp.api.tool_schemas import ToolDetailResponse, ToolListResponse, ToolSummaryResponse
from rdp.infra.config import ToolsConfig
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
    InputError,
)
from rdp.jobs.conversion.lerobot import inspect_environment
from rdp.tools.registry import RegisteredTool, ToolRegistry, load_tool_registry

router = APIRouter(prefix="/api/tools", tags=["tools"])
AuthenticatedContext = Annotated[AccountRequestContext, Depends(get_authenticated_context)]


class _ToolNotFoundError(InputError):
    """请求的登记包不存在；保持统一输入异常和 404 映射。"""

    http_status = HTTPStatus.NOT_FOUND


def configure_tools(app: FastAPI, *, settings: ToolsConfig) -> None:
    """为独立应用装配只读工具登记位置。

    Args:
        app: 尚未接收请求的应用。
        settings: 已校验的工具库和登记包绝对路径配置，不接受客户端路径。

    Returns:
        无；后续请求从此应用的配置读取工具状态。

    Raises:
        无。

    Side Effects:
        只设置 app.state.tools_config，不打开文件或运行外部程序。

    Time Semantics:
        启动时调用一次；请求时现场读取清单，配置变更须重启应用。
    """
    app.state.tools_config = settings


def _get_registry(request: Request, account: AuthenticatedContext) -> ToolRegistry:
    """认证完成后读取登记，部署目录故障转为统一外部失败，不伪装空列表。"""
    settings = getattr(request.app.state, "tools_config", None)
    if not isinstance(settings, ToolsConfig):
        raise DefectError()
    try:
        return load_tool_registry(settings.registry_dir, settings.library_root)
    except OSError as error:
        raise ExternalError(
            (
                Diagnostic(
                    level=DiagnosticLevel.ERROR,
                    category=DiagnosticCategory.EXTERNAL,
                    stage="工具登记",
                    source="平台",
                    objects=(DiagnosticObject(key="registry", value=str(settings.registry_dir)),),
                    rule="tools.registry_read",
                    actual=f"登记目录无法读取（{type(error).__name__}）",
                    expected="可读取的平台 tools 登记目录",
                    consequence="无法查询工具库",
                    next_step="检查平台 tools 目录和服务读取权限",
                ),
            )
        ) from error


RegistryDependency = Annotated[ToolRegistry, Depends(_get_registry)]


@router.get("", response_model=ToolListResponse, operation_id="list_tools")
def list_tools(request: Request, registry: RegistryDependency) -> ToolListResponse:
    """向登录成员返回全部工具的登记摘要和状态。

    Args:
        request: 含部署工具配置的请求。
        registry: 认证后读取的工具快照，包含清单无效的条目。

    Returns:
        按工具名排序的列表，含程序路径、登记指纹前 12 位及五段诊断。

    Raises:
        ExternalError: 登记根目录不可读取，经统一边界返回 502。

    Side Effects:
        只读登记包和工具程序；已配置 LeRobot 时在只读断网沙箱探测，不写操作日志。

    Time Semantics:
        返回本次请求快照；LeRobot 的导入和源码指纹探测各至多 15 秒，失败保留 error 状态，不阻止列表返回。
    """
    return ToolListResponse(
        items=tuple(_summary(item) for item in registry.items),
        lerobot_environment=inspect_environment(request.app.state.tools_config),
    )


@router.get("/{name}", response_model=ToolDetailResponse, operation_id="get_tool")
def get_tool(name: str, registry: RegistryDependency) -> ToolDetailResponse:
    """返回指定登记工具的配置全文及命令模板。

    Args:
        name: 登记包目录名，只在快照中匹配，不拼接为文件路径。
        registry: 认证后读取的快照，配置全文和配置哈希来自同一份字节。

    Returns:
        摘要、配置快照、命令模板和源码说明；清单无效时详情字段为空并保留诊断。

    Raises:
        _ToolNotFoundError: name 不存在，映射为 404，诊断包含请求的工具名。
        ExternalError: 登记根目录读取失败，统一返回 502。

    Side Effects:
        无；不读取源码仓库，不执行 --version，不修改工具或配置。

    Time Semantics:
        详情沿用本次请求的登记快照；不自动重试，不解释源码提交时间。
    """
    item = next((item for item in registry.items if item.name == name), None)
    if item is None:
        raise _ToolNotFoundError(
            (
                Diagnostic(
                    level=DiagnosticLevel.ERROR,
                    category=DiagnosticCategory.INPUT,
                    stage="工具详情",
                    source="平台",
                    objects=(DiagnosticObject(key="tool", value=name),),
                    rule="tools.not_found",
                    actual="工具未登记",
                    expected="已存在的登记包名称",
                    consequence="无法查看工具详情",
                    next_step="刷新工具列表后重新选择",
                ),
            )
        )
    manifest = item.manifest
    return ToolDetailResponse(
        **_summary(item).model_dump(),
        configurations=item.configurations,
        command=manifest.command if manifest else None,
        source_commit=manifest.tool.source_commit if manifest else None,
        source_note=manifest.tool.source_note if manifest else None,
    )


def _summary(item: RegisteredTool) -> ToolSummaryResponse:
    """只投影已校验的事实；坏清单不尝试从原始 TOML 抢救字段。"""
    manifest = item.manifest
    return ToolSummaryResponse(
        name=item.name,
        version=manifest.tool.version if manifest else None,
        summary=manifest.tool.summary if manifest else None,
        input_format=manifest.io.input_format if manifest else None,
        output_format=manifest.io.output_format if manifest else None,
        output_versions=manifest.io.output_versions if manifest else (),
        robot_models=tuple(manifest.models) if manifest else (),
        cleaning_models=tuple(manifest.cleaning) if manifest else (),
        needs_gpu=manifest.runtime.needs_gpu if manifest else None,
        status=item.status,
        diagnostics=item.diagnostics,
        program_path=str(item.program_path) if item.program_path else None,
        sha256_prefix=manifest.program.sha256[:12] if manifest else None,
    )
