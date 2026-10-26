"""运维入口的日志补记故障报告契约（07），不依赖 API、不写两种日志表。

报告仅供创建首管理员及运维重置的最外层异常边界使用，不供领域层调用。
固定标记由 accounts._boundary 保留，任意异常 notes 和第二异常原文不能穿过脱敏边界。
"""

from rdp.audit.reporting import report_audit_append_failure as report_audit_append_failure
