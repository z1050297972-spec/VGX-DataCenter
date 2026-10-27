检查点收到。执行线已复跑 `make check` 全绿（pytest 1537 passed / 123 skipped，Vitest 205 / 23 skipped），日志审计干净，快照 `refs/rdp/m0-09/B-cp1`。两处单条 `S608` 豁免可以，docstring 措辞调整照收。

继续按 prompt-B 的要求和边界实现剩余测试（重读 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/09-job-scheduling-resources/prompt-B.md 和 /home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节），仍用 $tdd 和 $enterprise-coding，每条先单独运行看到红再实现。

建议顺序（后面的依赖前面的）：
1. `test_jobs_scheduling.py`（资源池、按类型取队首、并发循环、恢复）和 `test_jobs_scheduling_config.py::test_production_types`；
2. `test_jobs_gpu.py`（核卡、进程环境；只用假 `nvidia-smi`，路径注入）；
3. `test_jobs_navigation.py`（写锁顺序、等待可取消、300 秒上限用测试专用短参数、写入期间屏蔽取消）；
4. `test_jobs_schedules.py`、`test_jobs_maintenance.py`；
5. `test_jobs_scheduling_api.py`，再前端三个测试文件（OpenAPI 有变化用 `make api-types`）。

所有等待有上限，子进程和线程在 `finally` 里回收；不依赖本机时区，不改全局时区。80 分钟内做不完仍停在 `make check` 全绿的位置交检查点，第 4 块列剩余。

只有三种情况停下：要加新依赖；要改允许范围外的受保护文件；要改已获批契约的含义。最终回复五块同前。
