检查点收到，接着把整票做完，规则照 prompt-B.md（先读 7.1，先写测试再写实现，同类测试可以合跑看红）。你第 4 块提到的"编号耗尽归 `ConflictError`"也在这一轮补上。

剩下的顺序（先做 worker 端，再做 Web 端）：
1. `tests/test_jobs_progress.py`、`tests/test_jobs_logs.py`、`tests/test_jobs_state.py`、`tests/test_jobs_registry.py` 剩下的（上报对象、日志、示例执行函数）。
2. `tests/test_jobs_worker.py`（执行器、恢复、单实例锁、主循环、心跳）和 `tests/test_jobs_processes.py`（外部进程、真实子进程场景）。
3. `tests/test_jobs_migration.py` 剩下的 3 个。
4. `tests/test_jobs_service.py`、`tests/test_jobs_api.py`（服务、审计作业明细、HTTP 接口）。
5. 前端 `src/web/src/api/jobs.test.ts`、`src/web/src/jobs/Pages.test.tsx`，以及 `WorkerStatusBanner` 挂进 `AccountLayout`。
6. 收尾：搜过程说法、删临时文件（包括 `/tmp/rdp-m0-08-*`）→ 最后一次 `make check`。

80 分钟左右还做不完，照旧停在相关测试全绿的位置交检查点。第 5 块只写本轮新做的测试。
