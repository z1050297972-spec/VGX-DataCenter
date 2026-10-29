"""全局标记「导航层恢复失败」的契约测试清单（M1-07，ADR 0005 修订）。

骨架阶段全部跳过。用真实 SQLite 临时库；表由 pending 迁移 v0010 创建，实现阶段先把迁移移入 versions。
"""

import pytest


def test_read_block_none_when_absent() -> None:
    """契约 read_recovery_block：没有标记行时返回 None，is_navigation_write_blocked 为 False。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_record_block_creates_single_row() -> None:
    """契约 record_recovery_block：首次设置建一行，set_at 取注入的时刻。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_record_block_merges_and_keeps_first_set_at() -> None:
    """契约 record_recovery_block：再次设置时 job_ids 取并集、items 去重，set_at 不变。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_record_block_caps_items_but_keeps_total() -> None:
    """规范 6.6：items 至多 MARKER_ITEM_SAMPLE_LIMIT 条，total_items 完整。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_record_block_rejects_empty_items() -> None:
    """契约 record_recovery_block：items 为空报 InputError。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_block_row_is_singleton_by_check() -> None:
    """迁移 v0010：singleton_id 只能为 1，第二行被 CHECK 拒绝。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_acknowledge_requires_existing_block() -> None:
    """契约 acknowledge_recovery_block：没有标记时报 ConflictError。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_acknowledge_requires_account_admin() -> None:
    """契约 acknowledge_recovery_block：actor.account_id 为 None（运维）时报 InputError。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_acknowledge_archives_deletes_journal_then_clears_marker() -> None:
    """Comments (5)：确认时先归档日志（manually_confirmed，带仍对不上的项）、删日志，最后清标记，顺序可断言。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_acknowledge_appends_audit() -> None:
    """Comments (5)：确认追加一条 confirm_navigation_recovery 操作日志，操作人是管理员账号。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_acknowledge_crash_before_clearing_keeps_block() -> None:
    """契约 acknowledge_recovery_block：崩在清标记之前，标记保留、写操作继续被挡住；再确认一次幂等。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_acknowledge_unblocks_next_poll() -> None:
    """验收（演示）：确认以后下一轮领取即放行排队的写作业，不需要重启 worker。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_marker_module_does_not_import_writer_modules() -> None:
    """规范 1.4：marker 模块不 import atomic、recovery、pipeline、jobs，Web 可以依赖它。"""
    pytest.skip("M1-07：该契约尚未实现")
