检查点 3 收到。执行线复跑 `make check` 全绿（pytest 1595 passed / 70 skipped，Vitest 205 / 23 skipped），日志审计干净，快照 `refs/rdp/m0-09/B-cp3`。

契约申请批准：`read_example_value` 读取预算改为最多 `NAVIGATION_EXAMPLE_LINE_MAX_BYTES + 1` 字节，额外一字节只用于确认行界，单行上限仍为 4096 字节。docstring 的 Side Effects 一句按此改，用常量表达式而不是字面量 4097。把 `test_full_limit_tail_after_previous_line` 去掉跳过，先红后绿。两个新增只读属性 `ProgressReporter.job_id`、`clock` 照收。

继续按 prompt-B 的要求和边界实现剩余测试（必要时重读 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/09-job-scheduling-resources/prompt-B.md），每条先单独运行看到红再实现。顺序建议：
1. `test_jobs_gpu.py`（核卡、坏卡落库、入口装配、示例集成；只用假 `nvidia-smi`）；
2. `test_jobs_schedules.py`、`test_jobs_maintenance.py`、`test_jobs_scheduling.py` 剩下两条；
3. `test_jobs_scheduling_api.py` 和前端三个测试文件（OpenAPI 有变化用 `make api-types`；页面 search 参数经真实 router 测；调度页挂进菜单和路由）。

80 分钟内做不完仍停在 `make check` 全绿处交检查点，第 4 块列剩余。全部完成时，在本票改过的文件里搜"骨架""提案""派工""桩""实现阶段""留待""负责人决定""评审"，不留。只有三种情况停下：要加新依赖；要改允许范围外的受保护文件；要改已获批契约的含义。最终回复五块同前。
