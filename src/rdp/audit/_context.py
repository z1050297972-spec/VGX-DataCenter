"""日志领域的可信入口上下文校验；只检查格式，不读取请求或替调用方补造来源。"""

from ipaddress import ip_address

from rdp.audit.types import AuditContext
from rdp.infra.diagnostics import DefectError
from rdp.infra.ids import is_request_id


def validate_context(value: object, *, ops: bool = False, request: bool = True) -> AuditContext:
    """在业务读写前拒绝错误的入口上下文，运维与请求来源不能混用。"""
    if not isinstance(value, AuditContext):
        raise DefectError()
    if ops:
        if value.source_ip is not None or value.request_id is not None:
            raise DefectError()
        return value
    if (request or value.request_id is not None) and not is_request_id(value.request_id):
        raise DefectError()
    if value.source_ip is not None:
        try:
            # 带作用域地址依赖本机接口，不是可移植的来源 IP；数据库只存规范文本。
            if "%" in value.source_ip or str(ip_address(value.source_ip)) != value.source_ip:
                raise ValueError("来源地址不是规范IP")
        except (TypeError, ValueError):
            raise DefectError() from None
    return value
