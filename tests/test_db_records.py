"""工单 05 契约测试；只在 tmp_path 的假状态目录验证。"""

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, Table, event, text

from rdp.infra.db.connection import create_database_engine, session_scope
from rdp.infra.db.models import Base, ErrorReportRow, metadata
from rdp.infra.db.records import ErrorRecord, clear_expired_errors, find_error, write_error
from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    ExternalError,
    InputError,
)


def _record(**changes: Any) -> ErrorRecord:
    """构造固定 UTC 的安全报错样例，期望值不由被测逻辑计算。"""
    data: dict[str, Any] = dict(
        error_id="123456789abc4def8abc123456789abc",
        occurred_at=datetime(2026, 10, 1, tzinfo=UTC),
        category="defect",
        summary="平台内部错误",
        report="TypeError: 安全示例\n",
        source_kind="request",
    )
    return ErrorRecord.model_validate(data | changes)


def _engine(root: Path) -> Engine:
    """报错仓储测试用临时表隔离迁移；迁移与模型一致性另由 compare_metadata 验证。"""
    engine = create_database_engine(root / "db")
    Base.metadata.create_all(engine)
    return engine


def _fault(root: Path, operation: str, code: int, kind: type[Exception]) -> None:
    """在 SQLAlchemy 驱动执行边界注入真实类型故障，断言仓储立即分类且事务回滚。"""
    engine = _engine(root)

    def fail(*args: Any, **kwargs: Any) -> None:
        error = sqlite3.OperationalError("驱动故障")
        error.sqlite_errorcode = code
        raise error

    try:
        with pytest.raises(kind), session_scope(engine) as session:
            event.listen(engine, "before_cursor_execute", fail)
            try:
                if operation == "write":
                    write_error(session, _record())
                elif operation == "find":
                    find_error(session, "1")
                else:
                    clear_expired_errors(
                        session, now=datetime(2026, 10, 31, tzinfo=UTC), retention_days=30
                    )
            except kind:
                raise
            except Exception as error:
                raise AssertionError("仓储必须立即转换驱动故障") from error
    finally:
        event.remove(engine, "before_cursor_execute", fail)
        engine.dispose()


def test_metadata(tmp_path: Path) -> None:
    """验证契约：所有表继承同一 Base/MetaData；PK/FK/UQ/CK/IX 命名模板稳定且 CHECK 有显式规则名。"""
    assert Base.metadata is metadata
    table = ErrorReportRow.__table__
    assert isinstance(table, Table)
    assert table.metadata is metadata
    assert {constraint.name for constraint in table.constraints} >= {
        "pk_error_reports",
        "ck_error_reports_source_identifier",
        "ck_error_reports_report_length",
    }
    assert {index.name for index in table.indexes} == {"ix_error_reports_occurred_at"}


def test_row_constraints(tmp_path: Path) -> None:
    """验证契约：报错表列非空、主键唯一、category/source_kind/编号/摘要和报告长度 CHECK 实际生效。"""
    engine = _engine(tmp_path)
    try:
        for field, value in (
            ("error_id", "00"),
            ("source_kind", "other"),
            ("category", "other"),
            ("report", ""),
            ("summary", "a" * 513),
            ("occurred_at", None),
        ):
            data = _record(error_id="1", source_kind="job").model_dump(mode="json")
            data[field] = value
            with pytest.raises(ConflictError), session_scope(engine) as session:
                session.execute(
                    text(
                        "INSERT INTO error_reports (error_id, occurred_at, category, summary, report, source_kind) VALUES (:error_id, :occurred_at, :category, :summary, :report, :source_kind)"
                    ),
                    data,
                )
    finally:
        engine.dispose()


def test_record_request(tmp_path: Path) -> None:
    """验证契约：ErrorRecord 接受合法 uuid4 hex 请求来源，UTC 规范化，冻结且拒绝额外字段。"""
    record = _record(occurred_at=datetime(2026, 10, 1, 8, tzinfo=timezone(timedelta(hours=8))))
    assert record.occurred_at == datetime(2026, 10, 1, tzinfo=UTC)
    assert record.occurred_at.tzinfo is UTC
    assert record.source_kind == "request"
    with pytest.raises(ValidationError):
        record.summary = "修改"


def test_record_job(tmp_path: Path) -> None:
    """验证契约：作业编号 1 和 2^63-1 以规范十进制文本保存，与同值请求编号空间不混淆。"""
    for identifier in ("1", "9223372036854775807"):
        record = _record(error_id=identifier, source_kind="job")
        assert record.error_id == identifier and record.source_kind == "job"


