"""Lichtblick 部署常量（基础层，M5-04/10），供运维安装与 Web 托管共用，不下载资源。"""

from pathlib import Path

# M5-04 批准的官方网页包；版本和摘要同时锁定，更新必须另走依赖评审。
LICHTBLICK_VERSION = "1.30.0"
# M5-10：补丁目录与原始发行版隔离，避免已装的未修补版本被幂等检查跳过。
LICHTBLICK_INSTALL_VERSION = f"{LICHTBLICK_VERSION}-rdp1"
LICHTBLICK_SHA256 = "f73b6bd0b4d2857b7311eb780279494334690e203de43440b54bc75994fd16c6"


def lichtblick_directory(state_dir: Path) -> Path:
    """计算当前锁定版本的网页目录，不探测安装状态。

    Args:
        state_dir: 平台已解析的本地状态根绝对路径，不接受 HTTP 请求提供的路径。

    Returns:
        state_dir/lichtblick/带平台补丁的版本号，路径未必存在；不再使用未打补丁的旧目录。

    Raises:
        无。

    Side Effects:
        无。

    Time Semantics:
        无；版本取本次部署代码中的常量。
    """
    return state_dir / "lichtblick" / LICHTBLICK_INSTALL_VERSION
