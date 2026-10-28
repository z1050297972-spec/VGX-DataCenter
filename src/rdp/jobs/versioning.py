"""作业执行版本持久化（11 M2），领域层只接收版本快照，不发现部署或调用 git。

版本随领取事务写入，复用 SQLAlchemy Session 和已有状态校验；不另开提交事务。
"""

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rdp.infra.diagnostics import ConflictError, DefectError, DiagnosticCategory
from rdp.infra.version import PLATFORM_VERSION_TEXT
from rdp.jobs import _storage
from rdp.jobs.models import JobRow
from rdp.jobs.records import find_job
from rdp.jobs.types import JobState


def record_execution_version(session: Session, job_id: int, *, version: str) -> None:
    """在一次实际领取的事务中记录运行该作业的平台版本。

    Args:
        session: 调用方已入场的写事务，与 claim_job 或 assign_recovery_gpu 共用。
        job_id: 本事务领取后处于 running 的正作业编号。
        version: 本 worker 启动快照，1-128 个码点，不含控制字符。

    Returns:
        无；jobs.platform_version 等于本次领取的版本。

    Raises:
        JobNotFoundError: 作业不存在。
        ConflictError: 作业不处于 running，拒绝给排队、取消中或终态冒写执行版本。
        InputError: 作业存量行损坏。
        ExternalError: 数据库写入失败，调用方回滚整个领取事务。
        DefectError: 编号或版本参数非法、只读会话或 SQL/映射错误。

    Side Effects:
        只更新当前作业版本，不提交、不写操作日志；失败不留下脱离领取事务的版本记录。
        恢复后重新领取覆盖为此次执行版本；仅准备恢复、提交、取消或查询不会改写版本。
        自动退回未启动领取时与领取其他字段一并恢复先前版本，避免标记未真正运行的新版本。

    Time Semantics:
        在领取状态/资源更新之后、事务提交和执行线程启动之前调用；
        排队期间升级取新 worker 的版本，运行期间文件变化不改变快照。
    """
    job_id = _storage.identifier(job_id, internal=True)
    try:
        PLATFORM_VERSION_TEXT.validate_python(version)
    except ValidationError as error:
        raise DefectError from error
    with _storage.operation(session, write=True):
        record = find_job(session, job_id)
        if record.state is not JobState.RUNNING:
            raise ConflictError(
                (
                    _storage.diagnostic(
                        job_id, "只有运行中作业可记录执行版本", DiagnosticCategory.CONFLICT
                    ),
                )
            )
        row = session.get(JobRow, job_id)
        if row is not None:
            row.platform_version = version
            session.flush()
