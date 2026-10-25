"""工单 04 的纯测试演示挂载契约；生产包不导入这里，不引入配置开关或真实数据。"""

from pathlib import Path
from typing import Annotated, Any, cast

from fastapi import FastAPI, Query

from rdp.infra.diagnostics import ConflictError, DefectError, Diagnostic, ExternalError, InputError


def mount_diagnostic_demo(app: FastAPI) -> None:
    """为执行线的演示应用挂载五个内存故障接口。

    Args:
        app: create_app(None, database=None) 或 create_app(测试构建目录, database=None) 的新应用；未构建中间件栈。

    Returns:
        无；在 /api/_diagnostics-demo/ 下挂 GET input、conflict、external、defect、validation。
        前四个分别抛四类异常；validation 声明必填的正整数 query 参数 count，错误输入走422。
        示例外部失败使用假命令与退出码，缺陷使用代表性示例二的三层 cause 和空 target，
        不调用真实工具/路径；路由排在 /api 兜底和静态挂载之前并可在 OpenAPI 中查看。

    Raises:
        ValueError: 已挂载同前缀路由或应用已启动；先完整检查，失败不留下部分路由。

    Side Effects:
        仅修改测试 app 内存路由及清空 OpenAPI 缓存；不改变生产工厂、配置、磁盘或日志设置。
        请求触发的日志由统一边界负责，演示函数本身不重复打日志。

    Time Semantics:
        同步挂载，测试或演示脚本在服务请求前显式调用；无等待、轮询或外部 I/O。
    """
    if app.middleware_stack is not None or any(
        getattr(route, "path", "").startswith("/api/_diagnostics-demo") for route in app.routes
    ):
        raise ValueError("演示应用已启动或已挂载演示路由")
    routes = {
        "input": _input,
        "conflict": _conflict,
        "external": _external,
        "defect": _defect,
        "validation": _validation,
    }
    for name, endpoint in routes.items():
        app.add_api_route("/api/_diagnostics-demo/" + name, endpoint, methods=["GET"])
        app.router.routes.insert(0, app.router.routes.pop())
    app.openapi_schema = None


def _diagnostic(category: str) -> Diagnostic:
    """演示只使用假对象和安全文字，不访问任何真实路径。"""
    return Diagnostic.model_validate(
        dict(
            level="error",
            category=category,
            stage="演示",
            source="平台",
            objects=[dict(key="dataset", value="演示数据集")],
            rule="对象必须可处理",
            actual="假命令退出码 1" if category == "external" else "不满足要求",
            consequence="本次操作未完成",
            next_step="按诊断检查演示输入",
        )
    )


def _input() -> None:
    """触发输入问题演示。"""
    raise InputError((_diagnostic("input"),))


def _conflict() -> None:
    """触发状态冲突演示。"""
    raise ConflictError((_diagnostic("conflict"),))


def _external() -> None:
    """触发外部工具失败演示，不运行进程。"""
    raise ExternalError((_diagnostic("external"),))


def _defect() -> None:
    """用空 target 建立三层实际异常链，不读取文件。"""
    try:
        try:
            Path(cast(Any, None))
        except TypeError as error:
            raise DefectError((_diagnostic("defect"),)) from error
    except DefectError as error:
        raise DefectError((_diagnostic("defect"),)) from error


def _validation(count: Annotated[int, Query(gt=0)]) -> dict[str, int]:
    """让框架负责必填正整数的类型和范围校验。"""
    return {"count": count}
