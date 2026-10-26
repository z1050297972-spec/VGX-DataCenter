"""日志测试的固定快照与临时数据库；只建立已批准的公开输入，不调用被测逻辑计算期望。"""

from accounts_support import AUDIT_CONTEXT, NOW

from rdp.audit.types import (
    AuditValues,
    ObjectRef,
    OperationDetails,
    OperationEvent,
    OperationResult,
    OperationType,
)
from rdp.infra.actors import ActorRef


def operation_event() -> OperationEvent:
    """提供新建账号成功事件，名字与编号有区分度，明细中没有任何秘密。"""
    return OperationEvent(
        NOW,
        ActorRef(7, "管理员甲"),
        OperationType.CREATE_ACCOUNT,
        ObjectRef("account", "11", "成员乙"),
        OperationResult.SUCCESS,
        None,
        AUDIT_CONTEXT,
        OperationDetails(
            before=AuditValues(),
            after=AuditValues(
                login_name="member",
                display_name="成员乙",
                role="member",
                status="enabled",
                must_change_password=True,
            ),
        ),
    )
