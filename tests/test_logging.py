"""工单 03 日志行为测试；所有文件样例限于 tmp_path。"""

import asyncio
import io
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from rdp.infra.config import LoadedConfig, LogConfig, PlatformConfig
from rdp.infra.logging import (
    LoggingSettings,
    LogTime,
    RuntimeFormatter,
    configure_logging,
    job_id_context,
    log_config_source,
    log_context,
    log_state_warnings,
    request_id_context,
)
from rdp.infra.state import initialize_state, state_paths


@dataclass
class _Clock:
    """测试可推进的墙钟，不读取系统时钟或修改进程时区。

    Attributes:
        value: aware 时刻，精度微秒，默认固定 UTC 时刻。
        zone: 展示和切分时区，默认固定 +08:00。
    """

    value: datetime = datetime(2026, 10, 21, 8, 15, 2, 123999, tzinfo=UTC)
    zone: tzinfo = timezone(timedelta(hours=8))

    def now(self) -> datetime:
        """提供当前测试时刻。"""
        return self.value

    def local_zone(self) -> tzinfo:
        """提供当前测试时区。"""
        return self.zone

    def source(self) -> LogTime:
        """把可推进依赖交给被测公开边界。"""
        return LogTime(self.now, self.local_zone)


def _record(fields: object = None, message: str = "完成", **values: object) -> logging.LogRecord:
    """生成标准日志输入，期望文本仍在每个测试里独立写出。"""
    return logging.makeLogRecord(
        {
            "name": "rdp.test",
            "levelname": "INFO",
            "levelno": logging.INFO,
            "msg": message,
            "args": (),
            "fields": {} if fields is None else fields,
            **values,
        }
    )


def test_formatter_construction(tmp_path: Path) -> None:
    """验证契约：RuntimeFormatter.__init__：返回实例，不读时钟、不冻结时区、不修改全局 logging。"""

    def forbidden() -> datetime:
        """构造阶段不应读取时钟。"""
        raise AssertionError("构造时读取时钟")

    before = list(logging.getLogger().handlers)
    formatter = RuntimeFormatter(LogTime(now=forbidden))
    assert isinstance(formatter, logging.Formatter)
    assert logging.getLogger().handlers == before


def test_exact_line_format(tmp_path: Path) -> None:
    """验证契约：验收 3：固定 UTC 时钟与 +08:00 时区，逐字断言时间到毫秒、级别、模块、中文消息及有序 key=value。"""
    formatter = RuntimeFormatter(_Clock().source())
    record = _record({"total": 3, "dataset": "样本"})
    assert (
        formatter.format(record)
        == '2026-10-21 16:15:02.123+08:00 INFO rdp.test 完成 dataset="样本" total=3'
    )


def test_milliseconds_truncated(tmp_path: Path) -> None:
    """验证契约：RuntimeFormatter.format：微秒 123999 截断为 .123，绝不舍入；展示带本地偏移，UTC 跨日换算正确。"""
    clock = _Clock(datetime(2026, 10, 21, 23, 59, 59, 999999, tzinfo=UTC))
    text = RuntimeFormatter(clock.source()).format(_record())
    assert text.startswith("2026-10-22 07:59:59.999+08:00 ")


def test_no_extra_fields(tmp_path: Path) -> None:
    """验证契约：RuntimeFormatter.format 返回：未传 fields 或空映射且无绑定时无尾随空格，不附加空编号。"""
    formatter = RuntimeFormatter(_Clock().source())
    record = logging.makeLogRecord({"name": "x", "levelname": "INFO", "msg": "消息", "args": ()})
    assert formatter.format(record) == "2026-10-21 16:15:02.123+08:00 INFO x 消息"
    assert not formatter.format(_record({})).endswith(" ")


def test_field_order_and_context(tmp_path: Path) -> None:
    """验证契约：RuntimeFormatter.format 返回：用户字段按键排序，job_id/request_id 按固定顺序追加，不重复。"""
    job_token = job_id_context.set(12)
    request_token = request_id_context.set("123456789abc4def8123456789abcdef")
    try:
        text = RuntimeFormatter(_Clock().source()).format(_record({"z": 2, "a": 1}))
    finally:
        request_id_context.reset(request_token)
        job_id_context.reset(job_token)
    assert text.endswith(" a=1 z=2 job_id=12 request_id=123456789abc4def8123456789abcdef")


def test_quoted_field_values(tmp_path: Path) -> None:
    """验证契约：RuntimeFormatter.format 返回：空串、空格、等号、换行、引号、反斜杠用 JSON 字符串转义；中文不转成 ASCII。"""
    text = RuntimeFormatter(_Clock().source()).format(
        _record(
            {
                "empty": "",
                "eq": "a=b",
                "line": "a\nb",
                "quote": 'a"b',
                "slash": "a\\b",
                "space": "a b",
            }
        )
    )
    assert text.endswith('empty="" eq="a=b" line="a\\nb" quote="a\\"b" slash="a\\\\b" space="a b"')


def test_scalar_field_values(tmp_path: Path) -> None:
    """验证契约：RuntimeFormatter.format 返回：安全字符串原样输出，整数/有限浮点/bool/None 输出确定的 JSON 标量。"""
    text = RuntimeFormatter(_Clock().source()).format(
        _record({"a": "safe/path", "b": True, "c": None, "d": 4, "e": 1.25})
    )
    assert text.endswith(" a=safe/path b=true c=null d=4 e=1.25")


def test_multiline_diagnostics(tmp_path: Path) -> None:
    """验证契约：RuntimeFormatter.format：CRLF/CR 归一为 LF，明细含空行缩进四空格，字段只放首行且无末尾换行。"""
    text = RuntimeFormatter(_Clock().source()).format(
        _record({"count": 2}, "诊断\r\n明细\r\n\r结束")
    )
    assert (
        text == "2026-10-21 16:15:02.123+08:00 INFO rdp.test 诊断 count=2\n    明细\n    \n    结束"
    )
    assert not text.endswith("\n")


