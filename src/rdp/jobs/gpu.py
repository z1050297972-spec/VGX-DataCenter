"""GPU 存在性核对（领域层，09）；只在 worker 调用，不配置驱动或管理平台外的占用。

使用标准库 subprocess 流式捕获输出，避免无界 PIPE 内存；校验失败只补诊断，
由启动/执行边界分别记录一次 ERROR。CUDA 环境注入在 processes，不由作业类型拼接。
"""

from pathlib import Path

from rdp.jobs.logs import JobLog


def verify_gpu(gpu_index: int, nvidia_smi: Path, *, log: JobLog | None) -> None:
    """在有界时间内确认指定物理卡号可被 nvidia-smi 查询。

    Args:
        gpu_index: 严格整数 0 至 MAX_GPU_INDEX，PCI_BUS_ID 顺序的物理编号。
        nvidia_smi: 入口注入的绝对可执行路径；测试只提供临时假脚本。
        log: 必填；作业执行时传入当前 JobLog，所有输出通过其线程安全写入接口；
            只有启动核对传 None，输出由当前模块 logger 写 worker.log，不另建日志文件。

    Returns:
        无；仅工具零退出且查询结果明确包含此编号时成功。

    Raises:
        ExternalError: 启动失败、非零/信号退出、GPU_PROBE_TIMEOUT_S 超时、缺卡、输出格式损坏
            或输出捕获失败；诊断含卡号、命令、退出码/信号、stderr 有界尾部、后果和检查驱动建议。
            无 stderr 或纯空白使用固定说明，不能因诊断空字段退化为程序缺陷；禁止回退 CPU。
        DefectError: 卡号、路径或调用依赖不合法；不启动进程。

    Side Effects:
        shell=False 执行 nvidia-smi --query-gpu=index --format=csv,noheader,nounits；
        两路输出保留 stdout/stderr 与 nvidia-smi 行前缀，作业中只通过 JobLog 写入，禁止直接打开日志路径；
        启动时只写已配置的 worker.log。完整流式保留输出，stderr 尾限 PROCESS_STDERR_TAIL_LINES/PROCESS_STDERR_TAIL_MAX_BYTES。
        超时终止并有界回收进程，不改 GPU 占用；调用者负责 finally 归还已领名额。
        本层不 ERROR；启动边界对失败卡记一次 ERROR 并移出本实例名额池，CPU 作业继续。
        作业执行前核对失败仍由执行器令该作业外部失败并归还卡，不在此更改启动池成员。

    Time Semantics:
        超时 GPU_PROBE_TIMEOUT_S=5 秒，用单调时长；回收另限 PROCESS_REAP_TIMEOUT_S。
        启动逐卡核对；作业领卡提交后、执行类型函数前再次使用同一核对函数，不在写事务中执行。
    """
    raise NotImplementedError
