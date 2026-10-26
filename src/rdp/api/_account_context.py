"""账号与日志入口共用的已认证身份提取；不重读数据库或接受客户端声明的身份。"""

from rdp.accounts._issues import problem
from rdp.accounts.errors import AuthenticationError
from rdp.accounts.types import SessionIdentity
from rdp.api.account_auth import AccountRequestContext


def identity(context: AccountRequestContext) -> SessionIdentity:
    """认证依赖必须交付身份，直接调用入口时同样失败关闭。"""
    if context.identity is None:
        raise problem(AuthenticationError, "请先登录")
    return context.identity
