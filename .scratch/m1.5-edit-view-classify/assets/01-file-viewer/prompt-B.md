你在 M1.5 工单的工作目录 /home/shawn/桌面/robot-data-platform.wt/m15-01-file-viewer（git worktree，分支 t/m15-01-file-viewer，从 main 开出；M1 第 01–08、10 张已合并）里工作。

这张票**分级是直做**：不交骨架，直接按 TDD 先写测试再实现，用 $tdd 和 $enterprise-coding。每个测试先单独运行，看到红，再实现。

先用绝对路径读这些（规划文件读主仓库 /home/shawn/桌面/robot-data-platform 里的版本）：
- 工单 .scratch/m1.5-edit-view-classify/issues/01-file-viewer.md 全文，以及 .scratch/m1.5-edit-view-classify/decisions.md
- AGENTS.md、docs/standards/CODING_STANDARDS.md、docs/agents/codex-workflow.md 第 3.0 节和第 7.1 节（7.1 是以前被打回过的写法）
- docs/adr/0006、0009，以及 .scratch/platform-v1/issues/12-link-rules.md 的 Answer
- 已合并的代码：src/rdp/jobs/navwrite/、src/rdp/jobs/datasets/、src/rdp/api/datasets/、src/rdp/jobs/dataset_browser/；前端 src/web/src/datasets/，其中第 08 张的 Creation*.tsx、第 10 张的 DataOrigin.tsx 是现成的预览和确认写法；还有 time.ts、formatBytes.ts
- 真实数据的样子看 .scratch/m1-datasets/assets/01-nav-read-index-rescan/baseline-*.txt

注意：M1 第 09 张（改指向）和另一张 M1.5 票此刻在别的工作目录里并行开发。尽量只新增文件，非改不可的共用文件改动在报告里逐处列出。

**一次交完**：后端和前端都做，最后 `make check` 全绿、0 skipped；`cd src/web && node_modules/.bin/vite build` 主入口低于 500 kB，跑完删掉 dist。真实演练由执行线在沙箱外做，你在报告里写清演练要用的请求例子和 aria-label。

边界：
- 只改 `src/`、`tests/`；`pyproject.toml` 只在要改 import-linter 契约时动，写理由；OpenAPI 用 `make api-types` 生成。
- 不 `git add`、不提交；**不读不写 `/mnt`**；不联网、不安装，不新增依赖。
- 不碰真实部署（`~/.config/rdp`、`~/.local/share/rdp`、`~/.local/opt/rdp`），不调用 systemctl，不占用 8600 端口；不碰别的 worktree。
- 机器内存紧张，测试用 `make check`，不要另开更多并行。

只有三种情况停下：要加新依赖；要改允许范围以外的受保护文件；要改已合并契约的含义（只加参数或字段的，可以先做，再在第 3 块申请）。

90 分钟内交付；做不完就停在全绿的位置交检查点。最终回复五块：1 改动清单（共用文件单独列）；2 `make check` 汇总行；3 契约变更申请；4 演练要用的东西和拿不准的地方；5 先红后绿。
