"""第 11 张 worker_entry 契约清单；只用临时目录和可注入依赖，不触碰真实部署或服务。"""

import pytest


def test_exit_codes() -> None:
    """验证契约：第8张：正常0、失败1、实例冲突2及停止超预算原样经 start_worker/run_cli/main 返回给 sys.exit。"""
    pytest.skip("第 11 张：等待对应实现")


def test_signals_stop() -> None:
    """验证契约：验收：注入信号安装器把SIGTERM和SIGINT都映射到同一个stop Event；不直接杀工具或写数据库。"""
    pytest.skip("第 11 张：等待对应实现")


def test_signal_restore() -> None:
    """验证契约：stop_signals 在受控子进程测试正常/异常退出均恢复原处理器；部分安装失败也回滚，不修改 pytest 的真实处理器。"""
    pytest.skip("第 11 张：等待对应实现")


def test_signal_invalid_thread() -> None:
    """验证契约：非主线程安装信号拒绝为 DefectError，不留下半安装状态；测试线程 finally 回收。"""
    pytest.skip("第 11 张：等待对应实现")


def test_retained_lock() -> None:
    """验证契约：WorkerExit.lock_retained=True 时不 dispose、不解锁、不在同进程重启，最终退出保留失败码。"""
    pytest.skip("第 11 张：等待对应实现")


def test_normal_cleanup() -> None:
    """验证契约：无遗留线程时释放引擎一次，信号上下文异常或 GPU 定位失败也安全清理。"""
    pytest.skip("第 11 张：等待对应实现")


def test_scheduling_settings() -> None:
    """验证契约：WorkerScheduling 含同一 catalog、GPU绝对路径与 config.errors.retention_days，不遗漏定时维护。"""
    pytest.skip("第 11 张：等待对应实现")


def test_logging_clock() -> None:
    """验证契约：run_worker 接收与入口相同的 LogTime，二次日志配置不会丢注入时钟或 --no-stderr。"""
    pytest.skip("第 11 张：等待对应实现")


def test_held_lock_refused() -> None:
    """验证契约：验收3：独立临时子进程持有worker.lock时检查返回拒绝，诊断含锁路径、实际状态、后果与下一步。"""
    pytest.skip("第 11 张：等待对应实现")


def test_free_and_missing_lock() -> None:
    """验证契约：锁缺失或陈旧文件未持锁时允许；不创建缺失文件，不依赖文件内容中的PID或过期心跳。"""
    pytest.skip("第 11 张：等待对应实现")


def test_probe_releases_lock() -> None:
    """验证契约：探测成功后立刻释放并关闭fd，真正worker随后可取得同一inode锁；不删除替换锁文件。"""
    pytest.skip("第 11 张：等待对应实现")


def test_probe_errors() -> None:
    """验证契约：相对路径、目录、软链接拒绝；权限、打开和加/解锁失败不能误报已停止，所有fd回收。"""
    pytest.skip("第 11 张：等待对应实现")
