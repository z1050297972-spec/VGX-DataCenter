骨架评审结论：改一轮。负责人已在骨架关卡回答（2026-10-27）：
- 清除作业登记两个（"清除过期报错""清除过期日志"），照现在的契约。
- worker 启动时核对不过的卡**移出名额池**：记 ERROR，本次运行不再分配；修好后重启 worker 重新核对。配置里的卡全都核对不过时，需要 GPU 的作业按"平台没有可用的卡"处理（同 `gpus = []`）。调度页显示哪些卡被移出。
- 等导航层写锁**保留 300 秒上限**，照现在的契约；超时诊断写明等了多久、锁被哪个作业拿着。

动手前重读 /home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节。只改契约骨架（签名、类型、docstring、跳过测试），新函数体仍只抛未实现；`make check` 全绿。

**阻塞（必须改）**

1. 恢复不能挡住别的类型（违反 K3），也不能留下过时的资源副本（scheduling.py:129-131、worker.py:225、execution.py:256）。改成：
   - worker 拿到锁后、开始调度前，一个事务把所有非终态行的等待原因和持锁标记清掉，把运行中、正在取消行的卡号清掉。不受容量限制。
   - 对全部遗留行先做完"准备"（写中断段、加恢复次数、正在取消 → 已取消、标记中断的直接终态），不需要资源，不等容量。
   - 准备好、要续跑或重跑的作业排在**本类型**队首，按本类型的上限和卡领资源；别的类型照常领取。
   - `test_recovery_different_types` 改成验证这个行为；加一条：两个同类可重跑遗留 + 一个别类排队，别类不等。
2. "等待 GPU"的写入和清除要写明（resources.py:164-165、scheduling.py:137、`JobRecord.wait_reason`）：主循环是排队中作业等待原因的唯一写入者；每轮重新判断，队首不再是等卡（领到卡、被上限挡住、被取消）就清掉；启动时由第 1 条一并清空。补测试。
3. 调用方必须提供的依赖不给默认值（7.1，07 骨架打回过）：`ops/worker.py:42 scheduling`、`execution.py:84,156,175 resources/claim`、`progress.py:80 publisher`、`records.py:264 claim_job(gpu_index)`、`api/jobs.py:66,74` 改为必填关键字参数（确实"可以没有"的值，类型写 `X | None` 但仍然必填）。第 8 张已有测试改用夹具构造，只改构造方式不改断言。

**顺手改**

4. 扫描简化：同类严格按顺序时，能领的只可能是每类队首。用一条查询取每类最小的排队中 `job_id`，按 `job_id` 排序逐个判断上限和卡；删掉跨轮游标、批次、排除集合、`SCAN_*`、`TICK_BUDGET` 和对应测试。
5. 核卡（gpu.py:16-18）在作业里经作业日志对象写（走外部进程入口或传入 JobLog，保持行前缀和线程安全）；启动核对只写 `worker.log`，不另设日志文件。
6. `nvidia-smi` 路径（scheduling.py:43）改为 `Path | None`，只有卡列表为空时允许 None。
7. `ExecutionContext` 只给作业类型一个导航层写入入口（NavigationWriter 一类），不暴露资源池、发布者、配置；清除作业需要的东西用最小的接口给。
8. 资源池的锁预算另起具名常量，不借用 `OUTPUT_JOIN_TIMEOUT_S`（resources.py:50,71,78,98）。
9. 模块合并：`scheduling_config.py` 并入 `scheduling.py`；`SchedulingCatalog` 挪到 `scheduling_types.py`，Web 的只读服务不 import 调度、执行、写锁模块；去掉 `ResourcePublisher`，直接调 `save_resource_display`。
10. 调度页去掉页签和 URL 参数（`scheduling/search.ts` 和两条 router 测试），工单只要一个只读页。两个示例提交接口保留，路径和 `/example` 的命名统一。
11. "示例：占用 GPU"在作业日志写一行实际设置给子进程的 `CUDA_VISIBLE_DEVICES`、`CUDA_DEVICE_ORDER`（`nvidia-smi` 自己不理会这个变量，演示要看得出隔离）。
12. "系统"保留名改成单向约束：编号为空就必须是"系统"；有编号的账号按编号区分，名字叫"系统"也照常能提交，`0005` 不因历史行拒绝升级。页面上"系统"按编号为空判断。
13. 补两条测试：跨类型抢卡时按 `job_id` 先给等卡的队首（A 类队首在等卡、B 类在后，卡空出先给 A）；`run_loop` 级集成测试：主循环每轮调用定时检查，清除作业能跑完。
14. 第 2 条决定（坏卡移出名额池）和第 3 条决定（300 秒）对应的契约和测试。

边界、停下的三种情况、四块最终回复都同 prompt-A.md。第 3 块列出本轮改了哪些已合并公开签名。
