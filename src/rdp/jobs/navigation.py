"""导航层写锁执行边界（领域层，09/ADR 0005）；锁在 worker 实例内，不是模块单例。

标准库 threading.Lock 提供互斥；框架只控制顺序，预览核对与实际写入由作业类型提供。
"""

from collections.abc import Callable

from rdp.jobs.progress import ProgressReporter


class NavigationWriter:
    """整个导航层共用的一把非可重入锁，执行上下文由 worker 注入同一对象。"""

    def __init__(self) -> None:
        """构造一个尚无人持有的导航层写锁。

        Args:
            无。

        Returns:
            无；每次构造互相隔离，worker 仅构造一次。

        Raises:
            无。

        Side Effects:
            只建立进程内 Lock；不创建文件锁、不访问导航层或数据库。

        Time Semantics:
            在线程启动之前调用，崩溃后内存锁随进程消失。
        """
        raise NotImplementedError

    def run[T](
        self,
        reporter: ProgressReporter,
        verify: Callable[[], None],
        write: Callable[[], T],
    ) -> T:
        """拿锁后核对预览状态，只有核对通过才调用写入。

        Args:
            reporter: 当前作业的上报/取消及资源副本对象，关联唯一 job_id。
            verify: 同步无参数核对；不改业务数据，冲突抛 ConflictError，诊断由类型查明最后修改者 #N。
            write: 同步无参数写入；返回任意类型 T，不可递归取锁，不可启动异步写入后提前返回。
                每个阻塞操作有界，持锁段应能在 worker 三十秒共同停止预算内完成。

        Returns:
            write 的原返回值；核对失败或等待取消时 write 一次也不会调用。

        Raises:
            JobCancelledError: 等锁前/期间或拿锁后进入保护区前收到取消；保护区内延后至放锁后的下一检查点。
            WorkerStoppingError: 等锁期间或进入保护区前停止；持锁期间同样延后，不能中断半次写入。
            ConflictError: 达到 NAVIGATION_LOCK_TIMEOUT_S=300 秒仍未获得锁，诊断包含当前作业编号、
                单调累计实际等待秒数、超时时观察到的持锁作业编号（释放竞争时明确无人持有）、
                等待上限、未执行写入的后果及下一步；或 verify 判定预览已失效。
            ExternalError: 回调中的外部写入、资源展示或日志出现不可跳过的 I/O 失败。
            InputError: 回调拒绝业务输入或资源存储损坏。
            DefectError: 嵌套取锁、非法回调/依赖，或回调其他异常；原异常交执行器收口，不在此重复报告。

        Side Effects:
            锁内维护持有人 job_id，取得后登记、finally 释放时清空；超时身份来自实例内存，不信任滞后数据库副本。
            顺序为设置等待原因→有界分段拿锁→清等待并标持锁→verify→write→finally 放锁并清持锁。
            资源副本短锁忙只留待补写；不能为显示等待持有数据库事务或阻塞调度。
            持锁段通过 reporter.defer_cancellation 屏蔽人为取消及停止控制异常；普通异常照常传播。
            verify 或 write 抛异常、worker 停止时均 finally 释放；清副本失败不能阻止释放或掩盖原异常。
            不自动回滚 write 已产生的产物，其失败残留由类型契约约束；不在放锁时主动检查取消以免掩盖写入异常。

        Time Semantics:
            每次 acquire 最多 NAVIGATION_LOCK_POLL_S=0.05 秒，总等待最多 300 秒，使用注入单调时钟。
            等待期间补写进度和资源；持锁期间上报仍可运行，取消信号保留不清除，下一检查点才响应。
            线程不协作导致超出停止预算时，worker 单实例锁按第 8 张保留到进程退出，不提前宣称导航锁已释放。
        """
        raise NotImplementedError
