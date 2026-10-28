"""存储根 HTTP 查询（入口层，10、L3），成员与管理员共享只读接口。

沿用全局账号鉴权与统一诊断，仅注入 MountInspector；没有存储根访问或写入能力。
应用工厂登记 schema，第 11 张启动入口负责配置实例，OpenAPI 导出不探测系统。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request

from rdp.api.account_auth import AccountRequestContext, get_authenticated_context
from rdp.api.storage_schemas import StorageRootsResponse
from rdp.infra.storage import MountInspector

router = APIRouter(prefix="/api/storage-roots", tags=["storage"])
AuthenticatedContext = Annotated[AccountRequestContext, Depends(get_authenticated_context)]


def configure_storage(app: FastAPI, *, inspector: MountInspector) -> None:
    """给应用绑定仅能核对挂载身份的依赖。

    Args:
        app: create_app 创建、尚未接收请求的独立应用。
        inspector: 必填关键字，含已校验根列表、系统表/UUID 回调和 UTC 时钟；空列表也显式提供。

    Returns:
        无；应用独享该不可变依赖，路由结构保持不变。

    Raises:
        DefectError: 依赖类型/登记内容非法、重复装配或应用已经开始处理请求。

    Side Effects:
        只修改 app.state；不读取配置、系统表、设备节点或根目录，不建线程或后台服务。

    Time Semantics:
        接收请求之前一次性调用，不取时钟、不等待外部资源。
    """
    raise NotImplementedError


def get_storage_inspector(request: Request, account: AuthenticatedContext) -> MountInspector:
    """取得已认证请求可用的挂载检查依赖。

    Args:
        request: 当前请求，只从其 app.state 取得实例依赖，不接受客户端配置。
        account: 全局账号认证结果，成员和管理员相同；未完成改密不放行。

    Returns:
        本应用已装配的 MountInspector，不缓存检查结果或另建系统适配器。

    Raises:
        AuthenticationError: 未登录或会话失效，沿用 401 和清 cookie。
        PasswordChangeRequiredError: 必须改口令，沿用 403。
        ExternalError: 没有装配存储依赖，返回带诊断的 502，不假装没有存储根。
        DefectError: app.state 中依赖损坏，沿用 500。

    Side Effects:
        仅复用认证上下文和会话刷新；不在这里读系统表或写操作日志。

    Time Semantics:
        身份时刻沿用请求上下文；检查时刻由随后 inspector 的时钟独立取得。
    """
    raise NotImplementedError


StorageInspector = Annotated[MountInspector, Depends(get_storage_inspector)]


@router.get("", response_model=StorageRootsResponse, operation_id="list_storage_roots")
def list_storage_roots(inspector: StorageInspector) -> StorageRootsResponse:
    """现场返回每个登记根的挂载状态摘要。

    Args:
        inspector: 已认证且完成依赖装配的请求检查器，没有根目录访问回调。

    Returns:
        配置顺序的名字、路径、写许可、在线标志、原因和 UTC 时刻；空配置 items 为空。
        一次请求调用一次 inspect；不暴露挂载表原文、UUID 或 NFS 来源，不返回 timeout。

    Raises:
        ExternalError: 系统表/UUID 元数据读取或解析失败，统一 502 与结构化诊断。
        DefectError: 注入时钟、依赖或结果不合法，统一 500，不吞成离线。

    Side Effects:
        无（只读挂载表和设备节点元数据）；不 stat 存储根，不记操作日志，不缓存响应。

    Time Semantics:
        每次请求现场检查，未发生根目录访问，不能据此承诺 NAS 响应正常；浏览器显示本地时间。
    """
    raise NotImplementedError
