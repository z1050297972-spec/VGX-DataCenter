检查点收到，接着做完剩下的 22 个 Python 测试和 11 个前端页面测试（你第 4 块列的清单），规则照 prompt-B.md（先读 7.1，先写测试再写实现）。默认 fetch 回归测试的那处校正，评审时核对，这轮不用动。

顺序：先 Python（`test_jobs_state`、`test_jobs_registry`、`test_jobs_logs`、`test_jobs_service`、`test_jobs_worker`、`test_jobs_api`），再前端页面和对应实现，最后收尾：搜过程说法（"骨架""桩""实现阶段""留待""尚未"）、删临时文件（包括 `/tmp/rdp-m0-08-*`）→ 最后一次 `make check`，pytest 和 Vitest 都不留 skipped。

80 分钟左右还做不完，照旧停在相关测试全绿的位置交检查点。第 5 块只写本轮新做的测试。
