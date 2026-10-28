"""第 11 张 runtime 契约清单；只用临时目录和可注入依赖，不触碰真实部署或服务。"""

import pytest


def test_assembly_order() -> None:
    """验证契约：load_config→状态目录→日志→来源/权限警告→引擎/版本→完整注册表/存储校验→调度/挂载的顺序可观察。"""
    pytest.skip("第 11 张：等待对应实现")


def test_configuration_source() -> None:
    """验证契约：RDP_CONFIG 与 home 替身决定最终配置；未知项或缺指定文件拒绝，日志不输出整份环境。"""
    pytest.skip("第 11 张：等待对应实现")


def test_directory_failure() -> None:
    """验证契约：状态路径被文件占用或不可写时拒绝，不启动服务；宽权限目录只记警告，不自动 chmod。"""
    pytest.skip("第 11 张：等待对应实现")


def test_registry_storage_validation() -> None:
    """验证契约：验收装配：作业声明的根名字未登记时拒绝启动，验证发生在全部类型注册之后。"""
    pytest.skip("第 11 张：等待对应实现")


def test_scheduling_catalog() -> None:
    """验证契约：Web/worker 均使用 resolve_scheduling、production_schedules 及注入本地规则时区；非法并发配置拒绝。"""
    pytest.skip("第 11 张：等待对应实现")


def test_storage_inspector() -> None:
    """验证契约：Web 只装配 MountInspector 的挂载表和 UUID 回调，不运行 read_storage_root 或触碰存储内容。"""
    pytest.skip("第 11 张：等待对应实现")


def test_worker_storage_checker() -> None:
    """验证契约：worker 必须把 StorageAccessChecker(config.storage, inspector, read_storage_root) 传入 ExecutorDependencies。"""
    pytest.skip("第 11 张：等待对应实现")


def test_version_snapshot() -> None:
    """验证契约：服务只读取一次版本；修改构建文件不会改变已运行实例或该实例领取的作业版本。"""
    pytest.skip("第 11 张：等待对应实现")


def test_cleanup_partial_failure() -> None:
    """验证契约：引擎创建后注册表、时区或版本失败时 dispose 一次，保留已建目录/日志，运行器不调用。"""
    pytest.skip("第 11 张：等待对应实现")


def test_clock_invalid() -> None:
    """验证契约：JobClock 的 naive、非有限单调值或回调异常属于 DefectError，不伪装用户输入问题。"""
    pytest.skip("第 11 张：等待对应实现")


def test_gpu_path_found() -> None:
    """验证契约：配置卡非空时通过注入 which 定位绝对 nvidia-smi，worker 不猜 /usr/bin 路径。"""
    pytest.skip("第 11 张：等待对应实现")


def test_gpu_missing_or_relative() -> None:
    """验证契约：配置卡非空但 which 返回 None/相对路径时拒绝并提示修复工具或设置 gpus=[]，不启动 worker。"""
    pytest.skip("第 11 张：等待对应实现")


def test_gpu_empty() -> None:
    """验证契约：配置 gpus=[] 时 nvidia_smi=None，不调用 which，不探测 GPU，CPU 作业仍可运行。"""
    pytest.skip("第 11 张：等待对应实现")


def test_gpu_lookup_faults() -> None:
    """验证契约：命令定位 I/O 归 ExternalError，回调异常/错误类型归 DefectError，释放已创建的引擎。"""
    pytest.skip("第 11 张：等待对应实现")
