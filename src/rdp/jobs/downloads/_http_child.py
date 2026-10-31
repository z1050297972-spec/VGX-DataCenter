"""单次镜像请求子进程；凭据只从标准输入接收，不写日志或文件。"""

import base64
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any, cast, override

from rdp.jobs.downloads.plan import HttpResponse

# 分块读取的字节数；限制每次临时分配，并在超限后尽快终止。
_READ_CHUNK_BYTES = 64 * 1024


class _BodyTooLargeError(Exception):
    """响应超过上限时停止读取。"""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """拒绝自动跳转，避免把凭据交给非镜像站点。"""

    @override
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        """将重定向作为原始响应交给调用方。"""
        return None


def _urllib_request(
    method: str, url: str, headers: Mapping[str, str], timeout_s: float, max_body_bytes: int
) -> HttpResponse:
    """在隔离进程中执行单次无代理且不跟随跳转的 urllib 请求。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    # URL 已在 UrllibTransport.request 中限制 HTTPS 和镜像主机；拒绝重定向。
    request = urllib.request.Request(url, headers=dict(headers), method=method)  # noqa: S310
    try:
        response = opener.open(request, timeout=timeout_s)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = response.read(min(_READ_CHUNK_BYTES, max_body_bytes + 1 - size))
            size += len(chunk)
            if size > max_body_bytes:
                raise _BodyTooLargeError
            if not chunk:
                break
            chunks.append(chunk)
        status = response.status
        if not isinstance(status, int):
            raise OSError("镜像响应状态无效")
        # HTTP 允许多个 Link 头；只保留最后一个会丢失分页 next。
        headers_out: dict[str, str] = {}
        for name, value in response.headers.items():
            key = next(
                (existing for existing in headers_out if existing.lower() == name.lower()), name
            )
            if name.lower() == "link" and key in headers_out:
                headers_out[key] += ", " + value
            else:
                headers_out[key] = value
        return HttpResponse(status=status, headers=headers_out, body=b"".join(chunks))


def _main() -> None:
    """子进程读取单个请求并输出不含可执行对象的 JSON。"""
    try:
        request = cast(dict[str, Any], json.loads(sys.stdin.buffer.read()))
        result = _urllib_request(
            request["method"],
            request["url"],
            request["headers"],
            request["timeout_s"],
            request["max_body_bytes"],
        )
        data: dict[str, object] = {
            "status": result.status,
            "headers": dict(result.headers),
            "body": base64.b64encode(result.body).decode("ascii"),
        }
    except _BodyTooLargeError:
        data = {"error": "oversize"}
    except Exception:
        data = {"error": "connection"}
    sys.stdout.buffer.write(json.dumps(data).encode("utf-8"))


if __name__ == "__main__":
    _main()
