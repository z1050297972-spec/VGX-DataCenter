你在 M1.5 第 03 张「场景、任务词表与分类筛选」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m15-03-scene-task（git worktree，分支 t/m15-03-scene-task，从 main 开出；M1 第 01–08、10 张，以及 M1.5 第 01、02 张都已合并）里工作。

**接手说明**：这张票原本由一个 Claude 子 agent 在做，它已经做了大约 15 分钟，负责人要求改回由你来做。工作区里可能有它留下的未完成改动。先用 `git status`、`git diff` 看清现状，能用的就留下，不对的就改。

这张票是**直做**：按 TDD 先写测试、看到红，再实现，用 $tdd 和 $enterprise-coding。

先用绝对路径读这些（规划文件读主仓库 /home/shawn/桌面/robot-data-platform 里的版本）：
- 工单 .scratch/m1.5-edit-view-classify/issues/03-scene-task-classification.md 全文
- .scratch/m1.5-edit-view-classify/decisions.md、vocab-draft.md（词表就按这份做）
- AGENTS.md、docs/standards/CODING_STANDARDS.md、docs/agents/codex-workflow.md 第 3.0 节和第 7.1 节（7.1 列的是以前被打回过的写法）
- 已合并的代码：
  - M1.5 第 02 张的字段编辑：数据集信息.json 顶层的 robot_model、scene、tasks，FieldEditing.tsx，nav_fields_preview；
  - M1 的扫描和索引：src/rdp/jobs/datasets/ 下的 reading、models、_index_write 和迁移；
  - 筛选和接口：src/rdp/jobs/dataset_browser/、src/rdp/api/datasets/、src/web/src/datasets/Filters.tsx；
  - 三种布局：LayoutA/B/C.tsx。
- 迁移照现有做法加在 versions/ 里，编号接 main 的 head。

要求：
- 控件统一用 antd，不要用原生 select；
- 1280×900 下不能出现横向滚动条；时间用 time.ts 的 formatDateTime；
- 关键控件加稳定的 aria-label；
- OpenAPI 用 `make api-types` 生成；
- 最后 `make check` 全绿、0 skipped；`cd src/web && node_modules/.bin/vite build`，主入口低于 500 kB，跑完删掉 dist；
- 工单里"一键建议"是可选项，时间不够就不做，写进报告。

注意：M1 第 09 张（改指向）此刻在另一个工作目录里合并，它会动 registry、api/__init__、Details.tsx、jobs/Pages.tsx。你尽量少碰这些共用文件；非碰不可的，在报告里逐处列出。

边界：
- 只改 `src/`、`tests/`；
- 不 `git add`、不提交；
- **不读不写 `/mnt`**；
- 不联网、不安装；
- 不碰真实部署，不调用 systemctl，不占用 8600 端口；
- 不碰别的 worktree；
- 测试用 `make check`，不要另开更多并行。

75 分钟内交付。最终回复五块：
1. 改动清单（共用文件单独列）；
2. make check 汇总行；
3. 契约变更（迁移编号、新字段）；
4. 演练要用的请求例子和 aria-label，以及拿不准的地方；
5. 先红后绿。
