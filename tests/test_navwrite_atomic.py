"""原子写与回滚的契约测试（M1-07，L13、L14、验收 5）。

失败注入用对 os.replace、os.symlink、os.mkdir、os.fsync 的 monkeypatch，在每一次变更调用处各注入一次。
所有写入只发生在 pytest 临时目录里的 nav_root 和状态目录；kill -9 的测试用子进程，有超时，结束时回收进程。
"""

import fnmatch
import os
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from nav_manifest import FakeNavigation
from navwrite_support import (
    file_image,
    noop,
    plan_for,
    sha,
    simple_nav,
    tree_state,
    write_step,
)

from rdp.infra.config import PlatformConfig
from rdp.infra.diagnostics import ConflictError, ExternalError, InputError
from rdp.infra.state import StatePaths, initialize_state, state_paths
from rdp.jobs.navwrite.atomic import (
    StepDisk,
    apply_plan,
    capture_before_images,
    observe_step,
    rollback_journal,
)
from rdp.jobs.navwrite.journal import Journal, journal_directory, write_journal
from rdp.jobs.navwrite.models import (
    MakeDirStep,
    MovePathStep,
    NavWritePlan,
    RemovePathStep,
    SetLinkStep,
    Step,
)

NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)
JOB = 7


def _case(tmp_path: Path) -> tuple[StatePaths, Path, NavWritePlan]:
    """状态目录、导航树和多步计划。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ())
    initialize_state(paths)
    nav, steps = simple_nav(tmp_path)
    return paths, nav, plan_for(nav, steps)


def _journal(paths: StatePaths, nav: Path, plan: NavWritePlan) -> tuple[Journal, Path]:
    """核对前像并落日志，等同于流水线在写入前做的两步。"""
    images = capture_before_images(nav, plan)
    return write_journal(paths, plan, images, JOB, NOW), journal_directory(paths, JOB)


def _temp_files(nav: Path) -> list[str]:
    """导航树里按命名认得出的临时文件。"""
    return [
        str(p.relative_to(nav)) for p in nav.rglob("*") if fnmatch.fnmatch(p.name, ".*.rdp-*.tmp")
    ]


def test_apply_write_file_is_atomic_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L13：write_file 先写同目录临时文件、fsync，再 os.replace；中途失败时原文件字节不变。"""
    nav = tmp_path / "nav"
    nav.mkdir()
    (nav / "a.json").write_bytes(b"old\n")
    plan = plan_for(nav, (write_step("a.json", b"old\n", b"new\n"),))
    events: list[str] = []
    real_replace, real_fsync = os.replace, os.fsync

    def replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        events.append("replace")
        source_path = Path(source)
        # 临时文件与目标同目录，名字可识别，内容已是新内容，原文件此刻仍是旧内容。
        assert source_path.parent == Path(target).parent
        assert fnmatch.fnmatch(source_path.name, ".a.json.rdp-7-0.tmp")
        assert source_path.read_bytes() == b"new\n" and (nav / "a.json").read_bytes() == b"old\n"
        real_replace(source, target)

    def fsync(descriptor: int) -> None:
        events.append("fsync")
        real_fsync(descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", replace)
        patch.setattr(os, "fsync", fsync)
        apply_plan(nav, plan, JOB, checkpoint=noop)
    assert events.index("replace") > events.index("fsync")  # 先 fsync 再 rename
    assert (nav / "a.json").read_bytes() == b"new\n" and _temp_files(nav) == []
    # 中途失败：rename 抛错，原文件字节不变。
    (nav / "a.json").write_bytes(b"old\n")

    def broken(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        raise OSError("注入失败")

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", broken)
        with pytest.raises(ExternalError):
            apply_plan(nav, plan, JOB, checkpoint=noop)
    assert (nav / "a.json").read_bytes() == b"old\n"


def test_apply_set_link_creates_via_temp_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L13：set_link 先建到临时名再 rename 盖过去，期间原链接始终可读。"""
    nav = tmp_path / "nav"
    nav.mkdir()
    (nav / "L").symlink_to("/old-target")
    plan = plan_for(nav, (SetLinkStep(path="L", before_target="/old-target", after_target="/new"),))
    seen: list[str] = []
    real_replace = os.replace

    def replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        seen.append(str(Path(source).readlink()))
        assert str(Path(nav / "L").readlink()) == "/old-target"  # 盖过去之前原链接不动
        real_replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", replace)
        apply_plan(nav, plan, JOB, checkpoint=noop)
    assert seen == ["/new"] and str(Path(nav / "L").readlink()) == "/new" and _temp_files(nav) == []
    # 原来不存在的链接同样建到临时名再 rename。
    fresh = plan_for(nav, (SetLinkStep(path="M", before_target=None, after_target="/m"),))
    apply_plan(nav, fresh, JOB, checkpoint=noop)
    assert str(Path(nav / "M").readlink()) == "/m"


def test_apply_make_dir_and_move_path(tmp_path: Path) -> None:
    """契约 apply_plan：make_dir 要求父目录已存在；move_path 同文件系统改名。"""
    nav = tmp_path / "nav"
    (nav / "src").mkdir(parents=True)
    (nav / "src" / "x.json").write_text("x", encoding="utf-8")
    apply_plan(nav, plan_for(nav, (MakeDirStep(path="d"),)), JOB, checkpoint=noop)
    assert (nav / "d").is_dir()
    with pytest.raises(ExternalError):
        apply_plan(nav, plan_for(nav, (MakeDirStep(path="缺/子目录"),)), JOB, checkpoint=noop)
    assert not (nav / "缺").exists()
    move = MovePathStep(path="src", to_path="d/moved", entry_kind="directory")
    apply_plan(nav, plan_for(nav, (move,)), JOB, checkpoint=noop)
    assert not (nav / "src").exists() and (nav / "d" / "moved" / "x.json").read_text() == "x"
    (nav / "occupied").mkdir()
    again = MovePathStep(path="d/moved", to_path="occupied", entry_kind="directory")
    with pytest.raises(ExternalError):
        apply_plan(nav, plan_for(nav, (again,)), JOB, checkpoint=noop)
    assert (nav / "d" / "moved").is_dir()  # 目标已存在时不覆盖


def test_apply_remove_path_checks_before_image(tmp_path: Path) -> None:
    """契约 apply_plan：remove_path 先核对前像，目录必须已空。"""
    nav = tmp_path / "nav"
    nav.mkdir()
    (nav / "f.json").write_bytes(b"content\n")
    (nav / "L").symlink_to("/t")
    (nav / "full").mkdir()
    (nav / "full" / "x").write_text("x", encoding="utf-8")
    wrong = RemovePathStep(path="f.json", entry_kind="file", before_file=file_image(b"other\n"))
    with pytest.raises(ConflictError):
        apply_plan(nav, plan_for(nav, (wrong,)), JOB, checkpoint=noop)
    assert (nav / "f.json").exists()
    wrong_link = RemovePathStep(path="L", entry_kind="symlink", before_target="/别的")
    with pytest.raises(ConflictError):
        apply_plan(nav, plan_for(nav, (wrong_link,)), JOB, checkpoint=noop)
    not_empty = RemovePathStep(path="full", entry_kind="directory")
    with pytest.raises(ExternalError):
        apply_plan(nav, plan_for(nav, (not_empty,)), JOB, checkpoint=noop)
    assert (nav / "full" / "x").exists()
    good: tuple[Step, ...] = (
        RemovePathStep(path="f.json", entry_kind="file", before_file=file_image(b"content\n")),
        RemovePathStep(path="L", entry_kind="symlink", before_target="/t"),
    )
    apply_plan(nav, plan_for(nav, good), JOB, checkpoint=noop)
    assert not (nav / "f.json").exists() and not (nav / "L").is_symlink()


def test_apply_rejects_paths_escaping_nav_root(tmp_path: Path) -> None:
    """契约 apply_plan：步骤路径逃逸 nav_root 或经过软链接时报 InputError，且什么都没写。"""
    nav = tmp_path / "nav"
    outside = tmp_path / "outside"
    nav.mkdir()
    outside.mkdir()
    (nav / "link").symlink_to(outside)
    for bad in ("../outside/x.json", "/etc/x.json", "link/x.json", "a/../../x.json", ""):
        steps: tuple[Step, ...]
        if not bad:
            continue
        steps = (write_step("ok.json", None, b"1\n"), write_step(bad, None, b"2\n"))
        with pytest.raises(InputError):
            apply_plan(nav, plan_for(nav, steps), JOB, checkpoint=noop)
        assert not (nav / "ok.json").exists() and list(outside.iterdir()) == []
    assert tree_state(outside) == {}


def _count_mutations(run: Callable[[], None], monkeypatch: pytest.MonkeyPatch) -> int:
    """数一遍 run 里有多少次变更类系统调用，用来决定失败注入点的个数。"""
    counter = [0]
    with monkeypatch.context() as patch:
        for name in ("replace", "symlink", "mkdir", "fsync"):
            real = getattr(os, name)

            def counted(*args: object, _real: Callable[..., object] = real, **kw: object) -> object:
                counter[0] += 1
                return _real(*args, **kw)

            patch.setattr(os, name, counted)
        run()
    return counter[0]


def _fail_at(monkeypatch: pytest.MonkeyPatch, number: int) -> None:
    """让第 number 次变更类调用抛 OSError。"""
    counter = [0]
    for name in ("replace", "symlink", "mkdir", "fsync"):
        real = getattr(os, name)

        def maybe(*args: object, _real: Callable[..., object] = real, **kw: object) -> object:
            counter[0] += 1
            if counter[0] == number:
                raise OSError(28, "注入失败：磁盘满")
            return _real(*args, **kw)

        monkeypatch.setattr(os, name, maybe)


def test_apply_failure_at_every_step_rolls_back_to_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L13 验收：对一份多步计划在每一步注入失败，rollback_journal 之后所有文件和链接都等于前像。"""
    reference = tmp_path / "ref"
    reference.mkdir()
    ref_nav, ref_steps = simple_nav(reference)
    total = _count_mutations(
        lambda: apply_plan(ref_nav, plan_for(ref_nav, ref_steps), JOB, checkpoint=noop), monkeypatch
    )
    assert total >= 10
    for number in range(1, total + 1):
        case = tmp_path / f"case{number}"
        case.mkdir()
        paths, nav, plan = _case(case)
        original = tree_state(nav)
        journal, directory = _journal(paths, nav, plan)
        with monkeypatch.context() as patch:
            _fail_at(patch, number)
            with pytest.raises(ExternalError):
                apply_plan(nav, plan, JOB, checkpoint=noop)
        outcome = rollback_journal(nav, directory, journal, checkpoint=noop)
        assert tree_state(nav) == original, f"第 {number} 次变更调用处失败后没有退回"
        assert outcome.mismatches == () and outcome.failed_steps == ()
        assert _temp_files(nav) == []


def test_apply_failure_leaves_only_recognizable_temp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """规范 2.6：失败只留下按命名认得出的临时文件，rollback_journal 把它们清掉。"""
    paths, nav, plan = _case(tmp_path)
    journal, directory = _journal(paths, nav, plan)
    original = tree_state(nav)
    real_replace = os.replace

    def fail_on_b(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        if Path(target).name == "b.json":
            raise OSError(28, "注入失败")
        real_replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", fail_on_b)
        with pytest.raises(ExternalError):
            apply_plan(nav, plan, JOB, checkpoint=noop)
    leftovers = {k for k in tree_state(nav).keys() - original.keys()}
    assert leftovers == {"newdir", ".b.json.rdp-7-2.tmp"}  # 新建的目录和 b.json 的临时文件
    assert _temp_files(nav) == [".b.json.rdp-7-2.tmp"]
    rollback_journal(nav, directory, journal, checkpoint=noop)
    assert tree_state(nav) == original


def test_capture_before_images_conflicts_on_changed_file(tmp_path: Path) -> None:
    """契约 capture_before_images：文件现在的哈希与计划前像不同时报 ConflictError，一行都没写。"""
    _paths, nav, plan = _case(tmp_path)
    images = capture_before_images(nav, plan)
    assert images == {1: b'{"v": 1}\n', 2: b'{"v": 2}\n'}
    (nav / "b.json").write_bytes("被改过\n".encode())
    before = tree_state(nav)
    with pytest.raises(ConflictError):
        capture_before_images(nav, plan)
    (nav / "b.json").write_bytes(b'{"v": 2}\n')
    (nav / "newdir").mkdir()
    (nav / "newdir" / "c.json").write_text("{}", encoding="utf-8")  # 计划要新建的文件已存在
    with pytest.raises(ConflictError):
        capture_before_images(nav, plan)
    assert tree_state(nav) != before  # 只有测试自己的改动，核对本身没有写


def test_observe_step_classifies_before_after_neither(tmp_path: Path) -> None:
    """L14：observe_step 对每种步骤判出 BEFORE、AFTER、NEITHER；前后像相同的步骤读作 BEFORE。"""
    paths, nav, plan = _case(tmp_path)
    journal, _directory = _journal(paths, nav, plan)
    steps = {step.index: step for step in journal.steps}
    # 写入前：全部等于前像。
    assert [observe_step(nav, steps[i]).disk for i in range(5)] == [StepDisk.BEFORE] * 5
    apply_plan(nav, plan, JOB, checkpoint=noop)
    assert [observe_step(nav, steps[i]).disk for i in range(1, 5)] == [StepDisk.AFTER] * 4
    # make_dir 的后像是"空目录"：里面已有 c.json 时读作都不是，逆序回滚到它时 c.json 已经退掉。
    assert observe_step(nav, steps[0]).disk is StepDisk.NEITHER
    (nav / "newdir" / "c.json").unlink()
    assert observe_step(nav, steps[0]).disk is StepDisk.AFTER
    (nav / "newdir" / "c.json").write_bytes(b'{"v": 3}\n')
    # 都不是：文件被改成第三种内容，链接指到第三个地方，目录里多了别人的文件。
    (nav / "a.json").write_bytes("第三种\n".encode())
    (nav / "L").unlink()
    (nav / "L").symlink_to("/third")
    (nav / "newdir" / "foreign").write_text("x", encoding="utf-8")
    assert observe_step(nav, steps[1]).disk is StepDisk.NEITHER
    assert observe_step(nav, steps[4]).disk is StepDisk.NEITHER
    assert observe_step(nav, steps[0]).disk is StepDisk.NEITHER
    assert "/third" in observe_step(nav, steps[4]).actual
    assert observe_step(nav, steps[1]).actual
    # 前后像相同的空操作步骤读作 BEFORE。
    same = plan_for(nav, (write_step("s.json", b"x\n", b"x\n"),))
    (nav / "s.json").write_bytes(b"x\n")
    noop_journal = write_journal(paths, same, {0: b"x\n"}, 9, NOW)
    assert observe_step(nav, noop_journal.steps[0]).disk is StepDisk.BEFORE
    # move / remove 的判断。
    (nav / "m1").mkdir()
    move = MovePathStep(path="m1", to_path="m2", entry_kind="directory")
    rm = RemovePathStep(path="f.json", entry_kind="file", before_file=file_image(b"f\n"))
    (nav / "f.json").write_bytes(b"f\n")
    mj = write_journal(paths, plan_for(nav, (move, rm)), {1: b"f\n"}, 10, NOW)
    assert [observe_step(nav, s).disk for s in mj.steps] == [StepDisk.BEFORE, StepDisk.BEFORE]
    (nav / "m1").rename(nav / "m2")
    (nav / "f.json").unlink()
    assert [observe_step(nav, s).disk for s in mj.steps] == [StepDisk.AFTER, StepDisk.AFTER]
    (nav / "f.json").write_bytes("别的\n".encode())
    (nav / "m1").mkdir()
    assert [observe_step(nav, s).disk for s in mj.steps] == [StepDisk.NEITHER, StepDisk.NEITHER]
    with pytest.raises(InputError):
        observe_step(nav, steps[1].model_copy(update={"path": "../x"}))


def test_rollback_restores_steps_in_reverse_order(tmp_path: Path) -> None:
    """L13：rollback_journal 按序号从大到小退回，restored_steps 的顺序可断言。"""
    paths, nav, plan = _case(tmp_path)
    original = tree_state(nav)
    journal, directory = _journal(paths, nav, plan)
    apply_plan(nav, plan, JOB, checkpoint=noop)
    assert tree_state(nav) != original
    outcome = rollback_journal(nav, directory, journal, checkpoint=noop)
    assert outcome.restored_steps == (4, 3, 2, 1, 0) and outcome.untouched_steps == ()
    assert outcome.mismatches == () and outcome.failed_steps == ()
    assert tree_state(nav) == original


def test_rollback_leaves_steps_already_at_before(tmp_path: Path) -> None:
    """L14：等于前像的步骤不动，记进 untouched_steps。"""
    paths, nav, plan = _case(tmp_path)
    journal, directory = _journal(paths, nav, plan)
    # 只做到第 2 步（make_dir、a.json），后面的步骤还是前像。
    partial = plan_for(nav, plan.steps[:2])
    apply_plan(nav, partial, JOB, checkpoint=noop)
    outcome = rollback_journal(nav, directory, journal, checkpoint=noop)
    assert outcome.restored_steps == (1, 0) and outcome.untouched_steps == (4, 3, 2)
    assert (nav / "a.json").read_bytes() == b'{"v": 1}\n' and not (nav / "newdir").exists()


def test_rollback_lists_neither_and_restores_the_rest(tmp_path: Path) -> None:
    """L14 与 Comments (4)：有两者都不是的项时，能退回的照样退回，退不回的列进 mismatches，不中止后面的步骤。"""
    paths, nav, plan = _case(tmp_path)
    journal, directory = _journal(paths, nav, plan)
    apply_plan(nav, plan, JOB, checkpoint=noop)
    (nav / "b.json").write_bytes("有人在终端里改过\n".encode())  # 第 2 步
    outcome = rollback_journal(nav, directory, journal, checkpoint=noop)
    assert [m.step_index for m in outcome.mismatches] == [2]
    item = outcome.mismatches[0]
    assert item.job_id == JOB and item.path == "b.json"
    assert sha(b'{"v": 2}\n')[:12] in item.expected_before
    assert sha(b'{"v": 22}\n')[:12] in item.expected_after
    assert sha("有人在终端里改过\n".encode())[:12] in item.actual
    assert "有人" not in repr(item)  # 不含正文
    assert outcome.restored_steps == (4, 3, 1, 0)  # 越过对不上的第 2 步继续退
    assert (nav / "b.json").read_bytes() == "有人在终端里改过\n".encode()  # 对不上的不动
    assert (nav / "a.json").read_bytes() == b'{"v": 1}\n' and str(
        Path(nav / "L").readlink()
    ) == "/old-target"


def test_rollback_restore_failure_is_reported_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Comments (6)：单步退回动作失败记进 failed_steps 和 mismatches，不抛。"""
    paths, nav, plan = _case(tmp_path)
    journal, directory = _journal(paths, nav, plan)
    apply_plan(nav, plan, JOB, checkpoint=noop)
    real_replace = os.replace

    def fail_on_a(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        if Path(target).name == "a.json":
            raise PermissionError(13, "注入的权限错误")
        real_replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", fail_on_a)
        outcome = rollback_journal(nav, directory, journal, checkpoint=noop)
    assert outcome.failed_steps == (1,)
    assert [m.step_index for m in outcome.mismatches] == [1]
    assert "退回失败" in outcome.mismatches[0].actual
    assert outcome.restored_steps == (4, 3, 2, 0)  # 其余步骤照样处理，包括退完文件之后已空的目录
    assert (nav / "a.json").read_bytes() == b'{"v": 11}\n'


def test_rollback_is_idempotent(tmp_path: Path) -> None:
    """契约 rollback_journal：对已回滚的日志再回滚，结果全部为 untouched。"""
    paths, nav, plan = _case(tmp_path)
    original = tree_state(nav)
    journal, directory = _journal(paths, nav, plan)
    apply_plan(nav, plan, JOB, checkpoint=noop)
    rollback_journal(nav, directory, journal, checkpoint=noop)
    second = rollback_journal(nav, directory, journal, checkpoint=noop)
    assert second.restored_steps == () and second.mismatches == ()
    assert set(second.untouched_steps) == {0, 1, 2, 3, 4}
    assert tree_state(nav) == original


def test_rollback_rejects_other_nav_root(tmp_path: Path) -> None:
    """契约 rollback_journal：nav_root 与日志不同时报 InputError，不对错误的树做回滚。"""
    paths, nav, plan = _case(tmp_path)
    journal, directory = _journal(paths, nav, plan)
    apply_plan(nav, plan, JOB, checkpoint=noop)
    other = tmp_path / "other"
    other.mkdir()
    (other / "a.json").write_bytes(b'{"v": 11}\n')
    with pytest.raises(InputError):
        rollback_journal(other, directory, journal, checkpoint=noop)
    assert (other / "a.json").read_bytes() == b'{"v": 11}\n'
    assert (nav / "a.json").read_bytes() == b'{"v": 11}\n'
    # 前像文件损坏时，开始回滚之前就报错，一步都没动。
    (directory / "images" / "2.before").write_bytes("坏\n".encode())
    before = tree_state(nav)
    with pytest.raises(InputError):
        rollback_journal(nav, directory, journal, checkpoint=noop)
    assert tree_state(nav) == before


def test_rollback_make_dir_only_when_empty(tmp_path: Path) -> None:
    """契约 rollback_journal：make_dir 退回时目录非空则不删，并作为对不上的项列出。"""
    paths, nav, _plan = _case(tmp_path)
    plan = plan_for(nav, (MakeDirStep(path="newdir"),))
    journal, directory = _journal(paths, nav, plan)
    apply_plan(nav, plan, JOB, checkpoint=noop)
    (nav / "newdir" / "foreign.txt").write_text("别人放的", encoding="utf-8")
    outcome = rollback_journal(nav, directory, journal, checkpoint=noop)
    assert (nav / "newdir" / "foreign.txt").exists()
    assert [m.step_index for m in outcome.mismatches] == [0] and outcome.restored_steps == ()
    (nav / "newdir" / "foreign.txt").unlink()
    again = rollback_journal(nav, directory, journal, checkpoint=noop)
    assert again.restored_steps == (0,) and not (nav / "newdir").exists()


def test_rollback_recreates_removed_objects(tmp_path: Path) -> None:
    """契约 rollback_journal：remove_path 退回时按前像重建文件、链接、目录。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ())
    initialize_state(paths)
    nav = tmp_path / "nav"
    nav.mkdir()
    (nav / "f.json").write_bytes(b"content\n")
    (nav / "L").symlink_to("/t")
    (nav / "d").mkdir()
    steps: tuple[Step, ...] = (
        RemovePathStep(path="f.json", entry_kind="file", before_file=file_image(b"content\n")),
        RemovePathStep(path="L", entry_kind="symlink", before_target="/t"),
        RemovePathStep(path="d", entry_kind="directory"),
    )
    plan = plan_for(nav, steps)
    original = tree_state(nav)
    journal, directory = _journal(paths, nav, plan)
    apply_plan(nav, plan, JOB, checkpoint=noop)
    assert tree_state(nav) == {}
    outcome = rollback_journal(nav, directory, journal, checkpoint=noop)
    assert outcome.restored_steps == (2, 1, 0) and tree_state(nav) == original


def _spy_mutations(monkeypatch: pytest.MonkeyPatch, seen: list[str]) -> None:
    """记录所有变更类系统调用碰到的路径。"""
    for name in ("replace", "rename", "symlink", "mkdir", "unlink", "rmdir"):
        real = getattr(os, name)

        def spy(
            *args: object, _real: Callable[..., object] = real, _name: str = name, **kw: object
        ) -> object:
            # symlink 的第一个参数是链接目标文本，不是被写的位置；被写的是第二个参数。
            written = args[1:2] if _name == "symlink" else args
            seen.extend(os.fspath(a) for a in written if isinstance(a, str | os.PathLike))
            return _real(*args, **kw)

        monkeypatch.setattr(os, name, spy)
    real_open = os.open

    def spy_open(path: str | os.PathLike[str], flags: int, *args: int, **kw: object) -> int:
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
            seen.append(str(path))
        return real_open(path, flags, *args, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "open", spy_open)


def test_writes_only_nav_root_and_state_dir(
    fake_nav: FakeNavigation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收 5：把假存储根设成只读，写作业照常成功，存储根里没有任何变化；写入只发生在 nav_root 和状态目录。"""
    roots = fake_nav.nav_root.parent / "roots"
    original_roots = tree_state(roots)
    original_nav = tree_state(fake_nav.nav_root)
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ())
    initialize_state(paths)
    target = fake_nav.nav_root / "按任务" / "EgoProDemo"
    link_target = str(Path(target / "原始数据").readlink())
    new_content = (target / "原始路径.json").read_bytes().replace(b"EgoProDemo", b"EgoProDemo2")
    steps: tuple[Step, ...] = (
        write_step(
            "按任务/EgoProDemo/原始路径.json",
            (target / "原始路径.json").read_bytes(),
            new_content,
        ),
        SetLinkStep(
            path="按任务/EgoProDemo/原始数据",
            before_target=link_target,
            after_target=str(roots / "dataset1"),
        ),
    )
    plan = plan_for(fake_nav.nav_root, steps)
    modes = {p: stat.S_IMODE(p.stat().st_mode) for p in [roots, *roots.rglob("*")] if p.is_dir()}
    for directory in modes:
        directory.chmod(0o555)  # 存储根设成只读
    spy_paths: list[str] = []
    try:
        with monkeypatch.context() as patch:
            _spy_mutations(patch, spy_paths)
            journal, directory = _journal(paths, fake_nav.nav_root, plan)
            apply_plan(fake_nav.nav_root, plan, JOB, checkpoint=noop)
            rollback_journal(fake_nav.nav_root, directory, journal, checkpoint=noop)
            apply_plan(fake_nav.nav_root, plan, JOB, checkpoint=noop)
    finally:
        for directory, mode in modes.items():
            directory.chmod(mode)
    assert str(Path(target / "原始数据").readlink()) == str(roots / "dataset1")
    assert (target / "原始路径.json").read_bytes() == new_content
    assert tree_state(roots) == original_roots  # 存储根里没有任何变化
    assert tree_state(fake_nav.nav_root) != original_nav
    allowed = (str(fake_nav.nav_root), str(paths.root))
    assert spy_paths and all(path.startswith(allowed) for path in spy_paths), spy_paths


CHILD = """
import json, os, sys, time
from pathlib import Path
from datetime import UTC, datetime
from rdp.jobs.navwrite.models import NavWritePlan
from rdp.jobs.navwrite.atomic import apply_plan, capture_before_images
from rdp.jobs.navwrite.journal import write_journal
from rdp.infra.state import StatePaths
from rdp.infra.config import PlatformConfig
from rdp.infra.state import state_paths

root, kill_after, ready = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
plan = NavWritePlan.model_validate_json((root / "plan.json").read_text(encoding="utf-8"))
paths = state_paths(PlatformConfig(state_dir=root / "state"), ())
nav = Path(plan.state.nav_root)
write_journal(paths, plan, capture_before_images(nav, plan), 7, datetime(2026, 10, 29, tzinfo=UTC))
real_replace, done = os.replace, [0]

def replace(source, target):
    real_replace(source, target)
    done[0] += 1
    if done[0] >= kill_after:
        ready.write_text("ready", encoding="utf-8")
        time.sleep(120)  # 等父进程 kill -9，不会自己退出

os.replace = replace
apply_plan(nav, plan, 7, checkpoint=lambda: None)
ready.write_text("finished", encoding="utf-8")
"""


@contextmanager
def _child_process(command: list[str]) -> Generator[subprocess.Popen[bytes]]:
    """启动子进程，退出时无条件回收，不留孤儿进程。"""
    process = subprocess.Popen(  # noqa: S603  # 理由：固定解释器加内联测试脚本，参数全部来自临时目录。
        command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    try:
        yield process
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        if process.stderr is not None:
            process.stderr.close()


@pytest.mark.parametrize("kill_after", [1, 2, 3])
def test_kill_minus_nine_midway_then_recovery_restores_before(kill_after: int) -> None:
    """验收 1（断电演练的底座）：子进程写到一半被 kill -9，再跑回滚，导航层回到前像；有超时，清理进程和临时目录。"""
    from rdp.jobs.navwrite.journal import list_journals, read_journal

    with tempfile.TemporaryDirectory(prefix="rdp-kill9-") as scratch:
        root = Path(scratch)
        paths = state_paths(PlatformConfig(state_dir=root / "state"), ())
        initialize_state(paths)
        nav, steps = simple_nav(root)
        plan = plan_for(nav, steps)
        (root / "plan.json").write_text(plan.model_dump_json(), encoding="utf-8")
        original = tree_state(nav)
        ready = root / "ready"
        command = [sys.executable, "-I", "-c", CHILD, str(root), str(kill_after), str(ready)]
        with _child_process(command) as process:
            deadline = time.monotonic() + 30
            while not ready.exists():
                assert process.poll() is None, "子进程提前退出：" + (
                    process.stderr.read().decode() if process.stderr else ""
                )
                assert time.monotonic() < deadline, "等子进程写到一半超时"
                time.sleep(0.02)
            assert ready.read_text(encoding="utf-8") == "ready"
            process.kill()  # SIGKILL，没有任何清理机会
            assert process.wait(timeout=10) == -9
        assert tree_state(nav) != original  # 导航层确实是一半新一半旧
        (journal_location,) = list_journals(paths)
        assert journal_location.complete
        journal = read_journal(journal_location.directory)
        outcome = rollback_journal(nav, journal_location.directory, journal, checkpoint=noop)
        assert outcome.mismatches == ()
        assert tree_state(nav) == original
        assert _temp_files(nav) == []
    assert not Path(scratch).exists()
