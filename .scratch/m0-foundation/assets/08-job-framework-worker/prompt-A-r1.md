骨架关卡：负责人说"改"，修一轮再进实现。下面逐条修，别处不动。这一步仍然只改契约骨架（签名、类型、docstring/TSDoc、跳过的测试清单），函数体仍是 `raise NotImplementedError` / `throw new Error("未实现")`。修的时候对照 /home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节，不要引入同类问题。评审原文 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/08-job-framework-worker/skeleton-review-A-done.md 可以参考，以本提示为准。

**必须改的**
1. **进度"最多晚 1 秒"**（`progress.py` 第 80–86、149 行附近；`execution.py` 第 169 行附近）：有还没落库的最新值时，`wait()`、`check_cancelled()` 和外部进程入口的轮询里，到了 `PROGRESS_INTERVAL_S` 就补写一次（仍走短锁，拿不到就跳过）。契约写明延迟上界（1 秒加连续跳过短锁的情况，写成具名上限或说明）。补测试：一秒内连报几次后进入长等待，约 1 秒内数据库变成最新值。确认 `job_process_support.py` 里"第 N 条已落库"的握手按新契约一定能等到。
2. **超出停止预算时不能先放锁**（`worker.py` 第 96 行附近、`ops/worker.py` 第 40 行附近）：执行线程和读输出线程都是 daemon，写进契约。线程超出 `WORKER_STOP_TIMEOUT_S` 还没退出时：记一次 ERROR，返回 `WORKER_EXIT_FAILURE`，不抛异常；**只要还有执行线程活着，单实例锁就不释放**，锁随进程退出一起释放（怎么做到你定，例如入口不关锁的文件描述符、由调用方退出进程，写清楚）。补测试：线程超时后，在第一个实例的进程退出之前，第二个实例拿不到锁。
3. **终态写库失败后的去向统一**（`execution.py` 第 119 行附近和 `worker.py` 第 80 行附近现在矛盾）：统一为停止领取、按第 2 条的方式收尾、以 `WORKER_EXIT_FAILURE` 退出，交给 systemd 重启，由下一个实例的恢复流程处理。不能出现"照常写心跳却不再领取"的半活状态。相关测试（`test_jobs_worker.py` 第 66 行、`test_jobs_state.py` 第 64 行附近）跟着改。
4. **领取到保存日志路径之间崩溃**（`execution.py` 第 124、161 行附近）：日志路径在领取（排队中 → 运行中）的同一个事务里算好并写入；`recover_job` 遇到路径已登记但文件不存在（领取提交后、写开头前崩溃）时，新建文件，先写开头再写中断段。补测试。
5. **验收 4 的测试竞争**（`test_jobs_processes.py` 第 155 行附近）：先等工具打印的 `ready` 出现在作业日志里（或等价的就绪握手），再请求取消。

**顺手改的**
6. 取消在 `BEGIN IMMEDIATE` 写事务里读当前状态（`service.py` 第 113 行附近现在在事务外读）：worker 恰好先领取时，用户的取消得到"正在取消"，不是 409。条件更新保留。相应测试改。
7. 领取顺序和"按提交顺序"的查询只按 `job_id`（自增，本身就是提交顺序），不按 `submitted_at`（`records.py` 第 149 行、`service.py` 第 193 行附近）：墙钟回拨会打乱顺序。
8. **恢复方式以当前登记为准**（负责人已批准）：执行的永远是当前代码。提交时保存的值和当前登记任一方是"标记中断"就标记中断；运行中的作业类型已经不在登记表里时标记中断。提交时的快照列只作记录，契约写明。
9. **反复崩溃有上限**（负责人已批准）：作业表加恢复次数，续跑、重跑每恢复一次加一，超过具名上限 3 次改按标记中断处理，作业日志的中断段写明原因。单条作业恢复失败（记录损坏、日志写不进去等）只结束这一条（能落终态就落终态，落不了就记 ERROR 跳过），不让整个 worker 退出。补测试。
10. 正在取消超过具名时长（你定，例如 60 秒）执行函数还没退出时，记一次 WARNING，并在作业日志写一条诊断，说明作业没有响应取消。不改状态。
11. 续跑时进度的基线写清楚：执行函数从上下文拿到上次的最后进度，续跑后报的值能不能小于它、计数怎么接，定下来写进 `progress.py` 和 `execution.py` 的契约。
12. 外部工具在 worker 被 SIGKILL 后会成为孤儿继续跑：契约写明生产环境靠第 11 张 systemd 服务的 `KillMode=control-group` 一并结束，`TimeoutStopSec` 要不小于停止预算 30 秒；测试环境由夹具清理。
13. `test_jobs_processes.py` 第 75–81 行附近：`finally` 里 `process.wait` 超时会跳过 `cleanup_orphans`，改成嵌套的 `try/finally`。`processes.py` 第 64 行附近：SIGKILL 后子进程收不回来（例如 D 状态）时，写明抛 `ExternalError`、读输出线程作为 daemon 遗留。
14. `execution.py` 第 121 行附近：`execute_job` 自己判断不了"越过停止预算"，从它的 `Raises` 删掉，归到 `run_loop`。
15. `jobs` 只 import `rdp.accounts` 的公开接口，不 import 带下划线的模块；确认现在是这样。

改完 `make check` 全绿，OpenAPI 变了用 `make api-types` 重新生成，不手改生成文件。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只改 import-linter：`rdp.jobs` → `rdp.audit`、`rdp.accounts` 的依赖方向；依赖表和别的段不动）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。测试只用临时目录。

为了不超时：预计 80 分钟内改不完时，停在 `make check` 全绿的位置交回，第 4 块写清还剩什么。

最终回复分四块：
1. 逐条写处理结果（第 1–15 条）。
2. `make check` 最后一次运行的命令和末尾输出原样贴出（pytest、Vitest 的 passed、skipped 数目要看得出）；再贴 `git status --porcelain --untracked-files=all`。
3. 契约变更申请、依赖申请、受保护文件申请：没有就写"无"。
4. 拿不准、需要评审决定的地方。
