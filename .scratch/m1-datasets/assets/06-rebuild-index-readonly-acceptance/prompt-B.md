你在 M1 第 06 张工单的工作目录 /home/shawn/桌面/robot-data-platform.wt/m1-06-rebuild-index-readonly-acceptance（git worktree，分支 t/m1-06-rebuild-index-readonly-acceptance，从 main 开出；第 01、02、03 张已经合并）里工作。

这张票**分级是直做**（codex-workflow.md 3.0 第 1 条）：不交骨架，直接先写测试、再实现，用 $tdd 和 $enterprise-coding。每个测试先单独运行，看到红，再实现；第一次就绿的，逐项说明原因。

先用绝对路径读这些：
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/m1-datasets/issues/06-rebuild-index-readonly-acceptance.md 全文，按它的范围、验收、不做来干。
- AGENTS.md、docs/standards/CODING_STANDARDS.md、docs/agents/codex-workflow.md 第 3.0 节和第 7.1 节（7.1 是以前被打回过的写法）。
- 工单引用的决策和已合并代码。前端要看 `src/web/` 里现有页面、路由、API 客户端的写法，以及第 03 张生成的 `src/web/src/api/schema.d.ts`；后端要看 `src/rdp/ops/` 和 `src/rdp/jobs/datasets/`。
- 第 01–03 张执行线的真实演练记录，在 /home/shawn/桌面/robot-data-platform/.scratch/m1-datasets/assets/ 下各票的目录里，可以了解真实数据的规模和形状。

**分两段交**：先把工单"排在前半段"的那条验收要用的东西做出来，交检查点，`make check` 全绿，没做完的测试保留跳过。执行线会在沙箱外做那条真实演练，结果作为下一段的输入。下一段补齐其余部分。

边界：
- 只改 `src/`、`tests/`，以及工单「允许改的受保护文件」里列出的文件。
- OpenAPI 有变化用 `make api-types` 生成。
- 不 `git add`、不提交。
- **不读不写 `/mnt`**。
- 不联网、不安装，不新增依赖：需要就停下，写依赖申请。
- 不碰真实部署（`~/.config/rdp`、`~/.local/share/rdp`、`~/.local/opt/rdp`），不起占用 8600 端口的服务，不调用 systemctl。
- 自己建的试验文件交付前删掉。

只有三种情况停下：要加新依赖；要改允许范围以外的受保护文件；要改已合并契约的含义（只加参数或字段的，可以先做，再在第 3 块申请）。

60 分钟内交检查点。最终回复五块：
1. 改动清单；
2. `make check` 的 pytest 汇总行和末尾输出；
3. 契约变更申请、依赖申请；
4. 执行线做真实演练需要知道的东西（例如怎么起、要用什么命令），拿不准的地方，以及下一段还剩什么；
5. 先红后绿，每个测试一行。
