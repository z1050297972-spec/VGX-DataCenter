上一轮（r1）的 13 条已全部落实，执行线评审通过了 `make check`、契约对比、变异抽查和违规试验。两轴评审还剩下面 3 处，逐条修复，别处不动。这是最后一轮。

1. **只读写入的诊断要如实**（CODING_STANDARDS 6.1）。`src/rdp/infra/db/_errors.py` 的 `readonly_write_error` 现在调 `database_problem(DefectError, database, "只读会话写入", 0)`，诊断里显示"安全错误码=0"，规则借用了通用的"存储及结构约束"文案。改成：诊断里带真实的 `sqlite3.SQLITE_READONLY` 错误码，规则如实写"只读会话不得写入"。顺手把同一行的 `cast` 去掉（用重载或让 `database_problem` 的返回类型跟着传入的类走）。`connection.py` 里路径非法那处同样借用了 `database_problem(..., 0)`，docstring 说诊断带"路径规则"：让实际诊断和 docstring 一致（写路径规则，不写"错误码=0"）。在 `tests/test_db_records.py::test_readonly_write_diagnostic` 和对应的路径测试里加断言：诊断里有真实错误码或路径规则，没有"错误码=0"。先单独跑一次看它红。
2. **不用四类以外的异常**（CODING_STANDARDS 6.2）。`src/rdp/api/errors.py` 里：
   - `if not report: raise RuntimeError("程序缺陷报告不能为空")` 这一支删掉。`_logged_report` 的返回值按类型就不会为空的话，直接删；做不到，就改成带诊断的 `DefectError`，并补一个测试走到它。
   - `if request_id_context.get() != problem.error_id: raise DefectError()` 改成带诊断的 `DefectError`（说清是哪两个编号对不上），补一个测试断言诊断内容。
3. **docstring 和注释不写死数值**：`connection.py` 第 58、218、230 行附近和 `migration.py` 第 235 行附近 docstring 里的"5000 毫秒"改成"`BUSY_TIMEOUT_MS`（5000 毫秒）"这种同时点出常量名的写法；`errors.py` 第 464 行附近注释里的"5 秒"同样处理。只改措辞、不改含义，执行线批准。

改测试的条目照 TDD：新断言先在当前实现上单独跑一次，能红的看到它红。每条改完只跑相关测试文件，最后只跑一次 `make check`。不要用 `make fmt` 改动本票以外的文件。

边界：
- 只改 `src/`、`tests/`；不动受保护文件。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`，不读执行线的临时目录。
- 不安装任何东西，不访问网络。需要新依赖时停下，写依赖申请。
- 自己建的试验文件交付前删掉。测试只用 `tmp_path`。

最终回复：
1. 逐条写处理结果（第 1–3 条）。
2. `make check` 最后一次运行的命令和末尾输出原样贴出（pytest、Vitest 的 passed、skipped 数目要看得出）；再贴跑之前和跑之后的 `git status --porcelain --untracked-files=all`。
3. 契约变更申请、依赖申请：没有就写"无"。列出这一轮改了哪些 docstring 的哪几句。
4. 拿不准、需要评审决定的地方（没有就写"无"）。
5. 先红后绿：本轮新增或加强的测试每个一行，写第一次单独运行的结果。
