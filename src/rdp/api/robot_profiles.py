"""RobotProfile 只读 HTTP 入口（M5-01）；登录成员共用启动时的事实快照。

从部署布局定位 profiles，不接触机器人、存储根或工具配置。离线 OpenAPI 仅注册模型，
生产启动显式装配读取；请求参数只匹配快照标识，绝不拼接文件路径。
"""

from http import HTTPStatus
from pathlib import Path
from typing import Annotated, cast

from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import BaseModel, ConfigDict

from rdp.api.account_auth import AccountRequestContext, get_authenticated_context
from rdp.collection.profile import load_robot_profiles
from rdp.collection.profile_models import RobotProfile
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    InputError,
)
from rdp.infra.version import deployment_layout

router = APIRouter(prefix="/api/robot-profiles", tags=["robot-profiles"])
AuthenticatedContext = Annotated[AccountRequestContext, Depends(get_authenticated_context)]


class RobotProfileSummary(BaseModel):
    """说明档列表的一行，不复制机器人连接信息。

    Attributes:
        profile: 说明档稳定标识。
        version: 正整数事实版本号。
        model: 机器人型号字符串。
        unknown_count: 未确认事实的数量，非负，关节名按组记一项。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    profile: str
    version: int
    model: str
    unknown_count: int


class RobotProfileList(BaseModel):
    """说明档列表响应。

    Attributes:
        items: 按部署文件名排序的摘要，可为空。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    items: tuple[RobotProfileSummary, ...]


class _ProfileNotFoundError(InputError):
    """指定说明档标识不存在，沿用统一 404 诊断。"""

    http_status = HTTPStatus.NOT_FOUND


def configure_robot_profiles(app: FastAPI, *, profiles_dir: Path | None = None) -> None:
    """在启动时读取并装配应用独享的 RobotProfile 快照。

    Args:
        app: 尚未接收请求的应用。
        profiles_dir: 本地 profiles 绝对目录；None 从当前 rdp 包的部署布局定位，规则与 tools 相同。

    Returns:
        无；后续请求使用已校验快照，不重读文件。

    Raises:
        InputError: 部署布局或文件格式不合格，携带完整安全诊断并阻止启动。
        ExternalError: 部署目录解析或读取失败，携带诊断并阻止启动。

    Side Effects:
        只读部署文件，成功后设置 app.state.robot_profiles；失败不装配部分结果。

    Time Semantics:
        启动时调用一次，本地同步加载，不重试；文件变更须重启后生效。
    """
    if profiles_dir is None:
        profiles_dir = (
            deployment_layout(Path(__file__).parents[1] / "__init__.py").root / "profiles"
        )
    app.state.robot_profiles = load_robot_profiles(profiles_dir)


def _get_profiles(request: Request, account: AuthenticatedContext) -> tuple[RobotProfile, ...]:
    """认证后取启动快照；漏装配属于程序缺陷，不伪装成空目录。"""
    profiles = getattr(request.app.state, "robot_profiles", None)
    if profiles is None:
        raise DefectError()
    return cast(tuple[RobotProfile, ...], profiles)


ProfilesDependency = Annotated[tuple[RobotProfile, ...], Depends(_get_profiles)]


@router.get("", response_model=RobotProfileList, operation_id="list_robot_profiles")
def list_robot_profiles(profiles: ProfilesDependency) -> RobotProfileList:
    """向登录账号返回说明档摘要和未知事实数量。

    Args:
        profiles: 已认证请求取得的启动快照，按文件名排序。

    Returns:
        所有说明档的身份和未知项计数，保持快照顺序，允许空列表。

    Raises:
        DefectError: 应用未装配说明档，由依赖报告程序缺陷。

    Side Effects:
        无；仅读内存，不连接机器人或读取磁盘。

    Time Semantics:
        返回进程启动时的事实版本；不声称是机器人实时状态。
    """
    return RobotProfileList(
        items=tuple(
            RobotProfileSummary(
                profile=item.profile,
                version=item.version,
                model=item.model,
                unknown_count=item.unknown_count,
            )
            for item in profiles
        )
    )


@router.get(
    "/{profile}",
    response_model=RobotProfile,
    response_model_exclude_none=True,
    operation_id="get_robot_profile",
)
def get_robot_profile(profile: str, profiles: ProfilesDependency) -> RobotProfile:
    """向登录账号返回指定说明档的结构化全文。

    Args:
        profile: 说明档标识，只在内存中精确匹配，不解释为路径。
        profiles: 当前应用启动时读取的快照。

    Returns:
        说明档的已知事实；未知值省略，明确无目标保留 none=true。

    Raises:
        _ProfileNotFoundError: 标识不在快照中，返回统一 404 诊断。
        DefectError: 应用漏装配说明档，由依赖报告。

    Side Effects:
        无；不读文件，不执行就绪检查。

    Time Semantics:
        与列表共用同一启动快照；无轮询或网络等待。
    """
    item = next((item for item in profiles if item.profile == profile), None)
    if item is None:
        raise _ProfileNotFoundError(
            (
                Diagnostic(
                    level=DiagnosticLevel.ERROR,
                    category=DiagnosticCategory.INPUT,
                    stage="读取 RobotProfile",
                    source="平台",
                    objects=(DiagnosticObject(key="profile", value=profile),),
                    rule="robot_profile.not_found",
                    actual="说明档不存在",
                    expected="已登记的说明档标识",
                    consequence="无法查看说明档详情",
                    next_step="刷新说明档列表后重新选择",
                ),
            )
        )
    return item