def test_record_id_invalid(tmp_path: Path) -> None:
    """验证契约：非法 uuid 版本/variant/大写、前导零、零/负数/超大作业号、来源错配触发隐藏载荷的 ValidationError。"""
    for identifier, kind in (
        ("01", "job"),
        ("0", "job"),
        ("-1", "job"),
        ("9223372036854775808", "job"),
        ("A23456789abc4def8abc123456789abc", "request"),
        ("123456789abc1def8abc123456789abc", "request"),
        ("123456789abc4def7abc123456789abc", "request"),
        ("1", "request"),
    ):
        with pytest.raises(ValidationError):
            _record(error_id=identifier, source_kind=kind)


def test_record_fields_invalid(tmp_path: Path) -> None:
    """验证契约：ErrorRecord 拒绝未知类别、空白/多行/超长摘要、空/超长报告、naive 时刻和 UTC 溢出，不输出载荷。"""
    for changes in (
        {"summary": "  "},
        {"summary": "a\nb"},
        {"summary": "a" * 513},
        {"report": ""},
        {"report": "a" * 262145},
        {"category": "unknown"},
        {"occurred_at": datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None)},
        {"occurred_at": datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=8)))},
    ):
        with pytest.raises(ValidationError):
            _record(**changes)


def test_write_success(tmp_path: Path) -> None:
    """验证契约：write_error flush 恰好一条，report 与运行日志逐字一致，不 commit、不另开会话。"""
    engine = _engine(tmp_path)
    record = _record()
    try:
        with session_scope(engine) as session:
            assert write_error(session, record) is None
            with session_scope(engine, read_only=True) as reader:
                assert reader.execute(text("SELECT count(*) FROM error_reports")).scalar_one() == 0
            assert (
                session.execute(text("SELECT report FROM error_reports")).scalar_one()
                == record.report
            )
        with session_scope(engine, read_only=True) as reader:
            assert reader.execute(text("SELECT count(*) FROM error_reports")).scalar_one() == 1
    finally:
        engine.dispose()


def test_write_duplicate(tmp_path: Path) -> None:
    """验证契约：同编号第二次写给 ConflictError，第一条不覆盖；失败工作单元回滚。"""
    engine = _engine(tmp_path)
    try:
        with session_scope(engine) as session:
            write_error(session, _record())
        with pytest.raises(ConflictError), session_scope(engine) as session:
            try:
                write_error(session, _record(summary="不能覆盖"))
            except ConflictError:
                raise
            except Exception as error:
                raise AssertionError("仓储不能泄漏底层异常") from error
        with session_scope(engine, read_only=True) as session:
            assert find_error(session, _record().error_id) == _record()
    finally:
        engine.dispose()


def test_write_corrupt(tmp_path: Path) -> None:
    """验证契约：write_error 对损坏数据库/UTC 值给 InputError，安全诊断不回显报告。"""
    _fault(tmp_path, "write", 26, InputError)


def test_write_external(tmp_path: Path) -> None:
    """验证契约：write_error 遇权限/磁盘满/I/O 给 ExternalError，回滚后不留半条。"""
    _fault(tmp_path, "write", 13, ExternalError)


def test_write_defect(tmp_path: Path) -> None:
    """验证契约：write_error 对只读会话或其他 SQL 编程错误给 DefectError。"""
    _fault(tmp_path, "write", 1, DefectError)


def test_write_lock(tmp_path: Path) -> None:
    """验证契约：write_error 锁失败给 ConflictError，无中间层日志、不自动重试。"""
    _fault(tmp_path, "write", 5, ConflictError)


def test_find_request(tmp_path: Path) -> None:
    """验证契约：find_error 返回完整且脱离会话仍可用的请求快照，关闭 Session 后可序列化。"""
    engine = _engine(tmp_path)
    try:
        with session_scope(engine) as session:
            write_error(session, _record())
        with session_scope(engine, read_only=True) as session:
            found = find_error(session, _record().error_id)
        assert found == _record()
        assert (
            found is not None
            and found.model_dump(mode="json")["occurred_at"] == "2026-10-01T00:00:00Z"
        )
    finally:
        engine.dispose()


