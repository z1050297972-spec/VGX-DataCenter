"""基础层首个迁移：只建报错表和时间索引（05 E2/F1），不创建账号、作业或日志表。

实现时冻结本版的列、约束名称和数值，不调用可变化的 Base.metadata.create_all；
迁移采用 SQLAlchemy/Alembic 标准类型，UTC 的底层表示为 TEXT。
"""

import sqlalchemy as sa
from alembic import op

from rdp.infra.diagnostics import Diagnostic, DiagnosticCategory, DiagnosticLevel, InputError

# 版本标识是 Alembic 的稳定图节点，无时间单位；首版没有父节点、分支标签或额外依赖。
revision: str = "0001_error_reports"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """创建报错表及按发生时刻清理所需的索引。

    Args:
        无；Alembic 提供在线迁移上下文和已开始的事务。

    Returns:
        无；error_reports 的列、CHECK、主键和 ix_error_reports_occurred_at 与首版模型一致。

    Raises:
        SQLAlchemyError: 表已存在、SQL、锁或 I/O 失败；由 migrate 按四类转换并补诊断。

    Side Effects:
        只创建 error_reports 及时间索引，版本表由 Alembic 管理；不建其他业务表。
        整体失败在外层显式事务中回滚，不留下半张表或虚假的最新版本。

    Time Semantics:
        必须在升级前备份完成且持有 BEGIN IMMEDIATE 后执行；无墙钟或重试。
    """
    # 冻结首版结构与阈值；不能引用后续会变化的 ORM 模型或常量。
    op.create_table(
        "error_reports",
        sa.Column("error_id", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.Text(), nullable=False),
        sa.Column("category", sa.String(8), nullable=False),
        sa.Column("summary", sa.String(512), nullable=False),
        sa.Column("report", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.String(7), nullable=False),
        sa.PrimaryKeyConstraint("error_id", name=op.f("pk_error_reports")),
        sa.CheckConstraint(
            "category IN ('input','conflict','external','defect')",
            name=op.f("ck_error_reports_category"),
        ),
        sa.CheckConstraint(
            "source_kind IN ('request','job')", name=op.f("ck_error_reports_source_kind")
        ),
        sa.CheckConstraint(
            "(source_kind = 'request' AND length(error_id) = 32 "
            "AND error_id NOT GLOB '*[^0-9a-f]*' AND substr(error_id,13,1) = '4' "
            "AND substr(error_id,17,1) IN ('8','9','a','b')) OR "
            "(source_kind = 'job' AND CAST(error_id AS INTEGER) > 0 "
            "AND CAST(CAST(error_id AS INTEGER) AS TEXT) = error_id)",
            name=op.f("ck_error_reports_source_identifier"),
        ),
        sa.CheckConstraint(
            "length(summary) BETWEEN 1 AND 512", name=op.f("ck_error_reports_summary_length")
        ),
        sa.CheckConstraint(
            "length(report) BETWEEN 1 AND 262144", name=op.f("ck_error_reports_report_length")
        ),
    )
    op.create_index(op.f("ix_error_reports_occurred_at"), "error_reports", ["occurred_at"])


def downgrade() -> None:
    """明确拒绝数据库降级，要求运维使用升级前备份恢复。

    Args:
        无。

    Returns:
        无；不正常返回。

    Raises:
        InputError: 任意调用均拒绝；诊断写明 F1 只允许向前迁移、未改变数据库，
            下一步为停止服务后人工恢复升级前备份及匹配的代码，不自动覆盖数据库。

    Side Effects:
        无；拒绝发生在执行 SQL 之前。

    Time Semantics:
        同步立即拒绝，不等待、不重试。
    """
    raise InputError(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=DiagnosticCategory.INPUT,
                stage="数据库迁移",
                source="平台",
                objects=(),
                rule="F1 只允许向前迁移",
                actual="请求数据库降级",
                expected="只运行升级",
                consequence="拒绝执行，数据库未改变",
                next_step="停止服务后人工恢复升级前备份及匹配的代码，不自动覆盖数据库",
            ),
        )
    )
