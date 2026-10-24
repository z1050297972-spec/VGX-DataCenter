"""测试公共边界的清理，保证日志配置不会污染后续测试或遗留打开的文件。"""

import logging
from collections.abc import Iterator
from typing import cast

import pytest

from rdp.infra import logging as runtime_logging


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
