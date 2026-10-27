检查点 2 收到。执行线复跑 `make check` 全绿（pytest 1572 passed / 91 skipped，Vitest 205 / 23 skipped），日志审计干净，快照 `refs/rdp/m0-09/B-cp2`。`test_sigkill_recovery` 改为排序后比较可以接受，但注释里的"09/K3："是过程说法（7.1），改成只写现在的规则（不同类型互不阻塞，所以只核对执行次数）。

继续按 prompt-B 的要求和边界实现剩余测试（必要时用绝对路径重读 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/09-job-scheduling-resources/prompt-B.md），仍然每条先单独运行看到红再实现。顺序建议：
1. `test_jobs_navigation.py`（写锁顺序、等待可取消、300 秒上限用测试专用短参数、写入期间屏蔽取消）；
2. `test_jobs_gpu.py`（核卡、坏卡落库、入口装配、子进程环境；只用假 `nvidia-smi`）；
3. `test_jobs_schedules.py`、`test_jobs_maintenance.py`、`test_jobs_scheduling.py` 剩下两条；
4. `test_jobs_scheduling_api.py` 和前端三个测试文件（OpenAPI 有变化用 `make api-types`；页面 search 参数经真实 router 测）。

80 分钟内做不完仍停在 `make check` 全绿处交检查点，第 4 块列剩余。只有三种情况停下：要加新依赖；要改允许范围外的受保护文件；要改已获批契约的含义。最终回复五块同前。
