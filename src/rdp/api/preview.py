"""预览布局 HTTP 入口（M5-04），只读登记和 Profile，不进行机器人连接探测。"""

from fastapi import APIRouter
from pydantic import JsonValue

from rdp.api.collection import Identifier, ReadSession
from rdp.api.robot_profiles import ProfilesDependency
from rdp.collection.models import RobotRow
from rdp.collection.preview import build_preview_layout
from rdp.collection.profile import find_profile_by_model
from rdp.collection.service import CollectionNotFoundError
from rdp.infra.diagnostics import Diagnostic, DiagnosticCategory, DiagnosticLevel, DiagnosticObject

router = APIRouter(tags=["实时预览"])


@router.get("/api/robots/{robot_id}/preview-layout", operation_id="get_preview_layout")
def get_preview_layout(
    robot_id: Identifier, session: ReadSession, profiles: ProfilesDependency
) -> dict[str, JsonValue]:
    """为已登记机器人生成可供同源查看器导入的布局。

    Args:
        robot_id: 机器人永久编号，1 至 2^63-1。
        session: 当前请求的只读数据库事务，响应前释放。
        profiles: 通过认证取得的启动时 RobotProfile 快照。

    Returns:
        Lichtblick 1.30.0 裸布局 JSON，相机与位置曲线按 Profile 顺序生成。

    Raises:
        CollectionNotFoundError: 机器人不存在或型号没有 RobotProfile，404 带五段诊断。
        ExternalError: 登记数据库不可读，由统一数据库边界报告。
        DefectError: Profile 未装配，由依赖报告。

    Side Effects:
        无；只读登记数据库与内存快照，不连接机器人、不读取存储根。

    Time Semantics:
        机器人型号取请求事务快照，Profile 取进程启动版本；曲线时间语义见 build_preview_layout。
    """
    robot = session.get(RobotRow, robot_id)
    profile = find_profile_by_model(profiles, robot.robot_model) if robot is not None else None
    if profile is None:
        raise CollectionNotFoundError(
            (
                Diagnostic(
                    level=DiagnosticLevel.ERROR,
                    category=DiagnosticCategory.INPUT,
                    stage="生成预览布局",
                    source="平台",
                    objects=(DiagnosticObject(key="robot_id", value=str(robot_id)),),
                    rule="preview.profile" if robot is not None else "preview.robot",
                    actual="该型号没有 RobotProfile" if robot is not None else "机器人不存在",
                    expected="已登记机器人，且型号精确匹配 RobotProfile",
                    consequence="无法生成实时预览布局",
                    next_step="核对机器人型号，并由维护者补充对应 RobotProfile",
                ),
            )
        )
    return build_preview_layout(profile)
