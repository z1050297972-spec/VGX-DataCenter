"""基础层唯一 SQLAlchemy 表元数据（工单 05）；仅声明，不创建表或访问数据库。

第 06-08 张的模型继承 Base，复用 metadata 和约束命名；表结构变更只走 Alembic。
SQLite 的 VARCHAR 不限制长度，因此文本上界同时声明 CHECK，不能只依赖 Python 校验。
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, Integer, MetaData, String, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from rdp.infra.db.utc import UTCDateTime
from rdp.infra.db.validation import ERROR_SOURCE_CHECK_SQL
from rdp.infra.ids import REQUEST_ID_HEX_LENGTH

# 工单 05 按规范 2.7 限制：报告最多 262144 个 Unicode 字符，最坏约 1 MiB UTF-8。
# 日志格式化与报错表共用这一上限，数据库层不再次截断，避免 D2 的两份报告不一致。
MAX_EXCEPTION_REPORT_CHARS = 262144
# 报错摘要是单行安全说明，单位 Unicode 字符；512 足以容纳平台固定摘要，拒绝静默裁剪。
MAX_ERROR_SUMMARY_CHARS = 512
# 截断标记计入报告上限；保留前缀以避免吞掉入口栈，明确告知维护者内容有损。
REPORT_TRUNCATION_MARKER = "\n[报告超出字符上限，后续内容已截断]\n"

# SQLAlchemy 推荐的模板机制；ck 要求调用者提供稳定的业务约束名，防止迁移名称漂移。
metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


class Base(DeclarativeBase):
    """所有平台表的 SQLAlchemy 2 声明式基类，不触发建表。

    Attributes:
        metadata: 本模块唯一 MetaData，无单位、不可空；默认共享 metadata，禁止各表另建。
    """

    metadata = metadata


class ErrorReportRow(Base):
    """每个请求或作业至多一条不可覆盖的完整报错，首个迁移仅建此表。

    Attributes:
        error_id: 主键，无单位、不可空、无默认；请求为 32 位小写 uuid4 hex，作业为
            1-9223372036854775807 的无前导零十进制文本。两种编号格式互斥，故不加代理主键。
        occurred_at: 发生时刻，UTCDateTime、微秒，不可空、无默认；由边界传入，不由数据库取时钟。
        category: 类别 input/conflict/external/defect，无单位、不可空、无默认；Web 仅存 defect。
        summary: 一句话安全摘要，1-512 个 Unicode 字符，不可空、无默认，不存原始异常消息。
        report: format_exception_report 的同一输出，1-262144 个 Unicode 字符，
            不可空、无默认；含异常链及 traceback，超长在格式化边界截断并标记，本层不二次裁剪。
        source_kind: request 或 job，无单位、不可空、无默认；来源编号就是 error_id，
            不另存易失配的 source_id；作业不伪装成请求，也不复用 ProblemResponse。
    """

    __tablename__ = "error_reports"
    __table_args__ = (
        CheckConstraint("category IN ('input','conflict','external','defect')", name="category"),
        CheckConstraint("source_kind IN ('request','job')", name="source_kind"),
        CheckConstraint(
            ERROR_SOURCE_CHECK_SQL,
            name="source_identifier",
        ),
        CheckConstraint(
            f"length(summary) BETWEEN 1 AND {MAX_ERROR_SUMMARY_CHARS}", name="summary_length"
        ),
        CheckConstraint(
            f"length(report) BETWEEN 1 AND {MAX_EXCEPTION_REPORT_CHARS}", name="report_length"
        ),
    )

    error_id: Mapped[str] = mapped_column(String(REQUEST_ID_HEX_LENGTH), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(8), nullable=False)
    summary: Mapped[str] = mapped_column(String(MAX_ERROR_SUMMARY_CHARS), nullable=False)
    report: Mapped[str] = mapped_column(Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(7), nullable=False)


class MonitoringMirrorRow(Base):
    """worker 最近一次镜像检查结果。

    Attributes:
        id: 唯一结果的主键。
        status: 生效、不生效或未知。
        checked_at: 检查时间的 UTC 文本；未检查为 None。
        requested_seq: 手动检查请求累计序号。
        completed_seq: 已消费的请求序号。
    """

    __tablename__ = "monitoring_mirror"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_seq: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    completed_seq: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class MonitoringResourcesRow(Base):
    """worker 最近一次资源采集快照。

    Attributes:
        id: 唯一快照主键。
        snapshot: 不含存储路径的 JSON 快照。
    """

    __tablename__ = "monitoring_resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot: Mapped[str] = mapped_column(Text, nullable=False)
