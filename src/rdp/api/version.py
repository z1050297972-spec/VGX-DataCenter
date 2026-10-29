"""只读版本接口（11 M2），仅返回入口注入的快照，不在请求中调用 git 或读取部署文件。"""

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field, ValidationError

from rdp.infra.diagnostics import DefectError
from rdp.infra.version import PLATFORM_VERSION_TEXT


class VersionResponse(BaseModel):
    """供网页底部展示的服务端版本契约。

    Attributes:
        version: 与 rdp --version 相同的文字，1-128 个码点；提交缺失显示“未知”。
    """

    version: str = Field(min_length=1, max_length=128)


def configure_version(app: FastAPI, *, version: str) -> None:
    """为尚未启动的应用登记版本快照和只读查询路径。

    Args:
        app: create_app 返回、尚未构建中间件栈的应用。
        version: read_platform_version 结果，1-128 个码点，不含控制字符。

    Returns:
        无；登记 GET /api/version 和 VersionResponse，并使其优先于 API 兜底及静态挂载。

    Raises:
        DefectError: 应用已启动、重复装配或版本文字不合法。

    Side Effects:
        只修改 app 内存和 OpenAPI 缓存；接口采用已有认证边界，所有完成改密的登录账号可读。
        不增加公开白名单，不读数据库、存储根或构建文件；不改变健康接口的固定响应。

    Time Semantics:
        一次装配；整个进程期间版本固定，升级重启后才变化。
    """
    if app.middleware_stack is not None or hasattr(app.state, "platform_version"):
        raise DefectError
    _validate_version(version)
    app.state.platform_version = version
    app.add_api_route(
        "/api/version",
        get_version,
        methods=["GET"],
        response_model=VersionResponse,
        openapi_extra={"security": [{"SessionCookie": []}]},
    )
    # configure_version 也允许在工厂返回后装配，必须越过已经登记的兜底和静态挂载。
    app.router.routes.insert(0, app.router.routes.pop())
    app.openapi_schema = None


def get_version(request: Request) -> VersionResponse:
    """返回当前服务实例的版本快照。

    Args:
        request: 已完成身份检查的当前请求；app 已 configure_version。

    Returns:
        仅含 version 的响应；不包含文件路径、环境变量或运行时 git 信息。

    Raises:
        DefectError: 应用未配置版本或快照被破坏；由统一边界生成错误编号。

    Side Effects:
        无（只读应用内存，不写操作日志或运行日志）。

    Time Semantics:
        同步立即读取启动快照，不检查磁盘变化、不缓存请求时刻。
    """
    version = _validate_version(getattr(request.app.state, "platform_version", None))
    return VersionResponse(version=version)


def _validate_version(version: object) -> str:
    """把装配缺陷与不可信构建文件的输入问题区分开，复用同一文字约束。"""
    try:
        return PLATFORM_VERSION_TEXT.validate_python(version)
    except ValidationError as error:
        raise DefectError from error
