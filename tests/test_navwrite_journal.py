"""写入日志的契约测试清单（M1-07，L13）：nav-journal 的磁盘格式。

骨架阶段全部跳过。
"""

import pytest


def test_write_journal_layout_and_fsync_order() -> None:
    """L13：write_journal 先写 images/*.before，再写 journal.json.tmp 并 rename 成 journal.json；journal.json 一出现就是完整的。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_journal_records_before_images_and_after_hashes() -> None:
    """L13：日志里每步有路径、前像、后像哈希；不抄后像正文；前像存在的 write_file 有 before_blob。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_write_journal_rejects_missing_or_wrong_before_images() -> None:
    """契约 write_journal：before_images 缺项、多项或哈希与计划不符时报 InputError，且不留日志目录。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_write_journal_refuses_existing_directory() -> None:
    """契约 write_journal：同一作业编号的日志目录已存在时报 ConflictError。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_write_journal_failure_leaves_nothing() -> None:
    """契约 write_journal：写入或 rename 失败时整个日志目录被清掉，导航层未动。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_incomplete_journal_means_navigation_untouched() -> None:
    """L13：只有 journal.json.tmp 或空目录时，list_journals 标 complete=False。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_read_journal_rejects_unknown_version_and_corruption() -> None:
    """契约 read_journal：缺 journal.json、坏 JSON、未知 format_version 报 InputError。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_read_before_image_detects_corruption() -> None:
    """契约 read_before_image：读到的字节哈希与日志记的不符时报 InputError。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_list_journals_sorted_and_ignores_foreign_names() -> None:
    """契约 list_journals：按作业编号升序；名字不是正整数的子目录被忽略但不删除；目录不存在返回空元组。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_discard_journal_is_idempotent_and_ordered() -> None:
    """契约 discard_journal：目录不存在视为完成；先删 journal.json 再删其余，半删状态读作日志不完整。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_discard_journal_refuses_foreign_directory() -> None:
    """契约 discard_journal：目录不在 nav-journal 之下时报 InputError，不删除。"""
    pytest.skip("M1-07：该契约尚未实现")
