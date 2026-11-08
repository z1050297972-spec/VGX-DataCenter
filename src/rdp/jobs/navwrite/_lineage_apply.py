"""人工血缘写入时补齐审计身份；不重新计算关系、编号或删除决策。

预览时写作业尚未分配编号，因此仅在落恢复日志前填入实际写作业元数据；
其余计划、前像和指纹保持不变，恢复与冲突检查仍由已有流水线负责。
"""

from sqlalchemy import Engine

from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import DefectError
from rdp.infra.timeutil import ensure_utc
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.navwrite import _create_plan as plans
from rdp.jobs.navwrite.jsonio import dump_navigation_json, load_navigation_json
from rdp.jobs.navwrite.lineage_parameters import LINEAGE_PREVIEW_TYPE, LineageParameters
from rdp.jobs.navwrite.models import NavPreview, WriteFileStep
from rdp.jobs.records import find_job


def prepare(engine: Engine, context: ExecutionContext, preview: NavPreview) -> NavPreview:
    """按持久作业类型识别人工登记，删除和其他预览保持原计划。"""
    with session_scope(engine, read_only=True) as session:
        source = find_job(session, preview.preview_job_id)
        if source.type_name != LINEAGE_PREVIEW_TYPE:
            return preview
        actor = find_job(session, context.job_id).submitted_by
    parameters = LineageParameters.model_validate(preview.parameters)
    if parameters.action == "remove":
        return preview
    if len(preview.plan.steps) != 1 or not isinstance(preview.plan.steps[0], WriteFileStep):
        raise DefectError()
    step = preview.plan.steps[0]
    payload = load_navigation_json(step.after_content.encode("utf-8"))
    lineage = payload["lineage"]
    if not isinstance(lineage, list) or not lineage or not isinstance(lineage[-1], dict):
        raise DefectError()
    record = lineage[-1]
    record["job_id"] = context.job_id
    record["recorded_by"] = {
        "kind": "人工补录",
        "account_id": actor.account_id,
        "account_name": actor.name,
        "at": ensure_utc(context.clock.now()).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    content = dump_navigation_json(payload)
    stamped = step.model_copy(
        update={"after": plans.image(content), "after_content": content.decode("utf-8")}
    )
    return preview.model_copy(
        update={"plan": preview.plan.model_copy(update={"steps": (stamped,)})}
    )
