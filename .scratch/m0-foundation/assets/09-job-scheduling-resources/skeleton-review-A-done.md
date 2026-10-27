# 第 9 张骨架评审（快照 refs/rdp/m0-09/A-done）

## BLOCKING
1. 恢复候选"容量可用才 recover_job 准备"且"全部遗留项准备前不放行新 queued"（scheduling.py:129-131、worker.py:225、execution.py:256）：两个可重跑的 A 类（上限 1）遗留时，第二个要等第一个跑完才准备，期间所有类型的新作业都领不到，违反 K3；test_recovery_different_types 把它当成期望。未准备的遗留行保留旧 gpu_index，另一个恢复作业领到同一张卡时 scheduling_service.py:198"同卡多个活跃占用"抛 DefectError，调度页 500。改法：启动时一个事务清所有非终态行的 wait_reason/持锁标记和 running/cancelling 行的 gpu_index；准备（中断段、恢复计数）对全部遗留行先做完、不需要资源；准备好的恢复候选只排在本类型队首。
2. "等待 GPU"的清除和写入者没有规定（resources.py:164-165、scheduling.py:137、JobRecord.wait_reason）：worker 停止或崩溃、队首改为被上限挡住、卡空出但扫描顺延时，queued 行上的 wait_reason=gpu 都留着。要写明主循环是 queued 等待原因的唯一写入者、每轮重扫不再等卡就清、启动时清空，并补测试。
3. 调用方必须提供的依赖给了默认 None（7.1，07 骨架打回过）：ops/worker.py:42 `scheduling=None`，execution.py:84/156/175 `resources`/`claim`，progress.py:80 `publisher`，records.py:264 `claim_job(gpu_index=None)`，api/jobs.py:66/74。生产漏传时 worker 悄悄不调度，且每处维护有资源/无资源两条路径。改为必填关键字参数，第 8 张测试改用夹具构造。

## 顺手改
- FIFO 扫描过重（records.py:225、scheduling.py:88-138、policy.py SCAN_*/TICK_BUDGET）：同类严格顺序下可领的只有每类队首，一条 GROUP BY type_name 取 MIN(job_id) 即可，删跨轮游标、批次、排除集合、250ms 预算和对应测试。
- gpu.py:16-18 核卡输出另开句柄写作业日志，绕过 JobLog 的锁和 `stderr <工具名>│` 前缀（6.9）；作业内走 run_process 或传 JobLog。启动核对用的"worker 核对日志"在 StatePaths 里没定义。
- scheduling.py:43 nvidia-smi 路径必填；`gpus=()` 时应允许 None。
- ExecutionContext.resources 暴露资源池、publisher、配置，作业类型能自己释放名额；只注入 NavigationWriter。
- resources.py:50/71/78/98 锁预算借用 OUTPUT_JOIN_TIMEOUT_S，另起具名常量。
- 模块偏碎：scheduling_config.py 并入 scheduling.py；SchedulingCatalog 挪到 scheduling_types，免得 Web 只读服务 import 调度和执行；ResourcePublisher 去掉，直接调 save_resource_display。
- 调度页的页签和 URL 参数超出工单，去掉。
- 两个示例提交接口（api/jobs.py:258/289）可以保留，命名和 `/example` 统一。
- nvidia-smi 不理会 CUDA_VISIBLE_DEVICES，演示看不出隔离：作业日志写一行实际设置的环境变量。
- "系统"保留名双向约束（scheduling_models.py:28-31、service.py:93）让真名叫"系统"的账号提交不了，0005 遇到历史行拒绝升级；改单向、按编号区分。
- 补测试：跨类型抢卡按 job_id 先给等卡的队首；run_loop 级集成测试（每轮调用 tick_schedules，清除作业跑完）。

## 验收覆盖
1–7 其余各项都有能区分对错的跳过测试。

## 需要负责人拍板
1. 清除作业两个不是三个。
2. 启动时核对不过的卡留在名额池里，"编号最小的空卡"规则会让 0 号坏卡导致所有 GPU 作业接连失败：要不要剔出名额池（重启后重新核对）。
3. 等写锁 300 秒超时按冲突失败，M1 重新扫描长时间持锁时后面的写入会成批失败：改成不设总上限、可取消、页面显示在等？
