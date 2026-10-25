上一次运行（派工 B）在 60 分钟时被超时中止，当时你已经去掉了全部跳过、正在跑最后的 `make fmt && make check`，最终回复没有写出来。工作区保留着你那时的改动，执行线在这个状态上做完了评审：`make check` 全绿，契约对比通过，违规试验通过。

评审发现下面的问题，逐条修复，别处不动。第 9–12 条只改写法、不改行为；第 11 条的 TSDoc 措辞变更已由执行线批准，其余已获批的签名、类型和 docstring 不改。要改别的契约时停下，写契约变更申请。

改测试的条目照 TDD：先让新测试或加强后的断言在当前实现上跑一次（单独运行），能红的看到它红；当前实现本来就对、所以一开始就绿的，在最终回复里说明。

1. `test_backup_filename` 传 +08:00 和 −06:00 的时刻，断言文件名里是换算后的 UTC；再造"同一时刻、同一 revision"的两次备份，断言文件名不同、两个文件都在。（`tests/test_db_migration.py`）
2. `test_backup_foreign` 先放至少 6 份平台命名的备份，加上人工文件、软链接和 `.partial`，跑 `migrate`；断言只删掉最旧的平台备份，其余原样。
3. `test_read_exception` 的写入用 `pytest.raises` 直接断言失败（只读会话写入必须失败），不要放在 `except` 分支里。
4. `test_report_nondefect` 照 docstring 覆盖输入（400、404）、冲突、外部失败、参数校验和"没有引擎"几种，都走真实应用；断言表里没有行，日志里也没有"完整报错持久化失败"。删掉 `report or ""` 的兜底，缺陷路径的报告不能是空的。
5. `test_configure_version` 经 `create_app(..., database=engine)` 覆盖缺失、没有版本表、落后、领先或未知四种，每种都断言 `InputError` 和"先运行 migrate"。
6. `test_process_success` 让两个写事务真正重叠：一个子进程持有写事务，另一个开始等锁，在 5 秒内放开；断言两个都成功、第二个确实等过（用 monotonic 量）。
7. B2 端到端：报告超过上限时，日志里的报告段和表里的 `report` 逐字相同，都以截断标记结尾，长度不超过上限；`tests/test_api_database.py` 的 `test_report_bound` 照 docstring 测 N−1、N、N+1 三档。
8. 加一个测试：迁移后的 `error_reports` 建表 SQL（`sqlite_master.sql`）和用模型 `MetaData` 在另一个空库里建出来的一致（规范化空白后比较），这样模型和迁移里两份 CHECK 漂移能被发现。
9. 常量：诊断文案里的"5000 毫秒"用 `BUSY_TIMEOUT_MS`；`ERROR_PERSIST_TIMEOUT_S` 由 `BUSY_TIMEOUT_MS` 加 1 秒余量算出；`records.py` 的"1 至 3650"用 `MAX_RETENTION_DAYS`；2^63−1 在 Python、TS 各定义一个具名常量，注明"SQLite 有符号 64 位整数上限"。值都不变。
10. 备份用的两个 `sqlite3.connect` 传 `timeout=BUSY_TIMEOUT_MS / 1000`。
11. 前端：`fetchQuery` 换成 `queryClient.query(options)`，删掉 `no-deprecated` 的豁免，TSDoc 里的方法名跟着改（语义不变，措辞变更，执行线批准）；参数名去掉 `_` 前缀（`@param` 跟着改）；`boundedText` 的计数写清楚。
12. 去重：`rdp.api` 不 import 私有的 `_validation`，改成公开模块或从包里导出；"只读会话写入 → DefectError（带诊断）"只留一处实现，`records.py` 那处不能抛不带诊断的 `DefectError()`；备份文件名的 UTC 格式化复用 `utc.py` 的写法；`test_db_migration.py` 复用 `_reap`；Python 侧的编号格式只留一处（迁移脚本里冻结的 CHECK 和前端那份除外）。
13. 补交 B 因超时没写出来的最终回复（五块），第 5 块"先红后绿"要逐个说明一开始就通过的测试为什么通过；可以按文件分组写，但每个测试都要点到。

为了不再超时：每条改完先只跑相关的测试文件，最后只跑一次 `make check`。不要用 `make fmt` 改动本票以外的文件。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只允许加 `[tool.alembic]` 或 Alembic 需要的配置；依赖表不动，别的段不动。这一轮应当不需要）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。测试只用 `tmp_path`，不碰真实的 `~/.config/rdp`、`~/.local/share/rdp`，不写 `.git/info/exclude`。

最终回复：
1. 逐条写处理结果（第 1–13 条）。
2. `make check` 最后一次运行的命令和末尾输出，原样贴出（pytest 和 Vitest 两步要能看出 passed 和 skipped 的数目）；再原样贴出跑之前和跑之后的 `git status --porcelain --untracked-files=all`。
3. 契约变更申请、依赖申请：没有就写"无"。另外列出这一轮改了哪些 docstring/TSDoc 的哪几句。
4. 拿不准、需要评审决定的地方（没有就写"无"）。
5. 先红后绿：本轮新增或加强的测试每个一行；再补上派工 B 的全部新测试，每个一行，写它第一次运行的结果（失败的原因，或者为什么一开始就通过）。
