"""工单 02 的公开边界回归测试，只使用临时目录与受控的外部依赖替身。"""

import runpy
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest


def _checker(root: Path) -> Callable[[Path], list[str]]:
    """把真实检查器放进临时仓库，在公开 check_file 边界验证仓库归属。"""
    script = root / "scripts" / "check_contracts.py"
    script.parent.mkdir(parents=True)
    source = Path(__file__).resolve().parents[1] / "scripts" / "check_contracts.py"
    script.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    namespace = runpy.run_path(str(script))
    return cast(Callable[[Path], list[str]], namespace["check_file"])


def _sample(root: Path, relative: str) -> Path:
    """生成缺少六项的公开 test_ 函数，以判定豁免是否真正生效。"""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def test_probe():\n    pass\n", encoding="utf-8")
    return path


def test_source_test_prefix(tmp_path: Path) -> None:
    """验证 W3：仓库 src/ 下公开 test_ 函数仍检查六项。"""
    check = _checker(tmp_path)
    problems = check(_sample(tmp_path, "src/rdp/sample.py"))
    assert len(problems) == 1
    assert "test_probe" in problems[0]
    assert "缺少 Args:" in problems[0]


def test_script_test_prefix(tmp_path: Path) -> None:
    """验证 W3：仓库 scripts/ 下公开 test_ 函数仍检查六项。"""
    check = _checker(tmp_path)
    problems = check(_sample(tmp_path, "scripts/sample.py"))
    assert len(problems) == 1
    assert "缺少 Time Semantics:" in problems[0]


def test_repository_tests_prefix(tmp_path: Path) -> None:
    """验证 W3：仅仓库根 tests/ 及其子目录的 test_ 函数跳过六项。"""
    check = _checker(tmp_path)
    for relative in ("tests/sample.py", "tests/nested/sample.py"):
        sample = _sample(tmp_path, relative)
        assert check(sample) == []
        sample.write_text("def ordinary():\n    pass\n", encoding="utf-8")
        assert len(check(sample)) == 1


def test_unrelated_tests_directory(tmp_path: Path) -> None:
    """验证 W3：临时目录或 src/ 下名为 tests 的目录不获得豁免。"""
    root = tmp_path / "repository"
    check = _checker(root)
    for base, relative in (
        (root, "src/tests/sample.py"),
        (tmp_path, "tests/sample.py"),
        (root, "tests_extra/sample.py"),
    ):
        assert len(check(_sample(base, relative))) == 1


def test_scope_independent_of_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 W3：绝对路径、相对路径及切换工作目录不改变判定。"""
    root = tmp_path / "repository"
    check = _checker(root)
    test = _sample(root, "tests/sample.py")
    source = _sample(root, "src/sample.py")
    for cwd in (root, tmp_path):
        monkeypatch.chdir(cwd)
        assert check(test) == check(test.relative_to(cwd)) == []
        assert len(check(source)) == len(check(source.relative_to(cwd))) == 1


def test_resolved_symlink_scope(tmp_path: Path) -> None:
    """验证 W3：check_file 按解析后的文件位置判断，不用 tests/ 内软链接扩大豁免。"""
    check = _checker(tmp_path)
    source = _sample(tmp_path, "src/sample.py")
    test = _sample(tmp_path, "tests/sample.py")
    outward = test.parent / "outward.py"
    outward.symlink_to(source)
    inward = source.parent / "inward.py"
    inward.symlink_to(test)
    assert len(check(outward)) == 1
    assert check(inward) == []
