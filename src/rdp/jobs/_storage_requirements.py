"""作业领域内部共享的存储声明校验；登记与执行复用同一规则，不做任何I/O。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from rdp.infra.diagnostics import DefectError
from rdp.infra.ids import JOB_TYPE_KEY_PATTERN

if TYPE_CHECKING:
    from rdp.jobs.registry import StorageUse


def validate_storage_uses(uses: tuple[StorageUse, ...]) -> None:
    """核对不可变需求、合法根名、严格写许可及唯一性，避免绕过登记扩大权限。"""
    # 类型公开路径保持在registry；延迟导入只为解除登记模块与共享校验的导入环。
    from rdp.jobs.registry import StorageUse

    if type(uses) is not tuple:
        raise DefectError()
    names: set[str] = set()
    for use in uses:
        if (
            not isinstance(cast(object, use), StorageUse)
            or not isinstance(cast(object, use.name), str)
            or re.fullmatch(JOB_TYPE_KEY_PATTERN, use.name) is None
            or type(use.write) is not bool
        ):
            raise DefectError()
        if use.name in names:
            raise DefectError()
        names.add(use.name)