def test_exception_and_stack_details(tmp_path: Path) -> None:
    """验证契约：RuntimeFormatter.format：标准异常链、traceback 和 stack_info 均缩进，主消息及原异常缓存不被修改。"""
    try:
        try:
            raise ValueError("原始错误")
        except ValueError as cause:
            raise RuntimeError("上层错误") from cause
    except RuntimeError as error:
        record = _record(
            exc_info=(type(error), error, error.__traceback__), stack_info="调用栈\n某处"
        )
    text = RuntimeFormatter(_Clock().source()).format(record)
    assert "ValueError: 原始错误" in text and "RuntimeError: 上层错误" in text
    assert "    调用栈\n    某处" in text
    assert all(line.startswith("    ") for line in text.splitlines()[1:])
    assert record.exc_text is None and record.msg == "完成"


def test_invalid_fields(tmp_path: Path) -> None:
    """验证 P2：坏键加引号、保留键丢弃、非标量与非映射字符串化，str 失败和非有限数也不丢整行。"""

    class Broken:
        """模拟错误路径上自身也无法字符串化的值。"""

        def __str__(self) -> str:
            raise RuntimeError("不应导致整行丢失")

    formatter = RuntimeFormatter(_Clock().source())
    text = formatter.format(
        _record(
            {
                "bad key": "still here",
                "job_id": "forged",
                "path": tmp_path,
                "nan": float("nan"),
                "broken": Broken(),
            }
        )
    )
    assert '"bad key"="still here"' in text
    assert "job_id=forged" not in text
    assert f"path={tmp_path}" in text
    assert 'nan="nan"' in text and 'broken="<无法字符串化>"' in text
    assert "完成" in formatter.format(_record(["list", "value"]))
    assert "fields=" in formatter.format(_record(42))


def test_invalid_time_source(tmp_path: Path) -> None:
    """验证契约：RuntimeFormatter.format/configure_logging Raises：naive 时钟或无有效偏移的时区被拒绝为 ValueError。"""
    clock = _Clock()
    clock.value = clock.value.replace(tzinfo=None)
    with pytest.raises(ValueError):
        RuntimeFormatter(clock.source()).format(_record())
    with pytest.raises(ValueError):
        configure_logging(LoggingSettings("web", tmp_path), time_source=clock.source())
    assert not (tmp_path / "web.log").exists()


def test_format_message_type_error(tmp_path: Path) -> None:
    """验证契约：RuntimeFormatter.format Raises：不匹配的消息格式参数保留 TypeError，不产生部分缓存。"""
    record = _record(message="数字 %d", args=("不是数字",))
    with pytest.raises(TypeError):
        RuntimeFormatter(_Clock().source()).format(record)


def test_format_time_overflow(tmp_path: Path) -> None:
    """验证契约：RuntimeFormatter.format Raises：时区换算越出 datetime 年范围报 OverflowError。"""
    clock = _Clock(datetime.max.replace(tzinfo=UTC))
    with pytest.raises(OverflowError):
        RuntimeFormatter(clock.source()).format(_record())


def test_record_snapshot(tmp_path: Path) -> None:
    """验证契约：RuntimeFormatter.format 副作用：同记录多次格式化复用时刻/时区/上下文，fields、消息及 contextvars 不变。"""
    clock = _Clock()
    formatter = RuntimeFormatter(clock.source())
    record = _record({"a": 1})
    token = job_id_context.set(21)
    try:
        first = formatter.format(record)
    finally:
        job_id_context.reset(token)
    clock.value += timedelta(days=2)
    clock.zone = UTC
    assert formatter.format(record) == first
    assert record.msg == "完成" and record.__dict__["fields"] == {"a": 1}
    assert job_id_context.get() is None


def test_format_no_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """验证契约：RuntimeFormatter.format 副作用：仅返回文本，不写文件或 stderr；校验失败不留下部分快照。"""
    record = _record(message="%d", args=("bad",))
    formatter = RuntimeFormatter(_Clock().source())
    with patch.object(Path, "open", side_effect=AssertionError("格式化不得读写文件")):
        with pytest.raises(TypeError):
            formatter.format(record)
        assert "_rdp_snapshot" not in record.__dict__
        record.msg = "正常"
        record.args = ()
        assert "正常" in formatter.format(record)
    assert capsys.readouterr().err == ""


def test_web_file_only(tmp_path: Path) -> None:
    """验证契约：验收 6/configure_logging 返回：web 仅创建/追加 web.log，UTF-8 中文正确，不创建 worker.log。"""
    configure_logging(LoggingSettings("web", tmp_path), time_source=_Clock().source())
    logging.getLogger("rdp.test").info("启动完成")
    assert (tmp_path / "web.log").read_text(
        encoding="utf-8"
    ) == "2026-10-21 16:15:02.123+08:00 INFO rdp.test 启动完成\n"
    assert not (tmp_path / "worker.log").exists()


def test_worker_file_only(tmp_path: Path) -> None:
    """验证契约：验收 6/configure_logging 返回：worker 仅创建/追加 worker.log，不需要 worker 入口。"""
    configure_logging(LoggingSettings("worker", tmp_path), time_source=_Clock().source())
    logging.getLogger("rdp.test").warning("作业结束")
    assert "WARNING rdp.test 作业结束" in (tmp_path / "worker.log").read_text(encoding="utf-8")
    assert not (tmp_path / "web.log").exists()


