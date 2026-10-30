你在 M1 第 08 张工单「建链与新增数据集」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m1-08-link-create-new-dataset（git worktree，分支 t/m1-08-link-create-new-dataset，从 main 开出；第 01–07 张已合并）里写**契约骨架**。

先用绝对路径读这些（规划文件读主仓库 /home/shawn/桌面/robot-data-platform 里的版本）：
- AGENTS.md、docs/standards/CODING_STANDARDS.md、docs/agents/codex-workflow.md 第 3.0 节和第 7.1 节（7.1 列的是以前被打回过的写法，一开始就避开）
- 工单 .scratch/m1-datasets/issues/08-link-create-new-dataset.md 全文，**特别是最后一条 Comment**：执行线定的三条（数据集名规则、没有 meta/info.json 时格式怎么来、前端不拆票）
- .scratch/platform-v1/issues/12-link-rules.md 的 Answer（L1–L19），docs/adr/0009、0006、0005，docs/manual/导航层手册.md 第 9 节
- 第 07 张已合并的写入底座 `src/rdp/jobs/navwrite/`（计划、预览作业 `run_preview`、`nav_write_apply`、日志、恢复、变更记录、操作码 `create_link`/`create_dataset`），新操作都要建在它上面，不要另写一套写入逻辑
- 第 03–05 张的数据集接口和页面写法（`src/rdp/api/datasets/`、`src/rdp/jobs/dataset_browser/`、`src/web/src/datasets/`），以及第 07 张的恢复页

用 $enterprise-coding。这一步**只交契约骨架**：
1. 后端：建链、新增数据集两种操作的预览构造（builder）、参数模型、结果模型、HTTP 接口（提交预览、读预览结果、确认后提交写入），以及签名、类型和六项 docstring。函数体只写 `raise NotImplementedError`。
2. 前端：页面和组件的骨架（props 类型、TSDoc），以及跳过的 Vitest 测试。
3. 测试清单写成跳过的测试，docstring 写明验证哪条契约，覆盖工单的验收条目。
4. `make check` 全绿，只允许本票新增的 skipped。

骨架关卡要看的东西，在最终回复第 4 块单独列出：接口路径、方法和字段；预览结果给前端看的结构；两种操作分别生成哪些计划步骤；数据集名和链接名的校验规则；页面流程（填参数 → 预览 → 确认 → 作业页）。

边界：
- 只改 `src/`、`tests/`，以及工单「允许改的受保护文件」里列出的文件。OpenAPI 有变化时用 `make api-types` 生成。
- 不 `git add`、不提交。
- **不读不写 `/mnt`**。真实导航层的结构看 /home/shawn/桌面/robot-data-platform/.scratch/m1-datasets/assets/01-nav-read-index-rescan/baseline-*.txt。
- 不联网、不安装，不新增依赖；需要新依赖时停下，写依赖申请。
- 不碰 `~/.config/rdp`、`~/.local/share/rdp`、`~/.local/opt/rdp`（正在运行的真实部署），不调用 systemctl，不占用 8600 端口。
- 不碰别的 worktree。
- 自己建的试验文件交付前删掉。机器内存紧张，测试用 `make check`，不要另开更多并行。

只有三种情况停下：要加新依赖；要改允许范围以外的受保护文件；要改已合并契约的含义（只加参数或字段的，可以先做，再在第 3 块申请）。

60 分钟内交付。最终回复四块：1 改动清单；2 `make check` 末尾输出；3 契约变更申请、依赖申请；4 骨架关卡要看的东西，以及拿不准的地方。
