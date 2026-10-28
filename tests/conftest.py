"""测试公共边界的清理，保证日志配置不会污染后续测试或遗留打开的文件。"""

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from nav_manifest import FakeNavigation, expand_fake_nav

from rdp.infra import logging as runtime_logging


@pytest.fixture
def fake_nav(tmp_path: Path) -> FakeNavigation:
    """给单个测试提供仅在临时目录内可变的导航层。

    Args:
        tmp_path: pytest 创建的私有绝对路径，不传真实存储根或真实 home。

    Returns:
        expand_fake_nav 的结果，样本位置固定为本仓库 tests/fixtures/nav；每次独立展开。

    Raises:
        ValueError: 清单或样本不满足 expand_fake_nav 的安全、引用和形态契约。
        OSError: 仓库夹具读取或临时文件创建失败。

    Side Effects:
        只读仓库夹具并写 tmp_path；不读 .scratch，测试结束由 pytest 清理成功现场。

    Time Semantics:
        function scope，不缓存跨测试状态，不读取真实挂载表。
    """
    return expand_fake_nav(tmp_path, fixture_dir=Path(__file__).parent / "fixtures" / "nav")


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    """保存并恢复 root/uvicorn 日志状态，关闭测试中新安装的 handler。"""
    loggers = [
        logging.getLogger(name) for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access")
    ]
    saved = [
        (item, list(item.handlers), item.level, item.propagate, item.disabled) for item in loggers
    ]
    # 测试同时回滚模块的资源登记，不能让下一项测试继承已关闭的 handler 引用。
    module_state = cast(dict[str, object], vars(runtime_logging))
    installed_handlers = cast(tuple[logging.Handler, ...], module_state["_installed_handlers"])
    original_handlers = {handler for _, handlers, _, _, _ in saved for handler in handlers}
    original_handlers.update(installed_handlers)
    exceptions = logging.raiseExceptions
    disabled = logging.root.manager.disable
    try:
        yield
    finally:
        current_handlers = {handler for item in loggers for handler in item.handlers}
        current_handlers.update(
            cast(tuple[logging.Handler, ...], module_state["_installed_handlers"])
        )
        for handler in current_handlers - original_handlers:
            handler.close()
        for item, handlers, level, propagate, is_disabled in saved:
            item.handlers = handlers
            item.setLevel(level)
            item.propagate = propagate
            item.disabled = is_disabled
        module_state["_installed_handlers"] = installed_handlers
        logging.raiseExceptions = exceptions
        logging.disable(disabled)
