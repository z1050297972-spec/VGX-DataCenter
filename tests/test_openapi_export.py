"""工单 02 的公开边界回归测试，只使用临时目录与受控的外部依赖替身。"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from rdp.api import create_app
from rdp.api.openapi_export import export_openapi, main


def _run_cli(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """通过实际模块入口验证退出码和输出，限制运行时间且不建立网络服务。"""
    return subprocess.run(  # noqa: S603  # 理由：固定解释器与模块，参数仅为测试构造的临时路径。
        [sys.executable, "-B", "-m", "rdp.api.openapi_export", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_deterministic_export(tmp_path: Path) -> None:
    """验证同一应用导出两次逐字节相同，UTF-8、键排序、两空格缩进及末尾换行。"""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    export_openapi(first)
    export_openapi(second)
    content = first.read_bytes()
    assert content == second.read_bytes()
    assert content.endswith(b"\n") and not content.endswith(b"\n\n")
    text = content.decode("utf-8")
    assert "机器人数据管理平台" in text
    assert text.startswith('{\n  "components": {\n')
    assert text.index('  "components":') < text.index('  "info":') < text.index('  "paths":')
    assert '    "schemas": {' in text


def test_export_matches_app(tmp_path: Path) -> None:
    """验证导出 JSON 与 create_app(None).openapi() 一致，包含健康响应模型。"""
    target = tmp_path / "schema.json"
    export_openapi(target)
    exported = json.loads(target.read_text(encoding="utf-8"))
    assert exported == create_app(None).openapi()
    assert "/api/health" in exported["paths"]
    assert "HealthResponse" in exported["components"]["schemas"]


def test_overwrite_export(tmp_path: Path) -> None:
    """验证只覆盖指定输出文件，不创建额外文件或启动服务。"""
    target = tmp_path / "schema.json"
    target.write_text("旧内容", encoding="utf-8")
    unrelated = tmp_path / "keep.txt"
    unrelated.write_bytes(b"unchanged")
    with patch("socket.socket", side_effect=AssertionError("导出不得建立 socket")):
        export_openapi(target)
    assert "/api/health" in json.loads(target.read_text(encoding="utf-8"))["paths"]
    assert unrelated.read_bytes() == b"unchanged"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["keep.txt", "schema.json"]


def test_invalid_output(tmp_path: Path) -> None:
    """验证父目录缺失、目标是目录或写入失败时抛 OSError，不自动建父目录。"""
    for target in (tmp_path / "missing" / "schema.json", tmp_path):
        with pytest.raises(OSError):
            export_openapi(target)
    assert not (tmp_path / "missing").exists()
    assert list(tmp_path.iterdir()) == []


def test_serialization_error(tmp_path: Path) -> None:
    """验证不可序列化值抛 TypeError、非有限数抛 ValueError，原文件不变。"""
    target = tmp_path / "schema.json"
    target.write_bytes(b"original")
    for value, error_type in ((object(), TypeError), (float("nan"), ValueError)):
        # 在第三方 OpenAPI 边界注入不能序列化的值，不替换导出函数内部逻辑。
        with (
            patch("fastapi.FastAPI.openapi", return_value={"invalid": value}),
            pytest.raises(error_type),
        ):
            export_openapi(target)
        assert target.read_bytes() == b"original"


@pytest.mark.parametrize("stage", ["write", "replace"])
def test_atomic_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
    """验证 G3：临时文件写入或替换失败时保留原文件，清除临时文件。"""
    target = tmp_path / "schema.json"
    target.write_bytes(b"original")
    original_temporary_file = tempfile.NamedTemporaryFile

    def failing_file(*, mode: str, encoding: str, dir: Path, delete: bool):
        """在标准库文件边界模拟写满，不依赖磁盘剩余空间。"""
        handle = original_temporary_file(mode=mode, encoding=encoding, dir=dir, delete=delete)
        monkeypatch.setattr(handle, "write", Mock(side_effect=OSError("写入失败")))
        return handle

    if stage == "write":
        monkeypatch.setattr(tempfile, "NamedTemporaryFile", failing_file)
    else:
        monkeypatch.setattr("os.replace", Mock(side_effect=OSError("替换失败")))
    with pytest.raises(OSError, match="失败"):
        export_openapi(target)
    assert target.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [target]


def test_cli_success(tmp_path: Path) -> None:
    """验证 python -m rdp.api.openapi_export 写入指定相对路径并以 0 退出。"""
    result = _run_cli(tmp_path, "schema.json")
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""
    assert "/api/health" in json.loads((tmp_path / "schema.json").read_text())["paths"]


def test_cli_help(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """验证 -h 和 --help 输出帮助且不导出文件，退出 0。"""
    for option in ("-h", "--help"):
        result = _run_cli(tmp_path, option)
        assert result.returncode == 0
        assert "output_path" in result.stdout
        assert result.stderr == ""
        assert main([option]) == 0
        captured = capsys.readouterr()
        assert "output_path" in captured.out
        assert captured.err == ""
    assert list(tmp_path.iterdir()) == []


def test_cli_arguments(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """验证缺失、多余或未知参数写 stderr 且退出 2，不写文件。"""
    for arguments in ([], ["one.json", "two.json"], ["--unknown"]):
        result = _run_cli(tmp_path, *arguments)
        assert result.returncode == 2
        assert result.stdout == ""
        assert "error:" in result.stderr
        assert main(arguments) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "error:" in captured.err
    assert list(tmp_path.iterdir()) == []


def test_cli_export_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """验证导出失败写 stderr 并包含输出路径和原因，退出 1。"""
    target = tmp_path / "missing" / "schema.json"
    result = _run_cli(tmp_path, str(target))
    assert result.returncode == 1
    assert str(target) in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""
    assert main([str(target)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert str(target) in captured.err
    assert not target.exists()


def test_cli_stream_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 stdout 或 stderr 写失败时保留 OSError。"""
    for stream, arguments in (
        ("stdout", ["--help"]),
        ("stderr", []),
        ("stderr", [str(tmp_path / "missing" / "schema.json")]),
    ):
        with monkeypatch.context() as patcher:
            patcher.setattr(sys, stream, Mock(write=Mock(side_effect=OSError("输出流断开"))))
            with pytest.raises(OSError, match="输出流断开"):
                main(arguments)


def test_cli_argv_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证显式 argv 不读取进程参数，None 读取 sys.argv[1:]。"""
    explicit = tmp_path / "explicit.json"
    implicit = tmp_path / "implicit.json"
    monkeypatch.setattr(sys, "argv", ["openapi_export", str(implicit)])
    assert main([str(explicit)]) == 0
    assert explicit.is_file()
    assert not implicit.exists()
    assert main(None) == 0
    assert implicit.read_bytes() == explicit.read_bytes()


def test_cli_help_does_not_hide_unknown_arguments(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """验证未知参数契约：即使同时请求帮助，也返回参数错误且不写文件。"""
    assert main(["--help", "--unknown"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--unknown" in captured.err
    assert list(tmp_path.iterdir()) == []
