"""中断恢复与恢复失败标记的契约测试清单（M1-07，L14，验收 1 的恢复部分、验收 4）。

骨架阶段全部跳过。用假导航层和临时状态目录，不起真实 worker；SIGKILL 演练由 Claude 在副本上做。
"""

import pytest


def test_recovery_state_equals_after_is_restored() -> None:
    """L14 样一：磁盘等于后像的项退回前像。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_recovery_state_equals_before_is_untouched() -> None:
    """L14 样二：磁盘等于前像的项不动。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_recovery_neither_stops_and_lists() -> None:
    """L14 样三：两者都不是的项不动，列出，作业标恢复失败（设标记）。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_recovery_incomplete_journal_is_discarded() -> None:
    """L13：没有 journal.json 的日志目录说明导航层没动，直接删除，fate 为 INCOMPLETE_DISCARDED。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_recovery_committed_record_with_leftover_journal_is_not_rolled_back() -> None:
    """契约 recover_journal：日志与 outcome 为 committed 的变更记录并存时只删日志，不回滚（写完了，崩在删日志之前）。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_recovery_archives_then_deletes_journal() -> None:
    """Comments (3)：回滚完成后，先归档进变更记录（rolled_back_by_recovery），再删日志，顺序可断言。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_recovery_failure_keeps_journal_for_admin() -> None:
    """Comments (4)：MISMATCH 时日志保留，供管理员核对。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_recovery_is_idempotent_after_crash_at_any_step() -> None:
    """契约 recover_journal：在回滚中途再次崩溃后重新运行，结论相同。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_recovery_runs_before_any_write_job_claim() -> None:
    """验收 4：恢复流程跑完以前，别的写作业不开始；用 ExecutorDependencies.recover_navigation 的调用顺序断言。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_recovery_failure_marker_survives_worker_restart() -> None:
    """ADR 0005 修订：重启 worker 不清除标记，写作业继续被挡住。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_blocked_write_jobs_stay_queued_others_run() -> None:
    """Comments (1)、(7)：标记在时 writes_navigation 的作业留在排队中，其他类型（含重新扫描）照常运行。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_recovery_failure_job_stays_interrupted() -> None:
    """Comments (1)：作业状态仍是已中断，没有新增状态，也没有作业结果。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_recovery_appends_audit_per_journal() -> None:
    """L15：每份日志追加一条 rollback_navigation_write 操作日志，系统身份，失败的带 conflict 类别。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_recovery_rejects_journal_for_other_nav_root() -> None:
    """契约 recover_navigation_writes：日志的 nav_root 与当前配置不同时报 InputError，不回滚。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_recovery_corrupt_journal_is_mismatch_not_crash() -> None:
    """契约 recover_navigation_writes：journal.json 损坏时按 MISMATCH 保留，不抛，不删。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_recovery_merges_new_items_into_existing_marker() -> None:
    """契约 recover_navigation_writes：已有标记时仍处理新日志，对不上的并入标记，不清除。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_recovery_with_no_journals() -> None:
    """契约 recover_navigation_writes：没有日志时 journals 为空，blocked 取决于是否已有标记。"""
    pytest.skip("M1-07：该契约尚未实现")
