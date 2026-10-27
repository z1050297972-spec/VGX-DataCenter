打回第 2 轮。上一轮（prompt-B-r1）在你跑最终检查前被执行线一侧的会话中断，没有最终回复；执行线已核对 8 条都改到了（快照 `refs/rdp/m0-09/B-r1-cut`），日志审计干净。但执行线跑 `make check` 时 1 条失败：

```
FAILED tests/test_jobs_worker.py::test_serial_execution
assert queued is not None and queued.state == "queued"   # 实际 'running'
```

单独跑 5 次都通过，只在整套负载下出现。原因是真实缺陷，不是测试问题：作业 72 在执行线程里 `stop.set()`，主循环 `_loop.py` `_fill` 恰好在 `stop.is_set()` 检查之后进入 `claim_next()`，把 73 以 running 提交（带卡号/名额），再看到 stop，只归还内存凭据就返回。数据库里留下一行从未启动的 running；下次启动它会被当作遗留作业恢复，消耗一次恢复次数，interrupt 类型（三个示例）未跑就变成已中断。B-done 时已存在（并发评审曾记为后续），现在因为它让 `make check` 不稳定，必须本轮修。

**要求（先红后绿）**

1. 领取已提交但因停止未启动线程的作业，不能留成 running。用一个短锁事务把它退回 queued：清卡号、等待原因、持锁标记、started_at 等领取时写入的字段，不写操作日志、不增加恢复次数，作业日志不写开头（领取时还没写的话）。只允许"本实例刚领取、线程从未启动"这一种情况走这条退回路径，不新增用户可见状态；这是状态机内部补充，按已批准契约的补充处理，在第 3 块写清改了哪些 docstring。退回事务失败时按现有规则整实例失败（不能静默留 running）。线程启动失败（`_start` 失败）同理处理。
2. 确定性测试：用钩子在 `claim_next` 提交之后、`_fill` 二次检查 stop 之前设置 stop（不靠时序），断言作业仍为 queued、无卡号、名额已归还、恢复次数未变，下一个实例照常领取并执行它一次。
3. `test_serial_execution` 在整套负载下必须稳定：不放宽断言，靠第 1 条修好。修完连续跑 `.venv/bin/pytest -p no:cacheprovider tests/test_jobs_worker.py tests/test_jobs_scheduling.py tests/test_jobs_gpu.py` 三次全绿再跑最终 `make check`。

边界、停下条件同前几轮（只改 `src/`、`tests/`；不安装、不联网；不读 data_check/Data_Collection_System-main，不碰 /mnt；测试不调真实 nvidia-smi；不 `git add`）。60 分钟内交付。

最终回复五块，覆盖第 1 轮（r1 的 8 条）和本轮：1 改动清单；2 `make check` 末尾原样输出及前后 `git status --porcelain --untracked-files=all`；3 契约补充和 docstring/TSDoc 改动；4 拿不准的地方；5 先红后绿（r1 的 3 条缺陷和本轮 1 条，每条第一次运行的结果）。
