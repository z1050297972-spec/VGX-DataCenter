"""工单 04 的纯测试演示挂载契约；生产包不导入这里，不引入配置开关或真实数据。"""

from fastapi import FastAPI


def mount_diagnostic_demo(app: FastAPI) -> None:
    """为执行线的演示应用挂载五个内存故障接口。

    Args:
        app: create_app(None) 或 create_app(测试构建目录) 的新应用；未构建中间件栈。

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
    raise NotImplementedError
