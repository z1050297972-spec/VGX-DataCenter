# 第 8 张骨架评审（A-done，快照 d97ad3d）

机械检查：`make check` 复跑全绿（pytest 1265 passed / 147 skipped，Vitest 179 passed / 22 skipped）；只改了 `src/`、`tests/` 和 `pyproject.toml` 的 import-linter；运行日志（ev-A、ev-A2）没有安装、联网、碰 /mnt 或 git 写操作；`/tmp` 无残留；违规试验 12 项全部符合预期（violation_probe-A-done.txt）；本票文件里没有过程说法。两路评审（规格/契约、algorithm-code-review）结论由执行线逐条核对过原文。

## 阻塞（执行线核实）
1. **进度最多晚 1 秒做不到**：`progress.py:80-86` 只在 `report()` 里节流写库，`wait()`（`progress.py:149`）写明不写数据库。一步间隔长时（示例作业上限 60 秒），被节流的最新值要等到下一次 report 才落库，断电时数据库落后几十秒，违反场景一和验收 3；`job_process_support.py` 的握手也可能等不到。
2. **超出停止预算时锁先放掉**：`worker.py:96`、`ops/worker.py:40` 写的是抛 `DefectError`，退出 `worker_lock` 时 flock 释放，而执行线程还活着（是不是 daemon 没写）。第二个 worker 能拿到锁并恢复同一作业，旧线程之后还可能写终态。
3. **终态写库失败后的去向矛盾**：`execution.py:119` 写"主循环停止领取新作业"，`worker.py:80` 写 ConflictError 往外抛。按前者做，worker 照常写心跳却不再领取，页面显示在线、队列不动。
4. **领取和保存日志路径之间崩溃没有定义**：`execution.py:124` 领取提交后另开事务保存 `log_path`，`recover_job`（`execution.py:161`）默认原日志存在。
5. **验收 4 的测试有竞争**：`test_jobs_processes.py:155` 在作业"运行中"就请求取消，工具可能还没装好忽略 SIGTERM 的处理器，测试会随机失败。工具已经打印 `ready`，等它再取消。

## 执行线采纳、一并修的
6. 取消在事务里读状态（`service.py:113` 现在在事务外读）：worker 恰好先领取时，用户的取消应当得到"正在取消"，不是 409。
7. 领取顺序只按 `job_id`（`records.py:149`、`service.py:193` 按 `submitted_at`，墙钟回拨会打乱提交顺序）。
8. 恢复方式以当前登记为准，不用提交时的快照：执行的永远是新代码。提交时的值和当前登记任一方是标记中断就标记中断；类型已经删掉的运行中作业标记中断。快照列只作记录。
9. 反复崩溃有上限：续跑、重跑的作业每次恢复计一次数，超过具名上限（例如 3 次）改按标记中断处理；单条作业恢复失败只结束这一条，不让整个 worker 退出（否则重启后又撞上同一条，队列永久堵住）。
10. 执行函数不配合取消时要有提示：正在取消超过具名时长还没退出，记 WARNING 并在作业日志写一条诊断。
11. 续跑时进度的基线写清楚（从上次最后进度开始，执行函数报的值不能小于它，还是续跑重新起算）。
12. worker 被 SIGKILL 后外部工具会成孤儿继续跑：契约写明依赖第 11 张 systemd 的 `KillMode=control-group`，第 11 张的 `TimeoutStopSec` 不小于停止预算 30 秒。
13. 测试的 finally 嵌套清理（`test_jobs_processes.py:75-81`：`process.wait` 超时会跳过 `cleanup_orphans`）；SIGKILL 后子进程处于 D 状态收不回来时，写明抛 `ExternalError`、读输出线程作为 daemon 遗留。
14. `execution.py:121` 的"越过停止预算"由 `run_loop` 判定，从 `execute_job` 的 Raises 里删掉。

## Codex 第 4 块的决定
- 停止预算 30 秒：同意（10 + 2 + 2 + 5 秒在内），加上阻塞第 2 条。
- 恢复方式在提交时快照：不同意，见第 8 条。
- 终态先提交数据库再写日志结尾，写结尾失败记 ERROR：同意，数据库是事实来源。
- 日志文件名用 UTC、撞名加编号：同意。
- 操作日志表头改"对象"、筛选标签保留"对象账号"：同意。
- jobs → accounts：同意（写事务里要重新认证，第 6 张定的）；只 import `rdp.accounts` 的公开接口，不碰带下划线的模块。
