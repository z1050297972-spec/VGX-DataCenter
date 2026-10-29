"""第 11 张 logging_startup 契约清单；只用临时目录和可注入依赖，不触碰真实部署或服务。"""

import builtins
import logging
import os
import shutil
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO, Literal
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from rdp.infra.logging import LoggingSettings, LogTime, configure_logging

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)


def _active(root: Path, process: str, moment: datetime, content: str = "旧内容\n") -> Path:
    """只在临时目录写活动文件并固定mtime，不改全局时区。"""
    path = root / f"{process}.log"
    path.write_text(content)
    os.utime(path, (moment.timestamp(), moment.timestamp()))
    return path


def _start(
    root: Path, process: Literal["web", "worker"] = "web", *, moment: datetime = NOW
) -> None:
    """通过公开配置入口写新记录；公共fixture在finally恢复所有logging状态。"""
    configure_logging(
        LoggingSettings(process, root), time_source=LogTime(lambda: moment, lambda: UTC)
    )
    logging.getLogger("rdp.test").info("新内容")


def test_old_mtime(tmp_path: Path) -> None:
    """验证契约：验收2b：web/worker活动文件mtime为三天前时归档为那天日期，新内容进入新活动文件。"""
    for process in ("web", "worker"):
        active = _active(tmp_path, process, NOW - timedelta(days=3))
        _start(tmp_path, process)
        assert (tmp_path / f"{process}.log.2026-10-25").read_text() == "旧内容\n"
        assert "新内容" in active.read_text() and "旧内容" not in active.read_text()


def test_today_mtime(tmp_path: Path) -> None:
    """验证契约：验收2b：mtime为今天时不补归档，原文件继续追加；不sleep或修改全局TZ。"""
    active = _active(tmp_path, "web", NOW)
    _start(tmp_path)
    assert active.read_text().startswith("旧内容\n")
    assert "新内容" in active.read_text()
    assert list(tmp_path.glob("web.log.*")) == []


def test_future_mtime(tmp_path: Path) -> None:
    """验证契约：mtime日期在未来时不提前归档，时钟回拨不重复切分。"""
    active = _active(tmp_path, "web", NOW + timedelta(days=3))
    _start(tmp_path)
    _start(tmp_path, moment=NOW - timedelta(days=1))
    assert active.read_text().startswith("旧内容\n")
    assert active.read_text().count("新内容") == 2
    assert list(tmp_path.glob("web.log.*")) == []


def test_missing_and_empty(tmp_path: Path) -> None:
    """验证契约：缺失文件正常新建；旧日期空文件也归档，不额外生成停机期间逐日空文件。"""
    _start(tmp_path)
    assert "新内容" in (tmp_path / "web.log").read_text()
    _active(tmp_path, "worker", NOW - timedelta(days=3), "")
    _start(tmp_path, "worker")
    assert (tmp_path / "worker.log.2026-10-25").read_bytes() == b""
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "web.log",
        "worker.log",
        "worker.log.2026-10-25",
    ]


def test_timezone_boundary(tmp_path: Path) -> None:
    """验证契约：用固定偏移/ZoneInfo区分UTC日期和当地日期；mtime转换与启动今天使用同一规则，覆盖夏令时边界。"""
    cases = (
        (
            timezone(timedelta(hours=8)),
            datetime(2026, 10, 28, 16, 1, tzinfo=UTC),
            datetime(2026, 10, 28, 15, 59, tzinfo=UTC),
            "2026-10-28",
        ),
        (
            ZoneInfo("America/New_York"),
            datetime(2026, 11, 1, 6, 30, tzinfo=UTC),
            datetime(2026, 11, 1, 3, 59, tzinfo=UTC),
            "2026-10-31",
        ),
    )
    for index, (zone, now, modified, suffix) in enumerate(cases):
        root = tmp_path / str(index)
        root.mkdir()
        _active(root, "web", modified)
        configure_logging(
            LoggingSettings("web", root),
            time_source=LogTime(lambda value=now: value, lambda value=zone: value),
        )
        assert (root / f"web.log.{suffix}").read_text() == "旧内容\n"
        assert (root / "web.log").read_text() == ""


def test_existing_archive(tmp_path: Path) -> None:
    """验证契约：同名日期归档已存在时追加而不覆盖，其他进程文件不变。"""
    archive = tmp_path / "web.log.2026-10-25"
    archive.write_text("更早证据\n")
    other = _active(tmp_path, "worker", NOW - timedelta(days=3), "worker不变")
    _active(tmp_path, "web", NOW - timedelta(days=3))
    _start(tmp_path)
    assert archive.read_text() == "更早证据\n旧内容\n"
    assert other.read_text() == "worker不变"


def test_archive_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：stat/rename/合并/重开失败抛OSError，原logging配置不变；部分合并失败保留活动文件和已追加归档证据。"""
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    _start(baseline)
    previous = tuple(logging.getLogger().handlers)
    for stage in ("stat", "rename", "copy", "open"):
        root = tmp_path / stage
        root.mkdir()
        active = _active(root, "web", NOW - timedelta(days=3))
        archive = root / "web.log.2026-10-25"
        if stage == "copy":
            archive.write_bytes(b"earlier\n")

        def partial(_source: BinaryIO, target: BinaryIO) -> None:
            target.write(b"partial\n")
            raise OSError("磁盘故障")

        with monkeypatch.context() as patch:
            if stage in ("stat", "rename"):
                patch.setattr(Path, stage, Mock(side_effect=OSError("文件故障")))
            elif stage == "copy":
                patch.setattr(shutil, "copyfileobj", partial)
            else:
                patch.setattr(builtins, "open", Mock(side_effect=OSError("重开失败")))
            with pytest.raises(OSError):
                _start(root)
            assert tuple(logging.getLogger().handlers) == previous
        if stage in ("stat", "rename", "copy"):
            assert active.read_text() == "旧内容\n"
        if stage == "copy":
            assert archive.read_bytes() == b"earlier\npartial\n"
        if stage == "open":
            assert archive.read_text() == "旧内容\n"
    logging.getLogger("rdp.test").info("原配置仍有效")
    assert "原配置仍有效" in (baseline / "web.log").read_text()


def test_retention_after_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：补归档之后仍按当地日期保留期清理，边界日保留；清理失败不阻断写日志。"""
    _active(tmp_path, "web", NOW - timedelta(days=31))
    boundary = tmp_path / "web.log.2026-09-28"
    boundary.write_text("边界保留")
    _start(tmp_path)
    assert not (tmp_path / "web.log.2026-09-27").exists()
    assert boundary.read_text() == "边界保留"
    expired = tmp_path / "web.log.2026-09-26"
    expired.write_text("删不掉")
    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", Mock(side_effect=PermissionError("拒绝清理")))
        _start(tmp_path)
    assert expired.read_text() == "删不掉"
    assert (tmp_path / "web.log").read_text().count("新内容") == 2


def test_reconfigure_same_day(tmp_path: Path) -> None:
    """验证契约：同日重复配置不重复归档/写行、不丢旧文件，测试finally恢复全局logging与handler。"""
    _active(tmp_path, "web", NOW - timedelta(days=3))
    _start(tmp_path)
    # 实际写入使用文件系统时钟；显式把mtime固定到注入的当天，避免依赖机器日期。
    active = tmp_path / "web.log"
    os.utime(active, (NOW.timestamp(), NOW.timestamp()))
    _start(tmp_path)
    assert (tmp_path / "web.log.2026-10-25").read_text() == "旧内容\n"
    assert active.read_text().count("新内容") == 2
    assert len(list(tmp_path.glob("web.log.*"))) == 1
