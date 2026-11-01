"""从调用者提供的网卡、进程和 worker 环境判断代理迹象，不保留凭据。"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

# comm 可能带产品前后缀且最多保留 15 个字符，按核心名称子串识别代理迹象。
PROXY_PROCESS_KEYWORDS = ("mihomo", "clash", "v2ray", "xray", "sing-box")
PROXY_VARIABLES = frozenset({"http_proxy", "https_proxy", "all_proxy"})
# 负责人经 Tailscale SSH 登录，该通道不改默认路由，不作为全局代理迹象。
EXCLUDED_TUN_PREFIXES = ("tailscale",)
# WireGuard 没有 tun_flags，继续通过其常见网卡名前缀识别。
WIREGUARD_PREFIX = "wg"
Signal = Literal["on", "off", "unknown"]


@dataclass(frozen=True)
class VpnStatus:
    """三种代理迹象和脱敏后的代理主机端口。

    Attributes:
        interfaces: 隧道网卡状态。
        processes: 已知代理进程状态。
        proxy: 环境代理变量状态。
        proxy_hosts: 不含凭据的主机端口。
    """

    interfaces: Signal
    processes: Signal
    proxy: Signal
    proxy_hosts: tuple[str, ...]


def vpn_status(
    interfaces: Path, processes: Sequence[str] | None, environment: Mapping[str, str] | None
) -> VpnStatus:
    """汇总代理迹象，不向结果传递用户名或口令。

    Args:
        interfaces: 网卡目录；通过 tun_flags 或 wg 前缀识别，排除 Tailscale SSH 通道。
        processes: 进程名列表，按核心名称子串忽略大小写匹配；无法读取时为 None。
        environment: worker 环境；无法读取时为 None。

    Returns:
        三项开关状态及代理的主机端口。

    Raises:
        无。

    Side Effects:
        只读取网卡目录。

    Time Semantics:
        结果反映调用时传入的快照。
    """
    try:
        interface_status: Signal = (
            "on"
            if any(
                not device.name.casefold().startswith(EXCLUDED_TUN_PREFIXES)
                and (
                    (device / "tun_flags").exists()
                    or device.name.casefold().startswith(WIREGUARD_PREFIX)
                )
                for device in interfaces.iterdir()
            )
            else "off"
        )
    except OSError:
        interface_status = "unknown"
    process_status: Signal = (
        "unknown"
        if processes is None
        else "on"
        if any(
            keyword in name.casefold() for name in processes for keyword in PROXY_PROCESS_KEYWORDS
        )
        else "off"
    )
    proxy_status: Signal = "unknown"
    hosts: list[str] = []
    if environment is not None:
        values = [v for k, v in environment.items() if k.lower() in PROXY_VARIABLES and v]
        proxy_status = "on" if values else "off"
        for value in values:
            try:
                parsed = urlsplit(value if "://" in value else f"http://{value}")
                host, port = parsed.hostname, parsed.port
            except ValueError:
                # 格式错误的值不得进入错误日志，因为其中可能带有凭据。
                continue
            if host:
                if port is not None:
                    host += f":{port}"
                hosts.append(host)
    return VpnStatus(interface_status, process_status, proxy_status, tuple(hosts))
