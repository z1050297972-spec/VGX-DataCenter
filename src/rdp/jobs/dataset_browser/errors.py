"""数据集查询拒绝（领域层，M1-03），沿用规范6.2的输入类异常，不另起诊断格式。"""

from http import HTTPStatus
from typing import ClassVar

from rdp.infra.diagnostics import InputError


class DatasetQueryError(InputError):
    """查询/布局/范围参数不符合契约，不回显原始请求。"""

    http_status: ClassVar[HTTPStatus] = HTTPStatus.UNPROCESSABLE_ENTITY


class DatasetNotFoundError(InputError):
    """索引中不存在所选入口或永久编号，不代表存储根离线。"""

    http_status: ClassVar[HTTPStatus] = HTTPStatus.NOT_FOUND
