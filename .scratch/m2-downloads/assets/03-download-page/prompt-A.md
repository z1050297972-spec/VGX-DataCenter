你在工单「下载页面」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m2-downloads（git worktree，分支 t/m2-downloads）里实现这张票。分级：直做，一次派工里先写测试再实现，最后交一次（codex-workflow 3.0 第 1 条）。分支上已经有第 01 张「下载计划」和第 02 张「下载作业」的实现，本票建在它们上面，不改它们已获批的公开契约。

先读（规划文件读主仓库目录 /home/shawn/桌面/robot-data-platform 里的版本）：
- AGENTS.md、docs/standards/CODING_STANDARDS.md、docs/agents/codex-workflow.md 第 7.1 节
- 工单 .scratch/m2-downloads/issues/03-download-page.md
- M2 spec .scratch/m2-downloads/spec.md（「负责人决定」第 2、3、4、6 条，以及「测试范围」）
- ADR 0006（含 2026-10 修订：Web 只有原文件查看器能只读存储根，下载页面不能碰存储根）
- 现有代码：后端 `src/rdp/api/`（看作业接口和管理员接口的写法），前端 `src/web/src/jobs/`、`router.tsx`、`accounts/Pages.tsx`（外壳导航）、`api/`；第 02 张的 `src/rdp/jobs/downloads/`（参数模型、调参通道 `adjustments.py`）
- 生成的接口类型用 `make api-types` 更新，不要手改 `openapi.json`、`schema.d.ts`

**负责人 2026-11-01 的要求："只做关键性的测试"**。测试只覆盖下面这些，每条一到两个测试，不为罕见情况补测试或写防御分支：
1. 后端：提交下载、提交预览、调参、设置/清除 token、列暂存、删暂存这几个接口经真实应用各测正常路径；成员不能设 token、不能删暂存（403）；暂存目录正被作业使用时删除返回 409。
2. token 接口的响应和操作日志里没有 token 文本。
3. 前端：下载表单（含高级参数默认收起、展开后显示 spec 第 6 条那张表的默认值和范围）、预览结果展示、作业详情里调整并发和限速、删除暂存前的确认，各一个 Vitest 用例；带 search 参数的路由经真实 router 测一个（7.1）。

实现要点：
- "预览"在 worker 里跑（复用第 01 张的 `build_plan`，做成一个只读短作业，或者复用下载作业的计划阶段，选最简单的），Web 只提交和读结果。
- 暂存列表由 worker 的只读作业生成、存数据库，页面读结果并显示生成时间；删除暂存也是 worker 作业，进操作日志。
- token 写状态目录里的 `hf_token`，权限 0600；按现有代码约定决定由 Web 写还是做成作业，写进最终回复。
- 页面放进外壳导航（"下载"），样式沿用现有页面。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：生成的 `openapi.json`、`schema.d.ts`（只能用 `make api-types` 生成）；如果要加表，新增迁移 0014。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络。需要新依赖时停下申请。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。
- 只在三种情况停下：要加新依赖；要改允许范围以外的受保护文件；要改第 01、02 张的公开契约或已有接口。其余自己按最简单安全的方式定，写进最终回复。
- 只有实际运行到 80 分钟左右还没做完，才停在 `make check` 全绿的位置交检查点。
- 机器内存紧张，`make check` 不要并发跑多份。

最终回复分五块：
1. 改动清单：每个文件一行。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出。
3. 依赖申请：没有就写"无"。
4. 自己定的设计选择和拿不准的地方。
5. 先红后绿：每个测试一行，写它第一次运行的结果。
