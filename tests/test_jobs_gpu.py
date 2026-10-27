"""09 GPU 契约清单；唯一外部工具是测试生成的假 nvidia-smi，不探测真实硬件。"""

from pathlib import Path

import pytest

# 假脚本用相邻的 mode 文件控制场景，不接受外部命令；即使未配置 mode 也只报告虚构的两张卡。
# CUDA 环境由框架注入，脚本把实际继承值写到 stderr，测试独立断言并发隔离而非假装查询了真实 GPU。
FAKE_NVIDIA_SMI_SCRIPT = r"""#!/usr/bin/env python3
import os
import pathlib
import sys
import time

mode_path = pathlib.Path(__file__).with_name("mode")
mode = mode_path.read_text().strip() if mode_path.exists() else "two"
if mode == "timeout":
    time.sleep(30)
if mode == "failure":
    sys.stderr.write("模拟驱动不可用\n")
    sys.exit(9)
if mode == "blank_stderr":
    sys.stderr.write(" \n\t")
    sys.exit(7)
if mode == "large_stderr":
    for index in range(10000):
        sys.stderr.write(f"模拟长输出 {index}\n")
    sys.exit(8)
if mode == "malformed":
    sys.stdout.write("坏卡号\n")
    sys.exit(0)
if any(arg.startswith("--query-gpu") for arg in sys.argv):
    sys.stdout.write("0\n" if mode == "missing" else "0\n1\n")
else:
    sys.stdout.write("模拟 nvidia-smi 输出\n")
    sys.stderr.write("CUDA_VISIBLE_DEVICES=" + os.environ.get("CUDA_VISIBLE_DEVICES", "缺失") + "\n")
    sys.stderr.write("CUDA_DEVICE_ORDER=" + os.environ.get("CUDA_DEVICE_ORDER", "缺失") + "\n")
"""


@pytest.fixture
def fake_nvidia_smi(tmp_path: Path) -> Path:
    """GPU 契约夹具：仅在临时目录生成可执行替身，进程由被测框架及测试 finally 回收。"""
    path = tmp_path / "nvidia-smi"
    path.write_text(FAKE_NVIDIA_SMI_SCRIPT, encoding="utf-8")
    path.chmod(0o700)
    return path


def test_two_cards_three_jobs(fake_nvidia_smi: Path) -> None:
    """验收2：两卡三作业前两项各领不同卡、先领最小空卡；第三项queued且等待GPU，归还后才开始。"""
    pytest.skip("09 契约待实现；使用注入的假脚本")


@pytest.mark.parametrize("ending", ["completed", "failed", "cancelled", "stopped", "interrupted"])
def test_release_all_endings(fake_nvidia_smi: Path, ending: str) -> None:
    """验收2：完成/失败/取消/停止/崩溃后恢复的每种路径不漏名额，后续作业可用卡，终态记录保留卡号。"""
    pytest.skip("09 契约待实现；分别观察资源池与数据库历史")


@pytest.mark.parametrize("mode", ["missing", "failure", "timeout", "malformed", "blank_stderr"])
def test_probe_failures(fake_nvidia_smi: Path, mode: str) -> None:
    """验收3：缺卡/非零/超时/坏输出/空白stderr均ExternalError，诊断有卡号、命令、stderr尾和后果，作业失败且归还卡。"""
    pytest.skip("09 契约待实现；不依赖真实GPU")


def test_startup_missing_card(fake_nvidia_smi: Path) -> None:
    """验收3：启动核对每张配置卡，失败记worker.log一次ERROR并移出本实例池，其他好卡可分配，CPU作业仍可开始。"""
    pytest.skip("09 契约待实现")


def test_recheck_after_claim(fake_nvidia_smi: Path) -> None:
    """验收3：启动时存在而领取后消失的卡也必须重新核对，类型execute不被调用，不回退CPU。"""
    pytest.skip("09 契约待实现")


def test_disabled_gpu(fake_nvidia_smi: Path) -> None:
    """K1：空GPU配置的需卡作业领取后外部失败，诊断明确没有配置可用卡，不无限queued。"""
    pytest.skip("09 契约待实现")


def test_child_environment(fake_nvidia_smi: Path) -> None:
    """验收2：并发子进程分别继承自己的CUDA_VISIBLE_DEVICES及PCI_BUS_ID，不修改父环境、不串卡。"""
    pytest.skip("09 契约待实现；假脚本输出实际继承环境")


def test_header_and_card_line(fake_nvidia_smi: Path) -> None:
    """契约：作业开头后写卡号，进程启动前写最终CUDA两项实际值，nvidia-smi用-i，stdout/stderr带前缀经JobLog完整写入。"""
    pytest.skip("09 契约待实现")


def test_probe_large_output(fake_nvidia_smi: Path) -> None:
    """契约：假工具大量输出完整入日志，内存及诊断stderr尾有界且标记截断，超时回收不留子进程。"""
    pytest.skip("09 契约待实现")


def test_bad_dependency(fake_nvidia_smi: Path) -> None:
    """契约：非法卡号/相对程序路径/日志依赖为DefectError，工具未启动、现有日志未修改。"""
    pytest.skip("09 契约待实现")


def test_all_startup_cards_excluded(fake_nvidia_smi: Path) -> None:
    """负责人决定：配置卡全部核对失败时有效池为空，需卡作业领取后以平台没有可用的卡外部失败，CPU仍可完成。"""
    pytest.skip("09 契约待实现")


def test_excluded_card_requires_restart(fake_nvidia_smi: Path) -> None:
    """负责人决定：失败卡修好后本实例仍绝不分配，重启再次核对成功才重新入池，不能运行期静默重启用。"""
    pytest.skip("09 契约待实现")


def test_startup_log_only(fake_nvidia_smi: Path) -> None:
    """评审5：启动verify_gpu(log=None)只通过logger写worker.log，不另设核卡文件；作业内核对传当前线程安全JobLog。"""
    pytest.skip("09 契约待实现")


def test_optional_command_only_without_configured_cards() -> None:
    """评审6：nvidia_smi=None仅在配置gpus为空时合法，配置非空即使预计全部失败也必须注入绝对路径。"""
    pytest.skip("09 契约待实现")


def test_gpu_checks_persisted_for_instance() -> None:
    """负责人决定：核对通过/移出及诊断原子写worker_gpu_checks，实例标识与心跳关联；失败回滚旧快照，Web不读取内存。"""
    pytest.skip("09 契约待实现")
