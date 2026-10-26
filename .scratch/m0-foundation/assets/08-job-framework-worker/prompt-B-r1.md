评审打回第 1 轮。`make check` 已复跑全绿（pytest 1514、Vitest 201，0 skipped），日志审计干净，变异 9 个抓住 8 个；真实浏览器演示走完了验收 11。下面这些要在本轮改掉，其余没提到的不要动。

动手前先用绝对路径重读 /home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节。用 $tdd：每条先写会失败的测试、单独运行看到红，再改实现。

**缺陷（先红后绿）**

1. 外部工具 stderr 只有空白时，失败被记成程序缺陷。`src/rdp/jobs/_process_io.py:358-370` 的 `tail_text()` 可能返回 `'\n  '` 这类纯空白，放进 `DiagnosticObject(value=...)` 触发 `DiagnosticText` 的非空白约束，抛 pydantic `ValidationError`；作业被记成"执行函数异常"、类别 DEFECT 并写报错表，退出码诊断丢失。`processes.py:237-249` 的退出失败和 `processes.py:202` 的"SIGKILL后进程仍未回收"两条路径都受影响。要求：空白尾部不进诊断对象（或换成固定说明），两条路径都仍以 `ExternalError` 结束，诊断保留退出码。测试用真实工具（如 `printf '\n  \n' >&2; exit 1`）走退出失败路径；回收失败路径可以用现有夹具。
2. 详情页进度百分比没取整，页面显示 `26.666666666666668%`（`src/web/src/jobs/Pages.tsx:409`）。改成整数百分比（或一位小数，二选一，写进 TSDoc），测试断言页面上显示的文字。
3. 作业日志 `<pre role="log">`（`Pages.tsx:287`）不换行，长行把整页撑出横向滚动条。改成在日志框内换行（或框内横向滚动），整页不出现横向滚动。测试断言对应样式。

**测试缺口（变异或评审发现，测试分辨不出对错）**

4. 恢复期间收到取消（`_recovery.py` `_commit` 里 `current.state is CANCELLING` 且 `mode != "cancel"` 那支）要在作业日志追加"恢复期间收到取消请求"那一段。把这个分支改成不写（`if False:`）全部测试仍通过。补一条测试：恢复读到运行中、提交前被改成正在取消，日志里有这一段且作业最终已取消。
5. 验收 4"取消人正确"：`test_cancel_running`（`tests/test_jobs_service.py:179`）提交和取消是同一个管理员。改成由另一个账号取消运行中的作业，断言操作日志的操作人是取消人、不是提交人。
6. 验收 8 的横幅测试（`Pages.test.tsx:451`）只挂了 `/change-password`。至少再在作业页和账号管理页各验证一次横幅出现。

**规范（7.1）**

7. 过程说法：`src/rdp/infra/exception_report.py:21-22` 和 `src/rdp/api/errors.py:231-232` 里"D2 不再替换…""B2：增量收集…"，只写现在的行为。
8. 两个公开函数 docstring 逐字相同（`api/errors.py:221-245` 与 `infra/exception_report.py:11-35`）。`api/errors.py` 的 `format_exception_report` 现在只是转调：调用方不多就直接改用 `rdp.infra.exception_report.format_exception_report` 并删掉转调；要保留就只写一句职责加"契约以 `rdp.infra.exception_report.format_exception_report` 为准"。`exception_report.py` 模块 docstring 补一句来历（第 8 张，jobs 与 api 共用）。这个新公开模块按 6.2 措辞补充级批准，评审会记进工单。
9. 已有常量还写字面量：`Pages.tsx` 的 `COUNT_MESSAGES` 里 10000、60000 改为从 `COUNT_MAX_STEPS`、`COUNT_MAX_INTERVAL_MS` 插值。
10. 运行日志上下文格式（编码规范 6.4 要 key=value）：`execution.py:481,484`、`_loop.py:177,203` 的"作业 %s"。那里 `job_id` 已经由 contextvars 带上的，直接去掉；没带上的改成 `job_id=%s`。

边界和交付同前几轮：
- 只改 `src/`、`tests/`，不动 `pyproject.toml`、依赖和锁文件；改动留在工作区，不 `git add`、不提交。
- 不安装、不联网；不读 `~/桌面/data_check`、`~/桌面/Data_Collection_System-main`，不碰 `/mnt`；不碰真实 `~/.config/rdp`、`~/.local/share/rdp`；自己建的临时文件交付前删掉。
- 每个文件改完只跑相关测试，最后跑一次 `make check`，pytest 和 Vitest 都不留 skipped。
- 只有三种情况停下：要加新依赖；要改允许范围外的受保护文件；要改已获批契约的含义。

最终回复分五块：1 改动清单（每文件一行）；2 `make check` 命令和末尾原样输出，及跑前跑后的 `git status --porcelain --untracked-files=all`；3 契约变更/依赖申请（没有写"无"）和改了哪些 docstring/TSDoc 的哪几句；4 拿不准的地方；5 先红后绿，每条测试第一次运行的结果。