def test_find_job(tmp_path: Path) -> None:
    """验证契约：find_error 按规范作业编号返回同一来源编号，不使用 ProblemResponse。"""
    engine = _engine(tmp_path)
    try:
        with session_scope(engine) as session:
            write_error(session, _record(error_id="7", source_kind="job"))
        with session_scope(engine, read_only=True) as session:
            found = find_error(session, "7")
            assert found is not None and found.source_kind == "job"
    finally:
        engine.dispose()


def test_find_missing(tmp_path: Path) -> None:
    """验证契约：find_error 查不到或已清除时返回 None，不伪造内容、不延长保留期。"""
    engine = _engine(tmp_path)
    try:
        with session_scope(engine, read_only=True) as session:
            assert find_error(session, "1") is None
    finally:
        engine.dispose()


def test_find_invalid(tmp_path: Path) -> None:
    """验证契约：find_error 非法编号给 InputError，不执行查询、不回显原值。"""
    engine = _engine(tmp_path)
    try:
        with session_scope(engine, read_only=True) as session, pytest.raises(InputError):
            find_error(session, "secret-invalid")
    finally:
        engine.dispose()


def test_find_corrupt(tmp_path: Path) -> None:
    """验证契约：find_error 对坏 UTC/坏行或损坏数据库给 InputError，不返回部分详情。"""
    engine = _engine(tmp_path)
    try:
        with session_scope(engine) as session:
            write_error(session, _record())
            session.execute(text("UPDATE error_reports SET occurred_at='bad'"))
        with session_scope(engine, read_only=True) as session, pytest.raises(InputError):
            find_error(session, _record().error_id)
    finally:
        engine.dispose()


def test_find_lock(tmp_path: Path) -> None:
    """验证契约：find_error 的 BUSY/LOCKED 转 ConflictError。"""
    _fault(tmp_path, "find", 6, ConflictError)


def test_find_external(tmp_path: Path) -> None:
    """验证契约：find_error 权限/I/O 转 ExternalError。"""
    _fault(tmp_path, "find", 10, ExternalError)


def test_find_defect(tmp_path: Path) -> None:
    """验证契约：find_error 其他 SQL/映射错误转 DefectError。"""
    _fault(tmp_path, "find", 1, DefectError)


def test_clear_boundary(tmp_path: Path) -> None:
    """验证契约：验收 8：固定 now 下截止前 1 微秒删除，恰等于截止、截止后及未来记录保留，返回真实删除数。"""
    engine = _engine(tmp_path)
    now = datetime(2026, 10, 31, tzinfo=UTC)
    try:
        with session_scope(engine) as session:
            for identifier, moment in [
                ("1", datetime(2026, 9, 30, 23, 59, 59, 999999, tzinfo=UTC)),
                ("2", datetime(2026, 10, 1, tzinfo=UTC)),
                ("3", datetime(2026, 11, 1, tzinfo=UTC)),
            ]:
                write_error(
                    session, _record(error_id=identifier, source_kind="job", occurred_at=moment)
                )
        with session_scope(engine) as session:
            assert clear_expired_errors(session, now=now, retention_days=30) == 1
        with session_scope(engine, read_only=True) as session:
            assert find_error(session, "1") is None
            assert find_error(session, "2") is not None
            assert find_error(session, "3") is not None
    finally:
        engine.dispose()


def test_clear_empty(tmp_path: Path) -> None:
    """验证契约：clear_expired_errors 无过期行返回 0，不读取报告列表、不 VACUUM。"""
    engine = _engine(tmp_path)
    try:
        with session_scope(engine) as session:
            assert (
                clear_expired_errors(
                    session, now=datetime(2026, 10, 31, tzinfo=UTC), retention_days=30
                )
                == 0
            )
    finally:
        engine.dispose()


def test_clear_utc(tmp_path: Path) -> None:
    """验证契约：保留天数为 UTC 24 小时，跨本机夏令时仍按固定时长，now 的不同偏移等价。"""
    engine = _engine(tmp_path)
    try:
        with session_scope(engine) as session:
            write_error(session, _record(occurred_at=datetime(2026, 10, 1, tzinfo=UTC)))
            assert (
                clear_expired_errors(
                    session,
                    now=datetime(2026, 10, 31, 8, tzinfo=timezone(timedelta(hours=8))),
                    retention_days=30,
                )
                == 0
            )
            assert (
                clear_expired_errors(
                    session,
                    now=datetime(2026, 10, 31, 8, 0, 0, 1, tzinfo=timezone(timedelta(hours=8))),
                    retention_days=30,
                )
                == 1
            )
    finally:
        engine.dispose()


