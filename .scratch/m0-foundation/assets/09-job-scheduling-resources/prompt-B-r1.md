评审打回第 1 轮。`make check` 已复跑全绿（pytest 1667、Vitest 228，0 skipped），日志审计干净；后端变异 11 个全部被抓住；真实 GPU 和浏览器演示走完了验收 9（两卡占满第三个等卡、写锁一个等锁一个持锁、核对不上以冲突失败）。下面这些要在本轮改掉，其余没提到的不要动。

动手前先用绝对路径重读 /home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节。缺陷类每条先写会失败的测试、单独运行看到红，再改实现（$tdd）。

**缺陷（先红后绿）**

1. 跨类型抢卡次序（`scheduling.py` `claim_next`）。一轮扫描里，队首 A（job 5，需卡类型 X）没卡被标等待 GPU 之后，执行线程恰好放出一张卡，后面的队首 C（job 7，另一个需卡类型 Y）在同一轮领到这张卡，越过了等卡的 A，违反本函数 docstring "跨类型抢卡也以此 job_id 顺序，不能……让后提交的 B 越过等卡的 A"。要求：同一轮里一旦有队首因无卡而等待，后面的队首不再领卡（不需卡的类型照常领）。测试用两种需卡测试类型，在 A 判定无卡之后、C 判定之前放卡（注入资源池或钩子，不靠时序碰运气）。
2. 导航写锁释放时的异常来源（`navigation.py` `run` 的两处 `self._finish_release(reporter, sys.exception())` 及 `_finish_release` 里的 `primary or sys.exception()`）。`finally` 里的 `sys.exception()` 在正常返回时取到的是调用方正在处理的无关异常（已实测：调用方在 `except KeyError:` 里调用时返回 `KeyError`），于是写入成功后的释放/持有人清理故障会被吞掉，备注加到无关异常上。要求：用显式捕获（`except BaseException as error: ...; raise`）把本次调用自己的主异常传给收尾，正常返回时为 None；释放故障在正常返回时照常抛出。测试：在 `except` 块里调用 `run`，让持有人清理失败，断言抛出释放故障、外层异常没有被加备注。
3. 恢复候选被取消时写作业日志摘要失败会让整个 worker 停下（`scheduling.py` `_cancel_recovered` 的 `open_job_log`/`write_summary` 异常冒出 `claim_next`）。`execute_job` 对同类日志写失败只记运行日志（`execution.py` 约 334-337 行）。要求两处一致：终态已提交后日志摘要写失败只记一次 ERROR（key=value 带 job_id），不停实例。测试注入日志写失败，断言作业已取消、worker 继续领取下一个作业。

**规范（7.1）**

4. 过程说法：`src/rdp/audit/_validation.py:62` 和 `src/rdp/jobs/worker.py:238` 的"待实现：……"注释（对应功能已实现），删掉或改成只写现在的行为；`src/web/src/scheduling/Pages.tsx:1`、`scheduling/queries.ts:1`、`api/scheduling.ts:1` 的"（09）"去掉。
5. 已有常量还写字面量：`scheduling/Pages.tsx` 的"占用秒数须为0至600的整数""暂停须为0至10的整数秒""期望值最多256个字符"改为从 `GPU_HOLD_MAX_S`、`NAVIGATION_PAUSE_MAX_S`、`EXPECTED_VALUE_MAX_CHARS` 插值。
6. 重复字面量写成具名常量：作业类型键 `"purge_errors"`、`"purge_audit_logs"`、`"example_gpu"`、`"example_navigation"` 及显示名"清除过期报错""清除过期日志"在 `registry.py`、`schedules.py`、`execution.py`、`maintenance.py`、`api/jobs.py` 多处重复。在定义处（登记模块或其类型模块）各定义一次常量，其他地方引用；`schedules.py:318` 和 `execution.py:417` 的同一个清除类型集合也只定义一次。不新增公开模块；不改测试里作为输入数据的字面量。
7. 类型键正则第三份：`infra/config.py:112` 新写的 `r"[a-z][a-z0-9_]{0,63}"` 与 `jobs/registry.py`、`audit/job_contracts.py` 已有的同一模式重复。在 infra 层定义一个具名常量（或校验函数），config 使用它；registry、job_contracts 若依赖方向允许（import-linter 通过）也改为引用，不允许就保持原样并在第 4 块说明。
8. 运行日志上下文 key=value（编码规范 6.4）：`src/rdp/ops/worker.py:148` 改为 `gpu_index=%d`；`src/rdp/jobs/_loop.py:210` 的"已等 %.3f 秒"改为 `elapsed_s=%.3f`。

边界和交付同前几轮：
- 只改 `src/`、`tests/`，不动 `pyproject.toml`、依赖和锁文件；改动留在工作区，不 `git add`、不提交。
- 不安装、不联网；不读 `~/桌面/data_check`、`~/桌面/Data_Collection_System-main`，不碰 `/mnt`；测试不调用真实 `nvidia-smi`，不碰真实 `~/.config/rdp`、`~/.local/share/rdp`；自己建的临时文件交付前删掉。
- 每个文件改完只跑相关测试，最后跑一次 `make check`，pytest 和 Vitest 都不留 skipped。60 分钟内交付。
- 只有三种情况停下：要加新依赖；要改允许范围外的受保护文件；要改已获批契约的含义。

最终回复分五块：1 改动清单（每文件一行）；2 `make check` 命令和末尾原样输出，及跑前跑后的 `git status --porcelain --untracked-files=all`；3 契约变更/依赖申请（没有写"无"）和改了哪些 docstring/TSDoc 的哪几句；4 拿不准的地方；5 先红后绿，每条测试第一次运行的结果。
