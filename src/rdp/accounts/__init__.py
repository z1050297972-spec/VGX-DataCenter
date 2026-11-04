"""账号领域层（M0 工单 06），负责身份、密码、会话与最后管理员不变量。

只依赖基础层与已批准的 SQLAlchemy/Pydantic/argon2；不 import Web 框架或 jobs。
不写运行、操作或登录日志；HTTP/cookie 和交互输入分别由 api、ops 负责。
"""
