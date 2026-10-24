"""入口层共用的 ASGI 调用类型；只描述框架开放字典，不复制协议字段（M0 03/04）。

沿用第 3 张的标准库 Callable/MutableMapping 表示，不直接依赖传递依赖 starlette。
"""

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

type ASGIMessage = MutableMapping[str, Any]
type Receive = Callable[[], Awaitable[ASGIMessage]]
type Send = Callable[[ASGIMessage], Awaitable[None]]
type ASGIApp = Callable[[ASGIMessage, Receive, Send], Awaitable[None]]
