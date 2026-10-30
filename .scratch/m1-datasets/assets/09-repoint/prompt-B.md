你在 M1 第 09 张工单「改指向」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m1-09-repoint（git worktree，分支 t/m1-09-repoint，从 main 开出；第 01–08、10 张都已合并）里工作。

负责人要求加快速度，这张票由执行线**改为直做**：写入底座（第 07 张）和预览、确认、写入、撤回的模式（第 08、10 张）都已经有现成的了。所以不交骨架，直接按 TDD 先写测试再实现，用 $tdd 和 $enterprise-coding。每个测试先单独运行，看到红，再实现；第一次就绿的，逐项说明原因。

先用绝对路径读这些（规划文件读主仓库 /home/shawn/桌面/robot-data-platform 里的版本）：
- AGENTS.md、docs/standards/CODING_STANDARDS.md、docs/agents/codex-workflow.md 第 3.0 节和第 7.1 节（7.1 是以前被打回过的写法）
- 工单 .scratch/m1-datasets/issues/09-repoint.md 全文（含 Comments）
- .scratch/platform-v1/issues/12-link-rules.md 的 Answer（重点 L8、L16–L19）、docs/adr/0009
- 已合并的代码：`src/rdp/jobs/navwrite/`（底座、撤回的 `nav_revert_preview`）；第 08 张的建链和新增数据集（`creation` 相关的预览构造、接口、409/201 确认、前端 Creation*.tsx），改指向照同样的写法做；第 10 张的数据来源；第 07 张的恢复页
- 真实数据的样子看 /home/shawn/桌面/robot-data-platform/.scratch/m1-datasets/assets/01-nav-read-index-rescan/baseline-*.txt 和 assets/07-nav-write-foundation/replica-drill-run.log（alpha 那 3 个够不着的数据块）

**分两段交**：
1. 后端：改指向预览的构造（前缀替换遵守 L17 的边界规则、L18 的范围、L8 重新生成按格式入口，L19 的新位置核对在 worker 里做）、接口、写入复用 nav_write_apply；外加撤回的接口（任意写导航层作业的"撤回预览 → 确认"，冲突时列出差异）。做完交检查点，`make check` 全绿，前端测试保留跳过。执行线会在真实导航层的副本上演练一次"把某个数据集从 dataset1 改指向到 dataset2 上同名目录"这类场景。
2. 前端（下一次派工）：详情里的"改指向"入口；作业详情和操作日志里每个写导航层作业的"撤回"入口。

边界：
- 只改 `src/`、`tests/`；OpenAPI 有变化用 `make api-types` 生成。
- 不 `git add`、不提交；**不读不写 `/mnt`**；不联网、不安装，不新增依赖。
- 不碰真实部署（`~/.config/rdp`、`~/.local/share/rdp`、`~/.local/opt/rdp`），不调用 systemctl，不占用 8600 端口；不碰别的 worktree。
- 测试用 `make check`，不要另开更多并行。

只有三种情况停下：要加新依赖；要改允许范围以外的受保护文件；要改已合并契约的含义（只加参数或字段的，可以先做，再在第 3 块申请）。

75 分钟内交后端检查点。最终回复五块：1 改动清单（共用文件单独列）；2 `make check` 汇总行；3 契约变更申请；4 执行线做副本演练要知道的东西（请求例子、怎样选一个新旧位置都存在的场景）、拿不准的地方、下一段还剩什么；5 先红后绿。
