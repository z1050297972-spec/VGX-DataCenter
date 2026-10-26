"""操作日志与登录日志领域（M0 第 7 张），只追加、查询及按保留期清除。

使用标准库 datetime/enum、已批准的 Pydantic/SQLAlchemy，不另造序列化或事务框架。
账号权限及账号存在性由上层显式提供，本模块不反向依赖 accounts、HTTP 或运维入口。
领域导入只登记共用 MetaData，不连接数据库或自动升级；表结构由迁移控制。
"""

# 明确再导出表声明，让所有入口导入本领域时登记同一份MetaData，避免遗漏注册。
from rdp.audit.models import AuditSettingsRow as AuditSettingsRow
from rdp.audit.models import LoginLogRow as LoginLogRow
from rdp.audit.models import OperationLogRow as OperationLogRow
