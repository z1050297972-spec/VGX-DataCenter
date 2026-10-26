"""日志输入异常（07），沿用规范 6.2 的输入问题体系，不携带原始载荷。"""

from http import HTTPStatus
from typing import ClassVar

from rdp.infra.diagnostics import InputError


class AuditInputError(InputError):
    """日志查询、保留期、快照或明细不满足字段契约。

    Attributes:
        http_status: 固定 422 UNPROCESSABLE_ENTITY，无单位、不可空。
        category: 继承 INPUT，不另建异常体系。
        diagnostics: 非空安全诊断元组；只含字段名和规则，不回显拒绝值或秘密。
    """

    http_status: ClassVar[HTTPStatus] = HTTPStatus.UNPROCESSABLE_ENTITY
