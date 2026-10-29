"""变更记录与撤回的契约测试清单（M1-07，L15、L16，验收 3）。

骨架阶段全部跳过。场景三用可控时钟让操作日志过期被清除，nav-changes 不受影响。
"""

import pytest


def test_archive_committed_record_contents() -> None:
    """L16：COMMITTED 记录含计划、每步前像和后像、提交人、起止时刻、受影响数据集。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_archive_inline_threshold_boundary() -> None:
    """Comments (9)：文件正好 CHANGE_INLINE_MAX_BYTES 时存全文，多 1 字节时只存 sha256 和大小。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_archive_large_file_goes_to_sidecar_blob() -> None:
    """待确认扩展：超限文件的正文放进旁路 blob（按 sha256 命名的 .gz），记录里有 blob 引用。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_archive_requires_plan_for_committed() -> None:
    """契约 archive_journal：outcome 为 COMMITTED 却没给 plan 时报 InputError。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_archive_is_idempotent() -> None:
    """契约 archive_journal：同一作业重复归档写入相同内容，已有记录不被破坏。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_archive_failure_keeps_existing_record() -> None:
    """契约 archive_journal：写入、fsync 或 rename 失败时已有的同名记录不被破坏。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_archive_rolled_back_outcomes_have_no_after_images() -> None:
    """Comments (3)：rolled_back、rolled_back_by_recovery 的记录没有后像，且不能被撤回。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_failed_and_rolled_back_jobs_also_get_records() -> None:
    """Comments 更正：失败和回滚的作业也要写变更记录，以 L16 为准。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_read_change_record_roundtrip() -> None:
    """契约 read_change_record：写出再读回得到相同的 ChangeRecord。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_read_change_record_missing_or_unknown_version() -> None:
    """契约 read_change_record：记录不存在、损坏或 format_version 不认识时报 InputError。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_plan_revert_inverts_steps_in_reverse_order() -> None:
    """L16 验收：反向计划是原步骤逆序反演，write_file 写回前像全文，set_link 改回前像目标。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_plan_revert_of_created_objects_removes_them() -> None:
    """L16：撤回新建类操作时，新建的文件、链接、空目录用 remove_path 删掉，目录在最后。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_plan_revert_requires_current_state_equals_after_images() -> None:
    """L16：当前状态等于 #N 的后像才生成反向计划。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_plan_revert_conflict_lists_differences() -> None:
    """L16 验收：中间又被改过时以冲突失败，列出每一处差异（路径、预期、实际、之后改过它的作业）。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_plan_revert_rejects_non_committed_record() -> None:
    """契约 plan_revert：结局不是 COMMITTED 时报 InputError。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_plan_revert_missing_blob_is_input_error() -> None:
    """契约 plan_revert：前像正文既没内联也找不到旁路 blob 时报 InputError，不生成残缺计划。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_revert_is_itself_a_write_job_with_own_record() -> None:
    """L16：撤回本身也是写导航层的作业，有自己的写入日志和变更记录，reverts_job_id 指向 #N。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_revert_after_audit_log_purged_still_works() -> None:
    """验收 3（场景三）：可控时钟走过 30 天、操作日志被清除后，nav-changes 还在，撤回作业照常预览、执行成功。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_revert_conflicts_when_changed_between_preview_and_apply() -> None:
    """L16、L12：撤回预览之后现状又变，写入作业在写锁下核对时以冲突失败，一行都没写。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_diff_against_after_images_names_later_job() -> None:
    """契约 diff_against_after_images：能从更晚的变更记录查到改过它的作业编号时填 changed_by_job_id。"""
    pytest.skip("M1-07：该契约尚未实现")
