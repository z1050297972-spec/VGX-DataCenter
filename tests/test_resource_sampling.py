"""使用临时 proc 样本验证资源采样，不访问真实存储根。"""

from pathlib import Path

import pytest

from rdp.monitoring.proc import read_sample, sample_rates


def test_proc_samples(tmp_path: Path) -> None:
    """固定计数器的差值计算网卡速率、CPU 占用和内存字节数。"""
    net = tmp_path / "netdev"
    stat = tmp_path / "stat"
    mem = tmp_path / "meminfo"
    net.write_text("eth0: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0\n")
    stat.write_text("cpu  100 0 50 850 0 0 0 0\n")
    mem.write_text("MemTotal: 1000 kB\nMemAvailable: 400 kB\nSwapTotal: 200 kB\nSwapFree: 150 kB\n")
    before = read_sample(net, stat, mem, 10.0)
    net.write_text("eth0: 3000 0 0 0 0 0 0 0 5000 0 0 0 0 0 0 0\n")
    stat.write_text("cpu  160 0 70 870 0 0 0 0\n")
    after = read_sample(net, stat, mem, 12.0)
    result = sample_rates(before, after)
    assert result.network["eth0"] == (1000.0, 1500.0)
    assert result.cpu_percent == 80.0
    assert after.memory_bytes == (1024000, 409600, 204800, 153600)


def test_vpn_signals_and_credentials(tmp_path: Path) -> None:
    """分别识别网卡、代理进程和环境变量，返回值绝不包含代理凭据。"""
    from rdp.monitoring.vpn import vpn_status

    interfaces = tmp_path / "net"
    interfaces.mkdir()
    (interfaces / "tun0").mkdir()
    (interfaces / "tun0" / "tun_flags").write_text("0x1001\n")
    enabled = vpn_status(interfaces, ["mihomo"], {"HTTPS_PROXY": "http://alice:secret@proxy:8080"})
    assert enabled.interfaces == "on"
    assert enabled.processes == "on"
    assert enabled.proxy == "on"
    assert enabled.proxy_hosts == ("proxy:8080",)
    assert "secret" not in repr(enabled)
    (interfaces / "tun0" / "tun_flags").unlink()
    (interfaces / "tun0").rmdir()
    disabled = vpn_status(interfaces, ["python"], {})
    assert (disabled.interfaces, disabled.processes, disabled.proxy) == ("off", "off", "off")


@pytest.mark.parametrize(("name", "expected"), [("Mihomo", "on"), ("tailscale0", "off")])
def test_tun_flags_distinguish_proxy_from_ssh(tmp_path: Path, name: str, expected: str) -> None:
    """任意名称的 TUN 网卡被识别，但仅用于 SSH 的 Tailscale 不算全局代理。"""
    from rdp.monitoring.vpn import vpn_status

    interfaces = tmp_path / "sys" / "class" / "net"
    device = interfaces / name
    device.mkdir(parents=True)
    (device / "tun_flags").write_text("0x1001\n")
    assert vpn_status(interfaces, [], {}).interfaces == expected


@pytest.mark.parametrize("process", ["verge-mihomo", "clash-verge-ser"])
def test_proxy_process_substrings(tmp_path: Path, process: str) -> None:
    """识别带前后缀及 comm 截断的代理名，匹配不区分大小写。"""
    from rdp.monitoring.vpn import vpn_status

    assert vpn_status(tmp_path, [process], {}).processes == "on"
    assert vpn_status(tmp_path, [process.upper()], {}).processes == "on"
