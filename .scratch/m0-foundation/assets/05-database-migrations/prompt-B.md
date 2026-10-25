骨架已获批，契约提交是 `d36a888`（`契约：数据库与迁移`），内容就是你派工 A 交的骨架。工作目录现在是干净的。

动手前先用绝对路径重读主仓库目录里的工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/05-database-migrations.md，Comments 的最后三条是骨架评审意见、关卡摘要和负责人的决定（B1–B3）。

现在按测试清单逐个函数实现，用 $tdd 和 $enterprise-coding：
1. 每次去掉一个测试的跳过，先单独运行它（Python 用 `.venv/bin/pytest tests/<文件>::<测试名>`，前端在 `src/web/` 里用 `node_modules/.bin/vitest run <文件> -t "<标题>"`），看到它失败，再写实现让它通过。评审会在运行日志里逐个核对每个测试都有一次实现前的失败运行。去掉跳过就直接通过的测试，在最终回复里逐个列出并说明原因（例如前一个测试的实现已经覆盖了它）。
2. 已获批的签名、类型和 docstring 不改，下面"已获批的契约变更"和"评审意见"列的几处除外。还有别的地方确实要改时停下，在最终回复里写契约变更申请：哪个函数、改什么、为什么。
3. 最后 `make check` 全绿，测试里不留骨架阶段的跳过（pytest 和 Vitest 都没有 skipped）。

已获批的契约变更（负责人在骨架关卡批准；先改测试、后改实现）：
- **B1 `create_app` 的 `database` 去掉默认值**：签名改成 `create_app(web_dist: Path | None, *, database: Engine | None) -> FastAPI`，仅限关键字、必须写明。`None` 的含义照骨架（只用于导出接口文档和不需要数据库的测试；报错只写日志；查报错接口返回带诊断的 502）。
  - 所有现有调用处改成显式传参：`src/rdp/api/openapi_export.py` 写 `database=None`；`tests/` 下所有 `create_app(None)`、`create_app(tmp_path)` 一类的调用（包括 `tests/diagnostics_demo.py` 的 docstring 和调用）写 `database=None`，需要数据库的测试传临时库的引擎。`git grep -n 'create_app('` 交付前确认没有漏掉的。
  - 改 `create_app` 的 `Args:`，删掉"默认 None"的说法；补一个测试：不传 `database` 时是 `TypeError`（签名层面拒绝）。
- **B2 完整报错上限**：照骨架里的提案做，`MAX_EXCEPTION_REPORT_CHARS = 262144`，超出截掉后面，尾部加 `REPORT_TRUNCATION_MARKER`，总长度不超过上限；日志和报错表存同一次格式化的结果。`format_exception_report` 的 docstring 去掉"提案""骨架不改现有函数体"一类字样，写成现在的行为。
- **B3**：`migrate` 不检查 Web、worker 是否在跑，契约不变（docstring 里"运维调用前必须停止 Web/worker"保留）。

评审意见（不改含义，照做）：
- 删掉 5 条骨架期的 `eslint-disable-next-line @typescript-eslint/no-unused-vars`（`src/web/src/api/errorDetails.ts`）。
- `get_session`、`get_read_session` 实现成 `yield` 以后，docstring 的 `Returns:` 改成 `Yields:`，删掉"骨架函数体只有 raise……"那句；迭代值语义不变。
- 删掉所有骨架期、提案期的说法，只写现在的行为：`create_app`（"工单 05 提案""骨架阶段仅登记路由/模型……"）、`handle_error`、`ErrorBoundary.__call__`、`format_exception_report`、`HealthPage` 的 TSDoc（"骨架阶段保留现有函数体……"）、`env.py` 模块注释（"骨架阶段不在导入时调度入口"），以及 `src/web/src/HealthPage.test.tsx`、`errorDetails.test.ts` 里"骨架"一类注释。交付前在本票改过的文件里搜"提案""骨架""派工"，不留。
- `env.py` 要在 Alembic 加载它时真正调用 `run_migrations()`（Alembic 是通过执行 `env.py` 跑迁移的），同时保证测试里单独 import 它不会触发迁移，办法你定，写进第 4 块。
- 版本不对抛输入或数据问题（不是冲突），按骨架。
- 首个迁移冻结列和约束，不调用 `Base.metadata.create_all`；`test_compare_metadata` 要真的用 Alembic 的 `compare_metadata` 比出空差异。
- 两进程、并发 `migrate`、报错持久化超时这类测试：所有等待都有上限，子进程和线程在 `finally` 里回收；测试结束后恢复全局 logging 状态；测试不依赖本机时区（−06:00），不改进程的全局时区。
- 前端 `HealthPage` 用 `createErrorDetailsLoader` 把查报错接到 `DiagnosticCard.loadDetails`。
- 演示由执行线在沙箱外做（临时状态目录里 `migrate`、起应用、截真实页面），你不用起服务器，也不要建真实的状态目录。
- 如果 OpenAPI 有变化，用 `make api-types` 重新生成，不手改生成文件。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只允许加 `[tool.alembic]` 或 Alembic 需要的配置；依赖表不动，别的段不动。派工 A 没有加，B 里应当也不需要）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。测试只用 `tmp_path`，不碰真实的 `~/.config/rdp`、`~/.local/share/rdp`，不写 `.git/info/exclude`。

最终回复分五块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出（pytest 和 Vitest 那两步要能看出 passed 和 skipped 的数目，应当没有 skipped）。再原样贴出跑之前和跑之后的 `git status --porcelain --untracked-files=all`。
3. 契约变更申请、依赖申请：没有就写"无"。另外逐条列出你按 B1、B2 和评审意见改了哪些 docstring/TSDoc 的哪几句。
4. 拿不准、需要评审决定的地方（没有就写"无"）。
5. 先红后绿：每个测试一行，写它第一次运行的结果（失败的原因，或者为什么一开始就通过）。
