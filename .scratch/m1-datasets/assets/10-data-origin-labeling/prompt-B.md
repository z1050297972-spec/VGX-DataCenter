你在 M1 第 10 张工单「数据来源标注」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m1-10-data-origin-labeling（git worktree，分支 t/m1-10-data-origin-labeling，从 main 开出；第 01–07 张已合并）里工作。

这张票**分级是直做**：不交骨架，直接按 TDD 先写测试、再实现，用 $tdd 和 $enterprise-coding。每个测试先单独运行，看到红，再实现；第一次就绿的，逐项说明原因。

先用绝对路径读这些（规划文件读主仓库 /home/shawn/桌面/robot-data-platform 里的版本）：
- AGENTS.md、docs/standards/CODING_STANDARDS.md、docs/agents/codex-workflow.md 第 3.0 节和第 7.1 节（7.1 列的是以前被打回过的写法）
- 工单 .scratch/m1-datasets/issues/10-data-origin-labeling.md 全文（含 Comments）
- .scratch/platform-v1/issues/15-tool-manifest-lineage.md、docs/adr/0008、0009
- 第 07 张已合并的写入底座 `src/rdp/jobs/navwrite/`，**特别是 `provenance.py`**（来源.json 第 1 版：`with_data_origin`、`dump_provenance`、三态读取）和操作码 `set_data_origin`；改数据来源要走第 07 张的预览 → 写入流水线，不另写写入逻辑
- 第 03–05 张的接口和页面写法，以及第 07 张的恢复页

**注意**：第 08 张此刻在另一个工作目录里并行开发，也会在 navwrite 上加东西。你只加数据来源这一种操作，尽量少改共用文件。共用文件非改不可时，在报告里列出改了哪几处，方便合并。

**分两段交**：先把后端（作业类型、预览、写入、接口）做完，交检查点，`make check` 全绿，前端测试保留跳过。执行线会在真实导航层的副本上演练一次，结果作为下一段的输入。下一段做前端。

边界：
- 只改 `src/`、`tests/`，以及工单「允许改的受保护文件」里列出的文件。OpenAPI 有变化时用 `make api-types` 生成。
- 不 `git add`、不提交。
- **不读不写 `/mnt`**。真实导航层的结构看 /home/shawn/桌面/robot-data-platform/.scratch/m1-datasets/assets/01-nav-read-index-rescan/baseline-*.txt。
- 不联网、不安装，不新增依赖；需要新依赖时停下，写依赖申请。
- 不碰 `~/.config/rdp`、`~/.local/share/rdp`、`~/.local/opt/rdp`（正在运行的真实部署），不调用 systemctl，不占用 8600 端口。
- 不碰别的 worktree。
- 自己建的试验文件交付前删掉。机器内存紧张，测试用 `make check`，不要另开更多并行。

只有三种情况停下：要加新依赖；要改允许范围以外的受保护文件；要改已合并契约的含义（只加参数或字段的，可以先做，再在第 3 块申请）。

60 分钟内交检查点。最终回复五块：1 改动清单；2 `make check` 的 pytest 汇总行和末尾输出；3 契约变更申请、依赖申请；4 执行线做副本演练需要知道的东西（怎么构造一次改数据来源），拿不准的地方，以及下一段还剩什么；5 先红后绿，每个测试一行。
