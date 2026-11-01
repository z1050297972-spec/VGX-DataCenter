"""下载暂存删除入队策略；仅访问事务内作业记录，不触碰存储根。

复用既有登录授权和 SQLite 写事务，拒绝已登记下载或清理占用同一仓库。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from rdp.infra.diagnostics import ConflictError, DiagnosticCategory
from rdp.jobs import _storage
from rdp.jobs.models import JobRow

# 类型键是持久化协议，通用提交和重提必须一致识别。
DELETE_TYPE = "download_staging_delete"


def check_busy(session: Session, parameters: dict[str, object]) -> None:
    """在已取得写锁的事务中检查保守的仓库占用。

    Args:
        session: 已开启的受管写事务，与随后入队共享。
        parameters: 已校验的删除请求，含存储根、仓库类型和仓库编号。

    Returns:
        无；没有已登记的占用才返回。

    Raises:
        ConflictError: 同仓库有排队、运行或取消中的下载/清理作业。
        ExternalError: 数据库查询失败。

    Side Effects:
        仅读取数据库，不访问存储根或修改作业。

    Time Semantics:
        与随后入队在同一写事务内；只表示此时，worker 删除前仍需重新协调。
    """
    active = session.scalars(
        select(JobRow).where(
            JobRow.type_name.in_(("download", DELETE_TYPE)),
            JobRow.state.in_(("queued", "running", "cancelling")),
        )
    )
    fields = ("storage_root", "repo_type", "repo_id")
    for row in active:
        if all(row.parameters.get(key) == parameters.get(key) for key in fields):
            raise ConflictError(
                (
                    _storage.diagnostic(
                        row.job_id, "下载暂存目录正被作业使用", DiagnosticCategory.CONFLICT
                    ),
                )
            )
