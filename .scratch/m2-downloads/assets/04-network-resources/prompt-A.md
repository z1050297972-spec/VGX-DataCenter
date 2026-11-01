你在工单「网络与资源监控」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m2-downloads（git worktree，分支 t/m2-downloads）里实现这张票。分级：直做，先写测试再实现。分支上已有第 01–03 张（下载计划、下载作业、下载页面），复用它们，不改它们的公开契约。

先读（规划文件读主仓库目录 /home/shawn/桌面/robot-data-platform 里的版本）：AGENTS.md、docs/standards/CODING_STANDARDS.md、docs/agents/codex-workflow.md 第 7.1 节、工单 .scratch/m2-downloads/issues/04-network-resources.md、spec .scratch/m2-downloads/spec.md（「测试范围」）、ADR 0005、0006（含修订）。复用：第 01 张的 `probe_mirror`、M0 的 GPU 核对（`src/rdp/jobs/gpu.py`）、调度里的定时提交（`schedules.py`、`scheduling.py`）、前端外壳导航。

**负责人要求"只做关键性的测试"**。测试只写这些，每条一到两个，不为罕见情况补测试或写防御分支：
1. `/proc/net/dev`、`/proc/stat`、`/proc/meminfo` 用固定样本文件算出的网速、CPU 百分比、内存数正确。
2. VPN 判断三项（TUN 类网卡、已知代理进程、代理环境变量）各有"开"和"关"的用例；代理变量里带用户名口令时，接口响应里不出现口令。
3. 镜像检查：308 回官方站显示"镜像不生效"，200 显示"生效"，失败或超时显示"未知"并带检查时间。镜像检查在 worker 里定时跑（建议 60 秒一次，加手动"立即检查"），结果存库，Web 只读。
4. 前端：页面展示镜像状态、VPN 结论、网速折线、资源占用，一个 Vitest 用例。

实现要点：Web 读 `/proc`、`/sys` 是本机内核信息，允许；存储根剩余空间由 worker 读（ADR 0006）。采样间隔、保留点数、代理进程名单写成具名常量。页面名"网络与资源"，放进外壳导航。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：生成的 `openapi.json`、`schema.d.ts`（只能用 `make api-types`）；如果要加表，新增迁移编号 **0016**，`down_revision` 接 `0015_download_staging`（合并时执行线统一改号）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。不安装，不访问网络。
- 只在三种情况停下：要加新依赖；要改允许范围外的受保护文件；要改第 01–03 张的公开契约或已有接口。其余自己按最简单安全的方式定，写进最终回复。
- `make check` 不并发跑多份。

最终回复的**第一行**必须是 `状态：全部完成`（工单全部做完、`make check` 全绿）或 `状态：未完成`（列出这一轮做了什么、还剩什么，执行线会自动让你继续）。全部完成时后面接五块：1 改动清单；2 `make check` 末尾输出原样；3 依赖申请；4 自己定的设计选择；5 先红后绿（每个测试一行）。
