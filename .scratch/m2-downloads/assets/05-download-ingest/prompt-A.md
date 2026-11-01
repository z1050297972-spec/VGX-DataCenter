你在工单「下载入库」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m2-downloads（git worktree，分支 t/m2-downloads）里实现这张票。分级：直做，先写测试再实现，一次做完再交。分支上已有第 01–04 张；复用 M1 的写入底座 `src/rdp/jobs/navwrite/`（新增数据集的 creation 那一套：`create_service.py`、`create_jobs.py`、`create_builders.py`、`origin.py`、`provenance.py`）和第 02 张的 `_rename_noreplace`，不改它们的公开契约。

先读（规划文件读主仓库目录 /home/shawn/桌面/robot-data-platform 里的版本）：AGENTS.md、docs/standards/CODING_STANDARDS.md、docs/agents/codex-workflow.md 第 7.1 节、**工单 .scratch/m2-downloads/issues/05-download-ingest.md（范围和验收以它为准）**、spec .scratch/m2-downloads/spec.md（「测试范围」「入库」）、ADR 0006、0008、docs/manual/导航层手册.md（14 项、来源.json）、M1 工单 .scratch/m1-datasets/issues/08-link-create-new-dataset.md。

**负责人要求"只做关键性的测试"**：只写工单「验收」第 1–5 条列出的测试，每条一到两个；不为罕见情况补测试或写防御分支。安全底线保留：只写可写存储根、路径不越界、改名不覆盖、写导航层失败时目录改回暂存位置、等待有上限、子进程和线程要回收。

边界：
- 只改 `src/`、`tests/`。允许改的受保护文件：生成的 `openapi.json`、`schema.d.ts`（只能 `make api-types`）；如需新表，迁移编号 0017，`down_revision` 接 `0016_monitoring`。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`（测试只用临时目录和 `tests/` 里的假导航层）。不安装，不访问网络。
- 只在三种情况停下：要加新依赖；要改允许范围外的受保护文件；要改 M1 写入底座或第 01–04 张的公开契约、`来源.json` 格式。其余自己按最简单安全的方式定，写进最终回复。
- `make check` 不并发跑多份，做完时跑一次。

最终回复第一行写 `状态：全部完成` 或 `状态：未完成`，然后五块：1 改动清单；2 `make check` 末尾输出原样；3 依赖申请；4 自己定的设计选择；5 先红后绿（每个测试一行）。