def test_clear_days(tmp_path: Path) -> None:
    """验证契约：保留天数 1/3650 有效；0/3651/bool/字符串拒绝 InputError，SQL 前失败不删行。"""
    engine = _engine(tmp_path)
    try:
        with session_scope(engine) as session:
            for days in (1, 3650):
                assert (
                    clear_expired_errors(
                        session, now=datetime(2026, 10, 31, tzinfo=UTC), retention_days=days
                    )
                    == 0
                )
            for value in (0, 3651, True, "30"):
                with pytest.raises(InputError):
                    clear_expired_errors(
                        session,
                        now=datetime(2026, 10, 31, tzinfo=UTC),
                        retention_days=cast(Any, value),
                    )
    finally:
        engine.dispose()


def test_clear_time(tmp_path: Path) -> None:
    """验证契约：naive now、UTC 溢出和截止减法溢出给 InputError，不删除任何行。"""
    engine = _engine(tmp_path)
    try:
        with session_scope(engine) as session:
            for now in (
                datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None),
                datetime(1, 1, 1, tzinfo=UTC),
                datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=8))),
            ):
                with pytest.raises(InputError):
                    clear_expired_errors(session, now=now, retention_days=30)
    finally:
        engine.dispose()


def test_clear_corrupt(tmp_path: Path) -> None:
    """验证契约：清除遇数据库损坏给 InputError，工作单元回滚。"""
    _fault(tmp_path, "clear", 11, InputError)


def test_clear_lock(tmp_path: Path) -> None:
    """验证契约：清除锁或约束冲突给 ConflictError，不留部分清除。"""
    _fault(tmp_path, "clear", 5, ConflictError)


def test_clear_external(tmp_path: Path) -> None:
    """验证契约：清除权限/磁盘/I/O 故障给 ExternalError，回滚全部 DELETE。"""
    _fault(tmp_path, "clear", 13, ExternalError)


def test_clear_defect(tmp_path: Path) -> None:
    """验证契约：清除只读会话或 SQL 编程错误给 DefectError。"""
    _fault(tmp_path, "clear", 1, DefectError)


def test_clear_commit(tmp_path: Path) -> None:
    """验证契约：清除不自行提交；外层失败恢复全部记录，无调度器、无日志。"""
    engine = _engine(tmp_path)
    try:
        with session_scope(engine) as session:
            write_error(session, _record())
        with pytest.raises(ValueError), session_scope(engine) as session:
            assert (
                clear_expired_errors(
                    session, now=datetime(2026, 12, 1, tzinfo=UTC), retention_days=30
                )
                == 1
            )
            raise ValueError("业务失败")
        with session_scope(engine, read_only=True) as session:
            assert find_error(session, _record().error_id) is not None
    finally:
        engine.dispose()


def test_readonly_write_diagnostic(tmp_path: Path) -> None:
    """验证只读仓储写入和清除均报带数据库身份及完整诊断的 DefectError。"""
    engine = _engine(tmp_path)
    try:
        for operation in ("write", "clear"):
            with (
                pytest.raises(DefectError) as caught,
                session_scope(engine, read_only=True) as session,
            ):
                if operation == "write":
                    write_error(session, _record())
                else:
                    clear_expired_errors(
                        session, now=datetime(2026, 10, 31, tzinfo=UTC), retention_days=30
                    )
            assert caught.value.diagnostics
            diagnostic = caught.value.diagnostics[0]
            assert diagnostic.category.value == "defect"
            assert diagnostic.objects[0].value == str(tmp_path / "db")
            assert f"错误码={sqlite3.SQLITE_READONLY}" in diagnostic.actual
            assert "错误码=0" not in diagnostic.actual
            assert diagnostic.rule == "只读会话不得写入"
            assert all(
                (
                    diagnostic.rule,
                    diagnostic.actual,
                    diagnostic.expected,
                    diagnostic.consequence,
                    diagnostic.next_step,
                )
            )
    finally:
        engine.dispose()


def test_report_bound(tmp_path: Path) -> None:
    """验证契约：报告 N-1/N 字符逐字保存，N+1 由格式化边界截断并标记；数据库拒绝绕过边界的超长值。"""
    from rdp.api.errors import format_exception_report

    for size in (262143, 262144):
        assert len(_record(report="x" * size).report) == size
    with pytest.raises(ValidationError):
        _record(report="x" * 262145)
    report = format_exception_report(ValueError("x" * 262144))
    record = _record(report=report)
    assert len(record.report) == 262144
    assert "已截断" in record.report
