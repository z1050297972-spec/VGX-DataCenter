"""账号领域四类异常的状态细分（06），只携带安全诊断，不记录或拼接凭据。"""

from http import HTTPStatus
from typing import ClassVar, cast

from rdp.infra.diagnostics import Diagnostic, InputError


class AuthenticationError(InputError):
    """未登录、过期、停用或登录凭据不正确；外部文案不区分账号存在与否。

    Attributes:
        http_status: 固定 HTTPStatus.UNAUTHORIZED，无单位、不可空、类默认值。
        category: 继承 INPUT，无单位、不可空、不覆盖。
        diagnostics: 至少一条同类别 ERROR 诊断，无单位、不可空、无默认；不得含凭据或未知登录名。
    """

    http_status: ClassVar[HTTPStatus] = HTTPStatus.UNAUTHORIZED


class AuthorizationError(InputError):
    """角色不足或 Origin 校验失败。

    Attributes:
        http_status: 固定 HTTPStatus.FORBIDDEN，无单位、不可空、类默认值。
        category: 继承 INPUT，无单位、不可空、不覆盖。
        diagnostics: 至少一条同类别 ERROR 诊断，无单位、不可空、无默认；不得含凭据或未知登录名。
    """

    http_status: ClassVar[HTTPStatus] = HTTPStatus.FORBIDDEN


class PasswordChangeRequiredError(InputError):
    """尚未完成强制改密码，拒绝其他业务访问。

    Attributes:
        http_status: 固定 HTTPStatus.FORBIDDEN，无单位、不可空、类默认值。
        category: 继承 INPUT，无单位、不可空、不覆盖。
        diagnostics: 至少一条同类别 ERROR 诊断，无单位、不可空、无默认；不得含凭据或未知登录名。
    """

    http_status: ClassVar[HTTPStatus] = HTTPStatus.FORBIDDEN


class AccountNotFoundError(InputError):
    """管理员或本地运维指定的目标账号不存在。

    Attributes:
        http_status: 固定 HTTPStatus.NOT_FOUND，无单位、不可空、类默认值。
        category: 继承 INPUT，无单位、不可空、不覆盖。
        diagnostics: 至少一条同类别 ERROR 诊断，无单位、不可空、无默认；不得含凭据或未知登录名。
    """

    http_status: ClassVar[HTTPStatus] = HTTPStatus.NOT_FOUND


class AccountInputError(InputError):
    """账号字段、密码或时刻不满足输入约束。

    Attributes:
        http_status: 固定 HTTPStatus.UNPROCESSABLE_ENTITY，无单位、不可空、类默认值。
        category: 继承 INPUT，无单位、不可空、不覆盖。
        diagnostics: 至少一条同类别 ERROR 诊断，无单位、不可空、无默认；不得含凭据或未知登录名。
    """

    http_status: ClassVar[HTTPStatus] = HTTPStatus.UNPROCESSABLE_ENTITY


class CurrentPasswordError(AccountInputError):
    """改本人密码时当前密码不正确，保留会话并提示修正输入。

    Attributes:
        http_status: 固定 HTTPStatus.BAD_REQUEST（400），无单位、不可空、类默认值；
            是 AccountInputError 的业务输入子类，不改变普通字段校验的 422。
        category: 继承 INPUT，无单位、不可空、不覆盖。
        diagnostics: 至少一条 INPUT/ERROR 诊断，提示“当前密码不正确”，不可空、无默认；
            不含原文；不得触发清 cookie 或登录导航。连续第五次错误改抛 LoginWaitError。
    """

    http_status: ClassVar[HTTPStatus] = HTTPStatus.BAD_REQUEST


class LoginWaitError(InputError):
    """启用账号的 G2 等待拒绝；入口将安全剩余秒数写入 Retry-After。

    Attributes:
        http_status: 固定 429 TOO_MANY_REQUESTS，无单位、不可空、类默认值。
        category: 继承 INPUT，无单位、不可空、不覆盖。
        diagnostics: 至少一条 INPUT/ERROR 诊断，不含账号是否存在、密码或 cookie，无默认。
        retry_after_s: 向上取整的剩余等待秒数，1-60、不可空、无默认。
    """

    http_status: ClassVar[HTTPStatus] = HTTPStatus.TOO_MANY_REQUESTS
    retry_after_s: int

    def __init__(self, diagnostics: tuple[Diagnostic, ...], *, retry_after_s: int) -> None:
        """构造已提交限流状态对应的安全拒绝。

        Args:
            diagnostics: 非空 INPUT/ERROR 元组；说明等待规则、拒绝后果和重试时间，不包含凭据。
            retry_after_s: 1-60 的整数秒数，不接受 bool；由领域按剩余时长向上取整。

        Returns:
            无；实例保留诊断和可供入口输出的剩余秒数。

        Raises:
            ValueError: 诊断不合法或 retry_after_s 越界、类型错误；消息不回显输入。

        Side Effects:
            无；不读时钟、不修改已提交的失败计数，不记录日志。

        Time Semantics:
            同步构造；剩余秒数以调用者传入的 now 计算，无等待。
        """
        if (
            isinstance(retry_after_s, bool)
            or not isinstance(cast(object, retry_after_s), int)
            or not 1 <= retry_after_s <= 60
        ):
            raise ValueError("等待秒数必须是 1 至 60 的整数")
        super().__init__(diagnostics)
        self.retry_after_s = retry_after_s
