"""Web 入口层报错查询（05/E2），只查有界报错，不读取日志文件或任意路径。

本票尚无登录，暂不鉴权；第 06 张必须限制为所有登录账号可看，不限定管理员。
响应模型直接使用基础层快照，经 OpenAPI 生成前端类型，不放宽 ProblemResponse 的 uuid4 限制。
"""

from http import HTTPStatus
from typing import Annotated, ClassVar

from fastapi import Depends, Path
from sqlalchemy.orm import Session

from rdp.api.database import get_read_session
from rdp.infra.db.records import ErrorRecord
from rdp.infra.diagnostics import InputError


class ErrorReportNotFoundError(InputError):
    """报错已清除或从未存在，保留输入/数据问题分类。

    Attributes:
        http_status: 固定 HTTPStatus.NOT_FOUND（404），无单位、不可空、类默认值。
        category: 继承 INPUT，无单位、不可空、不覆盖。
        diagnostics: 继承至少一条 INPUT/ERROR 诊断，单位条、不可空、无默认。
    """

    http_status: ClassVar[HTTPStatus] = HTTPStatus.NOT_FOUND


class InvalidErrorIdentifierError(InputError):
    """错误编号参数无效，不能把非法原值回显给日志或客户端。

    Attributes:
        http_status: 固定 HTTPStatus.UNPROCESSABLE_ENTITY（422），无单位、不可空、类默认值。
        category: 继承 INPUT，无单位、不可空、不覆盖。
        diagnostics: 继承至少一条 INPUT/ERROR 诊断，单位条、不可空、无默认。
    """

    http_status: ClassVar[HTTPStatus] = HTTPStatus.UNPROCESSABLE_ENTITY


def get_error_details(
    error_id: Annotated[
        str,
        Path(
            min_length=1,
            max_length=32,
            pattern=r"^([0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}|[1-9][0-9]{0,18})$",
        ),
    ],
    session: Annotated[Session, Depends(get_read_session, scope="function")],
) -> ErrorRecord:
    """为 GET /api/errors/{error_id} 返回一条完整报错。

    Args:
        error_id: 请求 uuid4 hex 或作业规范正整数十进制文本，无单位；作业最大 2^63-1，
            无前导零，不接受路径、SQL 或任意字符串；框架先校验形状，函数再校验整数上界。
        session: 本请求缓存的只读 Session；仅供同步路由线程使用，响应发送前关闭。

    Returns:
        ErrorRecord，HTTP 200 JSON；包含编号、UTC 时间、类别、摘要、同日志的报告和来源种类；
        来源编号就是 error_id。响应模型进入 OpenAPI；不返回 SQL、请求体或额外日志上下文。
        本票暂不鉴权，第 06 张加“所有登录账号可看”的登录依赖，不仅管理员。

    Raises:
        ErrorReportNotFoundError: 找不到记录（含过期清除），404；诊断对象 error_id，规则为
            “报错必须仍在保留期内且已成功保存”，实际“不存在”，期望“有一条报错”，
            后果“无法展示完整报错”，下一步“按编号查询运行日志或联系维护者”。
        InvalidErrorIdentifierError: 直接调用时格式错误，或作业编号越界，422；不回显非法原值。
            HTTP 形状错误由框架 RequestValidationError 返回同类 422。
        InputError: 数据库/时间列损坏；拒绝返回部分详情。
        ConflictError: 读取锁冲突。
        ExternalError: 数据库未启用、权限或 I/O 失败。
        DefectError: 其他 SQL/映射程序错误。

    Side Effects:
        无（只读一条记录）；不查任意日志文件、不延长保留期、不自行记日志。

    Time Semantics:
        单次查询，不等待将来的插入；时间返回 UTC，浏览器显示时转本地。
        SQLite 单次锁等待约 5 秒；客户端 5 秒超时可能先放弃，服务端不重试。
    """
    raise NotImplementedError
