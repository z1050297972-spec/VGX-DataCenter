"""原子写与回滚的契约测试清单（M1-07，L13、L14、验收 5）。

骨架阶段全部跳过。失败注入用对 os.replace、os.symlink、os.fsync 的 monkeypatch，在每一步之前和之后各注入一次。
"""

import pytest


def test_apply_write_file_is_atomic_replace() -> None:
    """L13：write_file 先写同目录临时文件、fsync，再 os.replace；中途失败时原文件字节不变。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_apply_set_link_creates_via_temp_name() -> None:
    """L13：set_link 先建到临时名再 rename 盖过去，期间原链接始终可读。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_apply_make_dir_and_move_path() -> None:
    """契约 apply_plan：make_dir 要求父目录已存在；move_path 同文件系统改名。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_apply_remove_path_checks_before_image() -> None:
    """契约 apply_plan：remove_path 先核对前像，目录必须已空。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_apply_rejects_paths_escaping_nav_root() -> None:
    """契约 apply_plan：步骤路径逃逸 nav_root 或经过软链接时报 InputError，且什么都没写。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_apply_failure_at_every_step_rolls_back_to_before() -> None:
    """L13 验收：对一份多步计划在每一步注入失败，rollback_journal 之后所有文件和链接都等于前像。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_apply_failure_leaves_only_recognizable_temp_files() -> None:
    """规范 2.6：失败只留下按命名认得出的临时文件，rollback_journal 把它们清掉。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_capture_before_images_conflicts_on_changed_file() -> None:
    """契约 capture_before_images：文件现在的哈希与计划前像不同时报 ConflictError，一行都没写。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_observe_step_classifies_before_after_neither() -> None:
    """L14：observe_step 对每种步骤判出 BEFORE、AFTER、NEITHER；前后像相同的步骤读作 BEFORE。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_rollback_restores_steps_in_reverse_order() -> None:
    """L13：rollback_journal 按序号从大到小退回，restored_steps 的顺序可断言。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_rollback_leaves_steps_already_at_before() -> None:
    """L14：等于前像的步骤不动，记进 untouched_steps。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_rollback_lists_neither_and_restores_the_rest() -> None:
    """L14 与 Comments (4)：有两者都不是的项时，能退回的照样退回，退不回的列进 mismatches，不中止后面的步骤。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_rollback_restore_failure_is_reported_not_raised() -> None:
    """Comments (6)：单步退回动作失败记进 failed_steps 和 mismatches，不抛。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_rollback_is_idempotent() -> None:
    """契约 rollback_journal：对已回滚的日志再回滚，结果全部为 untouched。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_rollback_rejects_other_nav_root() -> None:
    """契约 rollback_journal：nav_root 与日志不同时报 InputError，不对错误的树做回滚。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_rollback_make_dir_only_when_empty() -> None:
    """契约 rollback_journal：make_dir 退回时目录非空则不删，并作为对不上的项列出。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_writes_only_nav_root_and_state_dir() -> None:
    """验收 5：把假存储根设成只读，写作业照常成功，存储根里没有任何变化；写入只发生在 nav_root 和状态目录。"""
    pytest.skip("M1-07：该契约尚未实现")
