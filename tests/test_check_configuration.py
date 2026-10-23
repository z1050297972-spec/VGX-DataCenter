"""检查链配置的行为回归测试，只在临时目录验证失败证据的保留策略。"""

import os
import subprocess
import sys
from pathlib import Path


def test_failed_tmp_path_is_retained(tmp_path: Path) -> None:
    """验证评审修复：失败测试的样例保留，成功测试的样例清理，符合规范 7.8。"""
    config = Path(__file__).resolve().parents[1] / "pyproject.toml"
    sample = tmp_path / "test_retention_sample.py"
    sample.write_text(
        "def test_pass(tmp_path):\n"
        "    (tmp_path / 'passed.txt').write_text('成功现场', encoding='utf-8')\n"
        "def test_fail(tmp_path):\n"
        "    (tmp_path / 'failed.txt').write_text('失败现场', encoding='utf-8')\n"
        "    assert False, '故意失败，以验证现场保留'\n",
        encoding="utf-8",
    )
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    # 子 pytest 的失败现场也限制在本测试的 tmp_path 内；父测试完成后即可统一清理。
    environment = os.environ | {
        "PYTEST_DEBUG_TEMPROOT": str(sessions),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    # 30 秒用于发现子 pytest 意外阻塞；参数均为固定解释器和临时测试文件，不经过 shell。
    result = subprocess.run(  # noqa: S603  # 理由：只运行固定解释器及受控的回归样例。
        [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-c",
            str(config),
            str(sample),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "1 failed, 1 passed" in result.stdout
    retained = list(sessions.rglob("failed.txt"))
    assert len(retained) == 1, "失败测试的现场被清理了"
    assert retained[0].read_text(encoding="utf-8") == "失败现场"
    assert not list(sessions.rglob("passed.txt")), "成功测试的临时样例不应保留"