def test_stderr_disabled(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """验证契约：验收 6/ADR 0005：stderr=False 时不向 stderr 输出，包括运行期 handler 的 I/O 错误。"""
    configure_logging(LoggingSettings("web", tmp_path, stderr=False), time_source=_Clock().source())
    logging.getLogger("rdp.test").error("可见文件错误")
    with patch("logging.FileHandler.emit", side_effect=OSError("模拟日志写失败")):
        logging.getLogger("rdp.test").error("写入失败也不写 stderr")
    assert capsys.readouterr().err == ""
    assert "可见文件错误" in (tmp_path / "web.log").read_text(encoding="utf-8")


def test_stderr_enabled(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """验证契约：configure_logging：stderr=True 同时输出文件和当前 sys.stderr，复用同条日志的时间及编号。"""
    configure_logging(LoggingSettings("web", tmp_path, stderr=True), time_source=_Clock().source())
    with log_context(job_id=12):
        logging.getLogger("rdp.test").info("双路输出")
    assert capsys.readouterr().err == (tmp_path / "web.log").read_text(encoding="utf-8")
    assert "job_id=12" in (tmp_path / "web.log").read_text(encoding="utf-8")


def test_level_filtering(tmp_path: Path) -> None:
    """验证契约：configure_logging：DEBUG/INFO/WARNING/ERROR 阈值生效；默认 INFO 不输出 DEBUG。"""
    for level, expected in (("DEBUG", 4), ("INFO", 3), ("WARNING", 2), ("ERROR", 1)):
        folder = tmp_path / level
        folder.mkdir()
        configure_logging(
            LoggingSettings("web", folder, log=LogConfig.model_validate({"level": level})),
            time_source=_Clock().source(),
        )
        for number in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR):
            logging.getLogger("rdp.test").log(number, "级别检查")
        assert len((folder / "web.log").read_text(encoding="utf-8").splitlines()) == expected


def test_uvicorn_loggers(tmp_path: Path) -> None:
    """验证契约：configure_logging：uvicorn 和 uvicorn.error 启动/错误日志传播到统一格式，只写一次。"""
    for name in ("uvicorn", "uvicorn.error"):
        target = logging.getLogger(name)
        target.disabled = True
        target.propagate = False
        target.addHandler(logging.NullHandler())
    configure_logging(LoggingSettings("web", tmp_path), time_source=_Clock().source())
    logging.getLogger("uvicorn").info("启动服务器")
    logging.getLogger("uvicorn.error").error("服务失败")
    lines = (tmp_path / "web.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("INFO uvicorn 启动服务器")
    assert lines[1].endswith("ERROR uvicorn.error 服务失败")


def test_uvicorn_access_disabled(tmp_path: Path) -> None:
    """验证契约：验收 7：uvicorn.access 被禁用且不传播，对 /api/health 的访问记录也无输出。"""
    configure_logging(LoggingSettings("web", tmp_path), time_source=_Clock().source())
    logging.getLogger("uvicorn.access").info("GET /api/health 200")
    assert (tmp_path / "web.log").read_text(encoding="utf-8") == ""
    assert logging.getLogger("uvicorn.access").disabled
    assert not logging.getLogger("uvicorn.access").propagate


def test_repeat_configuration(tmp_path: Path) -> None:
    """验证契约：configure_logging 副作用：配两次不重复输出，关闭旧自有 handler，外部 handler 仅摘除而不关闭。"""
    external = logging.StreamHandler(io.StringIO())
    logging.getLogger().addHandler(external)
    with patch.object(external, "close", wraps=external.close) as external_close:
        configure_logging(LoggingSettings("web", tmp_path), time_source=_Clock().source())
        old = next(h for h in logging.getLogger().handlers if isinstance(h, logging.FileHandler))
        configure_logging(LoggingSettings("web", tmp_path), time_source=_Clock().source())
        assert old.stream is None
        external_close.assert_not_called()
    logging.getLogger("rdp.test").info("只写一次")
    assert (tmp_path / "web.log").read_text(encoding="utf-8").count("只写一次") == 1
    external.close()


def test_reconfigure_destination(tmp_path: Path) -> None:
    """验证契约：configure_logging：换 process、目录、级别或 stderr 后只写新目的地，旧日志内容及目录权限不变。"""
    configure_logging(LoggingSettings("web", tmp_path, stderr=True), time_source=_Clock().source())
    logging.getLogger("rdp.test").info("旧文件")
    old = (tmp_path / "web.log").read_bytes()
    folder = tmp_path / "new"
    folder.mkdir()
    configure_logging(
        LoggingSettings("worker", folder, log=LogConfig(level="ERROR")),
        time_source=_Clock().source(),
    )
    logging.getLogger("rdp.test").info("过滤")
    logging.getLogger("rdp.test").error("新文件")
    assert (tmp_path / "web.log").read_bytes() == old
    assert "新文件" in (folder / "worker.log").read_text(encoding="utf-8")
    assert "过滤" not in (folder / "worker.log").read_text(encoding="utf-8")


def test_unrelated_loggers_unchanged(tmp_path: Path) -> None:
    """验证契约：configure_logging：除 root 和三个 uvicorn logger 外其他命名 logger 状态不被修改。"""
    target = logging.getLogger("rdp.unrelated")
    before = (target.handlers[:], target.level, target.propagate, target.disabled)
    configure_logging(LoggingSettings("web", tmp_path), time_source=_Clock().source())
    assert (target.handlers, target.level, target.propagate, target.disabled) == before


def test_invalid_logging_settings(tmp_path: Path) -> None:
    """验证契约：configure_logging Raises：非法 process 或相对 log_dir 抛 ValueError，旧 logging 配置不变。"""
    before = (logging.getLogger().handlers[:], logging.getLogger().level, logging.raiseExceptions)
    for settings in (
        LoggingSettings(cast(Any, "other"), tmp_path),
        LoggingSettings("web", Path("relative")),
    ):
        with pytest.raises(ValueError):
            configure_logging(settings, time_source=_Clock().source())
        assert (
            logging.getLogger().handlers,
            logging.getLogger().level,
            logging.raiseExceptions,
        ) == before
    assert not list(tmp_path.iterdir())


def test_missing_log_directory(tmp_path: Path) -> None:
    """验证契约：configure_logging Raises：日志目录缺失报 FileNotFoundError，不隐式建目录。"""
    directory = tmp_path / "missing"
    with pytest.raises(FileNotFoundError):
        configure_logging(LoggingSettings("web", directory), time_source=_Clock().source())
    assert not directory.exists()


def test_log_directory_is_file(tmp_path: Path) -> None:
    """验证契约：configure_logging Raises：日志目录被普通文件占用报 NotADirectoryError。"""
    directory = tmp_path / "file"
    directory.write_text("保留", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        configure_logging(LoggingSettings("web", directory), time_source=_Clock().source())
    assert directory.read_text(encoding="utf-8") == "保留"


def test_logging_setup_io_failure(tmp_path: Path) -> None:
    """验证契约：configure_logging Raises：打开/追加文件或检查状态失败保留 OSError，关闭本次新 handler，保留旧配置。"""
    configure_logging(LoggingSettings("web", tmp_path), time_source=_Clock().source())
    old = list(logging.getLogger().handlers)
    error = PermissionError(13, "不可写", str(tmp_path / "worker.log"))
    with patch("builtins.open", side_effect=error), pytest.raises(OSError) as caught:
        configure_logging(LoggingSettings("worker", tmp_path), time_source=_Clock().source())
    assert caught.value is error and logging.getLogger().handlers == old
    logging.getLogger("rdp.test").info("旧配置仍可写")
    assert "旧配置仍可写" in (tmp_path / "web.log").read_text(encoding="utf-8")


def test_failed_setup_leaves_empty_file(tmp_path: Path) -> None:
    """验证契约：configure_logging 失败副作用：允许留下本次新建空文件，不删除既有文件、不留下半套 logger 配置。"""
    configure_logging(LoggingSettings("web", tmp_path), time_source=_Clock().source())
    old = list(logging.getLogger().handlers)
    opened: list[logging.Handler] = []
    original = logging.Handler.setFormatter

    def fail_stderr(handler: logging.Handler, formatter: logging.Formatter | None) -> None:
        """文件已打开后让第二个输出失败，以检查回滚和资源清理。"""
        if isinstance(handler, logging.FileHandler):
            opened.append(handler)
            original(handler, formatter)
        else:
            raise OSError("stderr 配置失败")

    with patch.object(logging.Handler, "setFormatter", fail_stderr), pytest.raises(OSError):
        configure_logging(
            LoggingSettings("worker", tmp_path, stderr=True), time_source=_Clock().source()
        )
    assert logging.getLogger().handlers == old
    assert (tmp_path / "worker.log").read_bytes() == b""
    assert all(isinstance(h, logging.FileHandler) and h.stream is None for h in opened)
    assert (tmp_path / "web.log").exists()


def test_midnight_rollover(tmp_path: Path) -> None:
    """验证契约：验收 5：推进注入时钟跨当地零点，首条新日志前归档旧文件，新记录进入活动文件；不真实等待。"""
    clock = _Clock(datetime(2026, 10, 21, 15, 59, 59, tzinfo=UTC))
    configure_logging(LoggingSettings("web", tmp_path), time_source=clock.source())
    logging.getLogger("rdp.test").info("零点前")
    clock.value += timedelta(seconds=1)
    logging.getLogger("rdp.test").info("零点后")
    assert "零点前" in (tmp_path / "web.log.2026-10-21").read_text(encoding="utf-8")
    current = (tmp_path / "web.log").read_text(encoding="utf-8")
    assert "零点后" in current and "零点前" not in current


def test_retention_calendar_boundary(tmp_path: Path) -> None:
    """验证契约：验收 5：保留期 1/30 天时，早于日历截止日的归档删除，恰在边界日的归档保留。"""
    for days, expired, boundary in (
        (1, "2026-10-20", "2026-10-21"),
        (30, "2026-09-21", "2026-09-22"),
    ):
        directory = tmp_path / str(days)
        directory.mkdir()
        old = directory / f"web.log.{expired}"
        keep = directory / f"web.log.{boundary}"
        old.write_text("过期", encoding="utf-8")
        keep.write_text("保留", encoding="utf-8")
        clock = _Clock(datetime(2026, 10, 21, 15, 59, tzinfo=UTC))
        configure_logging(
            LoggingSettings("web", directory, log=LogConfig(retention_days=days)),
            time_source=clock.source(),
        )
        clock.value += timedelta(minutes=1)
        logging.getLogger("rdp.test").info("触发清理")
        assert not old.exists()
        assert keep.read_text(encoding="utf-8") == "保留"


def test_retention_ignores_foreign_files(tmp_path: Path) -> None:
    """验证契约：切分只删本进程日期归档；保留另一进程、活动文件、非日期文件、目录、软链接及链接目标。"""
    for name in ("worker.log.2020-01-01", "web.log.invalid", "web.log.2020-13-01", "target"):
        (tmp_path / name).write_text("保留", encoding="utf-8")
    (tmp_path / "web.log.2020-01-01").mkdir()
    (tmp_path / "web.log.2020-01-02").symlink_to(tmp_path / "target")
    clock = _Clock(datetime(2026, 10, 21, 15, 59, tzinfo=UTC))
    configure_logging(LoggingSettings("web", tmp_path), time_source=clock.source())
    clock.value += timedelta(minutes=1)
    logging.getLogger("rdp.test").info("清理后仍可写")
    assert (tmp_path / "web.log.2020-01-01").is_dir()
    assert (tmp_path / "web.log.2020-01-02").is_symlink()
    for name in ("worker.log.2020-01-01", "web.log.invalid", "web.log.2020-13-01", "target"):
        assert (tmp_path / name).read_text(encoding="utf-8") == "保留"
    assert "清理后仍可写" in (tmp_path / "web.log").read_text(encoding="utf-8")


def test_idle_days_no_empty_archives(tmp_path: Path) -> None:
    """验证契约：切分时间语义：多日无日志不产生空归档、不清理；下一条到来才切分并按日期删除旧文件。"""
    clock = _Clock()
    configure_logging(
        LoggingSettings("web", tmp_path, log=LogConfig(retention_days=1)),
        time_source=clock.source(),
    )
    logging.getLogger("rdp.test").info("第一日")
    clock.value += timedelta(days=5)
    assert not list(tmp_path.glob("web.log.*"))
    logging.getLogger("rdp.test").info("第六日")
    assert not list(tmp_path.glob("web.log.*"))
    assert "第六日" in (tmp_path / "web.log").read_text(encoding="utf-8")


def test_startup_expiry_cleanup(tmp_path: Path) -> None:
    """验证契约：重启先按mtime补归档，首条日志删除过期归档；活动文件只保存重启后的记录。"""
    old = tmp_path / "web.log.2020-01-01"
    old.write_text("过期", encoding="utf-8")
    current = tmp_path / "web.log"
    current.write_text("旧活动文件\n", encoding="utf-8")
    os.utime(current, (1, 1))
    configure_logging(LoggingSettings("web", tmp_path), time_source=_Clock().source())
    assert old.exists()
    assert (tmp_path / "web.log.1970-01-01").read_text() == "旧活动文件\n"
    logging.getLogger("rdp.test").info("重启首条")
    assert not old.exists()
    assert "旧活动文件" not in current.read_text(encoding="utf-8")
    assert "重启首条" in current.read_text(encoding="utf-8")
    assert not (tmp_path / "web.log.1970-01-01").exists()
    assert not list(tmp_path.glob("web.log.*"))


def test_dst_calendar_midnight(tmp_path: Path) -> None:
    """验证契约：切分时间语义：固定 ZoneInfo 时区跨 23/25 小时自然日均在当地零点分界，不改 TZ 或 tzset。"""
    zone = ZoneInfo("America/New_York")
    for month, day, utc_hour, hours in ((3, 8, 5, 23), (11, 1, 4, 25)):
        folder = tmp_path / str(month)
        folder.mkdir()
        clock = _Clock(datetime(2026, month, day, utc_hour, tzinfo=UTC), zone)
        configure_logging(LoggingSettings("web", folder), time_source=clock.source())
        logging.getLogger("rdp.test").info("日初")
        clock.value += timedelta(hours=hours, seconds=-1)
        logging.getLogger("rdp.test").info("最后一秒")
        assert not list(folder.glob("web.log.*"))
        clock.value += timedelta(seconds=1)
        logging.getLogger("rdp.test").info("新日")
        archive = folder / f"web.log.2026-{month:02d}-{day:02d}"
        assert "最后一秒" in archive.read_text(encoding="utf-8")
        assert "新日" in (folder / "web.log").read_text(encoding="utf-8")


def test_clock_rollback(tmp_path: Path) -> None:
    """验证契约：切分时间语义：墙钟回拨不重复归档；追上原边界后下一条才切分，不覆盖原归档。"""
    clock = _Clock(datetime(2026, 10, 21, 15, 59, tzinfo=UTC))
    configure_logging(LoggingSettings("web", tmp_path), time_source=clock.source())
    logging.getLogger("rdp.test").info("前日")
    clock.value += timedelta(minutes=1)
    logging.getLogger("rdp.test").info("新日")
    archive = tmp_path / "web.log.2026-10-21"
    before = archive.read_bytes()
    clock.value -= timedelta(hours=2)
    logging.getLogger("rdp.test").info("回拨")
    clock.value += timedelta(hours=2)
    logging.getLogger("rdp.test").info("追上")
    assert archive.read_bytes() == before
    assert len(list(tmp_path.glob("web.log.*"))) == 1
    clock.value += timedelta(days=1)
    logging.getLogger("rdp.test").info("下一日")
    assert (tmp_path / "web.log.2026-10-22").exists()


def test_timezone_change(tmp_path: Path) -> None:
    """验证契约：切分时间语义：时区提供器改变后下一条日志偏移更新并重算未来边界；只换时区不触发过去边界。"""
    clock = _Clock(datetime(2026, 10, 21, 15, 30, tzinfo=UTC))
    configure_logging(LoggingSettings("web", tmp_path), time_source=clock.source())
    logging.getLogger("rdp.test").info("原时区")
    clock.zone = timezone(timedelta(hours=-6))
    clock.value += timedelta(hours=1)
    logging.getLogger("rdp.test").info("换时区")
    assert not list(tmp_path.glob("web.log.*"))
    assert "10:30:00.000-06:00" in (tmp_path / "web.log").read_text(encoding="utf-8")
    clock.value = datetime(2026, 10, 22, 6, tzinfo=UTC)
    logging.getLogger("rdp.test").info("新时区零点")
    assert (tmp_path / "web.log.2026-10-21").exists()


def test_archive_collision(tmp_path: Path) -> None:
    """验证契约：切分副作用：重启/回拨遇到同日期归档时追加合并、不覆盖，已有记录完整保留。"""
    clock = _Clock(datetime(2026, 10, 21, 15, 59, tzinfo=UTC))
    archive = tmp_path / "web.log.2026-10-21"
    archive.write_text("之前的归档\n", encoding="utf-8")
    configure_logging(LoggingSettings("web", tmp_path), time_source=clock.source())
    logging.getLogger("rdp.test").info("当前区间")
    clock.value += timedelta(minutes=1)
    logging.getLogger("rdp.test").info("新区间")
    text = archive.read_text(encoding="utf-8")
    assert text.startswith("之前的归档\n") and "当前区间" in text
    assert "新区间" not in text


def test_runtime_write_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """验证契约：运行期失败：切分或写入 OSError 经 handleError 处理，不向业务抛出、不输出 stderr；允许当前记录丢失。"""
    clock = _Clock(datetime(2026, 10, 21, 15, 59, tzinfo=UTC))
    configure_logging(LoggingSettings("web", tmp_path), time_source=clock.source())
    logging.getLogger("rdp.test").info("之前")
    clock.value += timedelta(minutes=1)
    with patch("os.rename", side_effect=OSError("切分失败")):
        logging.getLogger("rdp.test").error("失败记录")
    assert capsys.readouterr().err == ""
    logging.getLogger("rdp.test").info("恢复写入")
    assert "恢复写入" in (tmp_path / "web.log").read_text(encoding="utf-8")


def test_handler_reuses_standard_library(tmp_path: Path) -> None:
    """验证契约：私有 handler 基于 TimedRotatingFileHandler，复用 emit/锁/流管理；初始化只使用注入时钟。"""
    with patch("time.time", side_effect=AssertionError("不得以系统时钟初始化切分")):
        configure_logging(LoggingSettings("web", tmp_path), time_source=_Clock().source())
    file_handlers = [
        h for h in logging.getLogger().handlers if isinstance(h, TimedRotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    assert file_handlers[0].baseFilename == str(tmp_path / "web.log")


def test_handler_rollover_decision(tmp_path: Path) -> None:
    """验证契约：shouldRollover 返回：零点前及回拨 False、跨零点 True，不依赖 LogRecord.created 或系统时钟。"""
    clock = _Clock(datetime(2026, 10, 21, 15, 59, tzinfo=UTC))
    configure_logging(LoggingSettings("web", tmp_path), time_source=clock.source())
    handler = next(
        h for h in logging.getLogger().handlers if isinstance(h, TimedRotatingFileHandler)
    )
    record = _record(created=99999999999.0)
    assert handler.shouldRollover(record) is False
    clock.value -= timedelta(days=1)
    assert handler.shouldRollover(record) is False
    clock.value = datetime(2026, 10, 21, 16, tzinfo=UTC)
    record.created = 0
    assert handler.shouldRollover(record) is True


def test_handler_deletion_candidates(tmp_path: Path) -> None:
    """验证契约：getFilesToDelete 返回：无过期时空列表，有过期时按绝对路径排序，查询本身不删除文件。"""
    configure_logging(LoggingSettings("web", tmp_path), time_source=_Clock().source())
    handler = next(
        h for h in logging.getLogger().handlers if isinstance(h, TimedRotatingFileHandler)
    )
    assert handler.getFilesToDelete() == []
    for name in ("web.log.2020-02-02", "web.log.2020-01-01"):
        (tmp_path / name).write_text("过期", encoding="utf-8")
    assert handler.getFilesToDelete() == [
        str(tmp_path / "web.log.2020-01-01"),
        str(tmp_path / "web.log.2020-02-02"),
    ]
    assert (tmp_path / "web.log.2020-01-01").exists()


def test_bind_job_context(tmp_path: Path) -> None:
    """验证契约：验收 4：with log_context(job_id=123) 内日志带作业编号，正常退出恢复 None，进入返回 None。"""
    clock = _Clock()
    formatter = RuntimeFormatter(clock.source())
    with log_context(job_id=123) as bound:
        assert bound is None
        assert formatter.format(_record()).endswith("job_id=123")
    assert job_id_context.get() is None
    assert "job_id=" not in formatter.format(_record())


def test_bind_request_context(tmp_path: Path) -> None:
    """验证契约：log_context 返回：绑定有效 uuid4.hex 请求编号，日志自动包含该编号，退出恢复旧值。"""
    request_id = "123456789abc4def8123456789abcdef"
    with log_context(request_id=request_id):
        assert (
            RuntimeFormatter(_Clock().source())
            .format(_record())
            .endswith(f"request_id={request_id}")
        )
    assert request_id_context.get() is None


def test_nested_context(tmp_path: Path) -> None:
    """验证契约：log_context：嵌套绑定按 token 恢复外层；None 参数保留现有值，无参数为不改变绑定的作用域。"""
    with log_context(job_id=1, request_id="123456789abc4def8123456789abcdef"):
        with log_context(job_id=2):
            assert job_id_context.get() == 2
            assert request_id_context.get() == "123456789abc4def8123456789abcdef"
            with log_context():
                assert job_id_context.get() == 2
        assert job_id_context.get() == 1
    assert job_id_context.get() is None and request_id_context.get() is None


def test_invalid_context_identifiers(tmp_path: Path) -> None:
    """验证契约：log_context Raises：0、负数、bool 作业号及长度/大小写/version/variant 错的请求号报 ValueError。"""
    for value in (0, -1, True):
        manager = log_context(job_id=value)
        with pytest.raises(ValueError), manager:
            pytest.fail("非法作业编号不得进入主体")
    for value in (
        "short",
        "123456789ABC4DEF8123456789ABCDEF",
        "123456789abc1def8123456789abcdef",
        "123456789abc4def0123456789abcdef",
    ):
        with pytest.raises(ValueError), log_context(request_id=value):
            pytest.fail("非法请求编号不得进入主体")


def test_context_validation_atomic(tmp_path: Path) -> None:
    """验证契约：log_context 失败副作用：同时传合法作业号与非法请求号，进入失败不留下部分绑定。"""
    with log_context(job_id=9):
        with pytest.raises(ValueError), log_context(job_id=10, request_id="bad"):
            pytest.fail("不得进入")
        assert job_id_context.get() == 9 and request_id_context.get() is None


def test_context_exception_restore(tmp_path: Path) -> None:
    """验证契约：log_context Raises：体内业务异常原样传播并恢复旧值，不吞异常、不打日志。"""
    error = RuntimeError("主体失败")
    with log_context(job_id=5):
        with pytest.raises(RuntimeError) as caught, log_context(job_id=6):
            raise error
        assert caught.value is error and job_id_context.get() == 5
    assert job_id_context.get() is None


def test_context_cancel_restore(tmp_path: Path) -> None:
    """验证契约：log_context Raises：asyncio 任务取消原样传播 CancelledError，并恢复上下文。"""

    async def scenario() -> None:
        """在绑定内注入取消，观察同一任务的恢复。"""
        with log_context(job_id=5):
            with pytest.raises(asyncio.CancelledError), log_context(job_id=6):
                raise asyncio.CancelledError
            assert job_id_context.get() == 5

    asyncio.run(scenario())
    assert job_id_context.get() is None


def test_concurrent_context_isolation(tmp_path: Path) -> None:
    """验证契约：验收 4：用异步同步点交错两个任务，日志各带自己的编号，不依赖执行顺序或 sleep。"""

    async def scenario() -> list[str]:
        """使用事件交错，避免 sleep 或调度顺序假设。"""
        entered = [asyncio.Event(), asyncio.Event()]
        formatter = RuntimeFormatter(_Clock().source())

        async def task(index: int) -> str:
            with log_context(job_id=index + 1):
                entered[index].set()
                await entered[1 - index].wait()
                return formatter.format(_record())

        return list(await asyncio.gather(task(0), task(1)))

    texts = asyncio.run(scenario())
    assert texts[0].endswith("job_id=1") and texts[1].endswith("job_id=2")
    assert job_id_context.get() is None


def test_child_context_inheritance(tmp_path: Path) -> None:
    """验证契约：log_context：新 asyncio 任务继承创建时快照，父子后续改动隔离；手工线程不自动继承。"""

    async def scenario() -> None:
        """子任务在父绑定变化后仍看到创建时快照。"""
        ready = asyncio.Event()

        async def child() -> int | None:
            await ready.wait()
            return job_id_context.get()

        with log_context(job_id=11):
            task = asyncio.create_task(child())
            with log_context(job_id=22):
                ready.set()
                assert await task == 11
                assert job_id_context.get() == 22

    asyncio.run(scenario())
    with log_context(job_id=33), ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(job_id_context.get).result(timeout=5) is None


def test_default_configuration_notice(tmp_path: Path) -> None:
    """验证契约：C1/log_config_source：日志初始化后 used_defaults=True 在 INFO 阈值下恰写一行使用默认配置及 config_file。"""
    configure_logging(LoggingSettings("web", tmp_path), time_source=_Clock().source())
    loaded = LoadedConfig(PlatformConfig(state_dir=tmp_path), tmp_path / "config.toml", True)
    log_config_source(loaded)
    text = (tmp_path / "web.log").read_text(encoding="utf-8")
    assert text.count("使用默认配置") == 1
    assert f"config_file={tmp_path}/config.toml" in text
    assert "INFO rdp.infra.logging" in text


def test_explicit_configuration_no_notice(tmp_path: Path) -> None:
    """验证契约：log_config_source 返回：used_defaults=False 不写默认提示，即使文件中值恰等于默认值。"""
    configure_logging(LoggingSettings("web", tmp_path), time_source=_Clock().source())
    log_config_source(
        LoadedConfig(PlatformConfig(state_dir=tmp_path), tmp_path / "config.toml", False)
    )
    assert (tmp_path / "web.log").read_text(encoding="utf-8") == ""


def test_default_notice_threshold(tmp_path: Path) -> None:
    """验证契约：log_config_source：WARNING/ERROR 阈值不输出 INFO；函数不越过统一日志阈值。"""
    for level in ("WARNING", "ERROR"):
        folder = tmp_path / level
        folder.mkdir()
        configure_logging(
            LoggingSettings("web", folder, log=LogConfig.model_validate({"level": level})),
            time_source=_Clock().source(),
        )
        log_config_source(
            LoadedConfig(PlatformConfig(state_dir=folder), folder / "config.toml", True)
        )
        assert (folder / "web.log").read_text(encoding="utf-8") == ""


def test_default_notice_no_global_deduplication(tmp_path: Path) -> None:
    """验证契约：log_config_source 副作用：每次调用独立，入口每次启动调用一次；不改配置、不重读文件。"""
    configure_logging(LoggingSettings("web", tmp_path), time_source=_Clock().source())
    loaded = LoadedConfig(PlatformConfig(state_dir=tmp_path), tmp_path / "config.toml", True)
    with patch.object(Path, "open", side_effect=AssertionError("不重读配置")):
        log_config_source(loaded)
        log_config_source(loaded)
    assert (tmp_path / "web.log").read_text(encoding="utf-8").count("使用默认配置") == 2
    assert loaded.used_defaults


def test_default_timezone_read_failure(tmp_path: Path) -> None:
    """验证契约：本地时区规则读取失败时 formatter/configure_logging 保留 OSError；用替身，不读真实规则文件。"""
    clock = _Clock()
    source = LogTime(now=clock.now)
    error = OSError(5, "时区规则不可读", "/etc/localtime")
    with patch.object(Path, "open", side_effect=error):
        with pytest.raises(OSError) as caught:
            RuntimeFormatter(source).format(_record())
        assert caught.value is error
        with pytest.raises(OSError):
            configure_logging(LoggingSettings("web", tmp_path), time_source=source)
    assert not (tmp_path / "web.log").exists()


def test_configure_time_overflow(tmp_path: Path) -> None:
    """验证契约：初始化时换算或计算下一次零点溢出抛 OverflowError，关闭新 handler 并保留旧配置。"""
    configure_logging(LoggingSettings("web", tmp_path), time_source=_Clock().source())
    old = logging.getLogger().handlers[:]
    for clock in (
        _Clock(datetime.max.replace(tzinfo=UTC)),
        _Clock(datetime.max.replace(tzinfo=UTC), UTC),
    ):
        with pytest.raises(OverflowError):
            configure_logging(LoggingSettings("worker", tmp_path), time_source=clock.source())
        assert logging.getLogger().handlers == old
    assert not (tmp_path / "worker.log").exists()


def test_default_clock_is_utc(tmp_path: Path) -> None:
    """验证默认时钟适配器返回 UTC aware 时刻；不依赖本机时区或实际日期。"""
    moment = LogTime().now()
    assert moment.tzinfo is UTC and moment.utcoffset() == timedelta(0)


def test_state_permission_warning_after_logging(tmp_path: Path) -> None:
    """验证 P4：先收集、后配置日志，WARNING 确实落进本进程文件，含路径、权限和后果。"""
    for process in ("web", "worker"):
        root = tmp_path / process
        root.mkdir(mode=0o755)
        root.chmod(0o755)
        paths = state_paths(PlatformConfig(state_dir=root), [])
        warnings = initialize_state(paths)
        configure_logging(
            LoggingSettings(cast(Any, process), paths.logs, log=LogConfig(level="ERROR")),
            time_source=_Clock().source(),
        )
        log_state_warnings(warnings)
        text = (paths.logs / f"{process}.log").read_text(encoding="utf-8")
        assert text.startswith("2026-10-21 16:15:02.123+08:00 WARNING rdp.infra.logging ")
        assert "mode=0755" in text and f"path={root}" in text
        assert "口令哈希" in text and "其他用户可能读到" in text
        assert root.stat().st_mode & 0o777 == 0o755


def test_private_state_directories_have_no_warning(tmp_path: Path) -> None:
    """验证 P4：0700 目录和本次新建目录不报警；报告函数不重新读写目录。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ["下载"])
    assert initialize_state(paths) == ()
    warnings = initialize_state(paths)
    assert warnings == ()
    configure_logging(LoggingSettings("web", paths.logs), time_source=_Clock().source())
    with (
        patch.object(Path, "stat", side_effect=AssertionError("不重读权限")),
        patch.object(Path, "chmod", side_effect=AssertionError("不改权限")),
    ):
        log_state_warnings(warnings)
    assert (paths.logs / "web.log").read_bytes() == b""


def test_rollover_cleanup_failure_recovers(tmp_path: Path) -> None:
    """验证评审 1：归档后的清理失败不丢当条或后续记录，留下的归档下次切分再试。"""
    clock = _Clock(datetime(2026, 10, 21, 15, 59, tzinfo=UTC))
    configure_logging(LoggingSettings("web", tmp_path), time_source=clock.source())
    logging.getLogger("rdp.test").info("之前")
    expired = tmp_path / "web.log.2020-01-01"
    expired.write_text("过期", encoding="utf-8")
    clock.value += timedelta(minutes=1)
    with patch.object(Path, "unlink", side_effect=OSError("清理暂时失败")):
        logging.getLogger("rdp.test").error("失败当条")
    logging.getLogger("rdp.test").info("故障后继续")
    text = (tmp_path / "web.log").read_text(encoding="utf-8")
    assert "失败当条" in text and "故障后继续" in text
    assert expired.exists()
    clock.value += timedelta(days=1)
    logging.getLogger("rdp.test").info("下次切分重试清理")
    assert not expired.exists()


def test_old_handler_close_failure_keeps_new_output(tmp_path: Path) -> None:
    """验证重配资源清理：旧日志关闭失败按运行期日志故障处理，不破坏已准备好的新输出。"""
    configure_logging(LoggingSettings("web", tmp_path), time_source=_Clock().source())
    old = next(h for h in logging.getLogger().handlers if isinstance(h, logging.FileHandler))
    with patch.object(old, "close", side_effect=OSError("旧文件关闭失败")):
        configure_logging(LoggingSettings("worker", tmp_path), time_source=_Clock().source())
    old.close()
    logging.getLogger("rdp.test").info("新输出正常")
    assert "新输出正常" in (tmp_path / "worker.log").read_text(encoding="utf-8")


@pytest.mark.parametrize("cleanup_stage", ["startup", "rollover"])
@pytest.mark.parametrize("delete_error", ["denied", "missing"])
def test_expired_archive_delete_errors_preserve_records(
    tmp_path: Path, cleanup_stage: str, delete_error: str
) -> None:
    """验证评审 1：启动或切分时单个归档持续删不掉或已被删除，跨零点六条日志都不丢。"""
    clock = _Clock(datetime(2026, 10, 21, 15, 59, tzinfo=UTC))
    configure_logging(LoggingSettings("web", tmp_path), time_source=clock.source())
    if cleanup_stage == "rollover":
        logging.getLogger("rdp.test").info("预热，完成首次清理")
    expired = tmp_path / "web.log.2020-01-01"
    other = tmp_path / "web.log.2020-01-02"
    expired.write_text("待删除", encoding="utf-8")
    other.write_text("可删除", encoding="utf-8")
    attempts: list[datetime] = []
    original_unlink = Path.unlink

    def fail_one_archive(path: Path, missing_ok: bool = False) -> None:
        """只在文件系统边界模拟单文件故障，其他文件仍可正常清理。"""
        if path == expired:
            attempts.append(clock.value)
            if delete_error == "missing":
                original_unlink(path, missing_ok=missing_ok)
                raise FileNotFoundError(2, "归档已被其他清理者删除", str(path))
            raise PermissionError(13, "归档持续不可删除", str(path))
        original_unlink(path, missing_ok=missing_ok)

    with patch.object(Path, "unlink", fail_one_archive):
        for index in range(3):
            logging.getLogger("rdp.test").info("记录 %d", index)
        clock.value += timedelta(minutes=1)
        for index in range(3, 6):
            logging.getLogger("rdp.test").info("记录 %d", index)
        current = (tmp_path / "web.log").read_text(encoding="utf-8")
        assert all(f"记录 {index}\n" in current for index in range(3, 6)), current
        archived = (tmp_path / "web.log.2026-10-21").read_text(encoding="utf-8")
        assert all(f"记录 {index}\n" in archived for index in range(3)), archived
        expected_attempts = 2 if cleanup_stage == "startup" and delete_error == "denied" else 1
        assert len(attempts) == expected_attempts
        assert not other.exists()
        assert expired.exists() is (delete_error == "denied")
    # 不在每条记录重试；下一次切分时，权限已恢复的归档应被清掉。
    clock.value += timedelta(days=1)
    logging.getLogger("rdp.test").info("下一次切分")
    assert not expired.exists()
    assert "下一次切分" in (tmp_path / "web.log").read_text(encoding="utf-8")


@pytest.mark.parametrize("cleanup_stage", ["startup", "rollover"])
@pytest.mark.parametrize("operation", ["iterdir", "is_file", "is_symlink"])
def test_expired_archive_query_errors_preserve_records(
    tmp_path: Path, cleanup_stage: str, operation: str
) -> None:
    """验证 r2：启动或切分清理的枚举、属性查询持续失败时，跨零点六条记录仍完整写入。"""
    clock = _Clock(datetime(2026, 10, 21, 15, 59, tzinfo=UTC))
    configure_logging(LoggingSettings("web", tmp_path), time_source=clock.source())
    if cleanup_stage == "rollover":
        logging.getLogger("rdp.test").info("预热，完成首次清理")
    expired = tmp_path / "web.log.2020-01-01"
    expired.write_text("待下次清理", encoding="utf-8")
    with patch.object(
        Path, operation, side_effect=PermissionError(13, "清理查询持续失败", str(tmp_path))
    ) as query:
        for index in range(3):
            logging.getLogger("rdp.test").info("查询故障记录 %d", index)
        clock.value += timedelta(minutes=1)
        for index in range(3, 6):
            logging.getLogger("rdp.test").info("查询故障记录 %d", index)
        current = (tmp_path / "web.log").read_text(encoding="utf-8")
        assert all(f"查询故障记录 {index}\n" in current for index in range(3, 6)), current
        archived = (tmp_path / "web.log.2026-10-21").read_text(encoding="utf-8")
        assert all(f"查询故障记录 {index}\n" in archived for index in range(3)), archived
        # 启动清理失败也只能试一次；之后到零点才再试，不在每条记录上重试。
        assert query.call_count == (2 if cleanup_stage == "startup" else 1)
        assert expired.exists()
    clock.value += timedelta(days=1)
    logging.getLogger("rdp.test").info("查询恢复，下一次切分")
    assert not expired.exists()
    assert "查询恢复，下一次切分" in (tmp_path / "web.log").read_text(encoding="utf-8")
