"""写入日志的契约测试（M1-07，L13）：nav-journal 的磁盘格式。"""

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from navwrite_support import plan_for, sha, simple_nav

from rdp.infra.config import PlatformConfig
from rdp.infra.diagnostics import ConflictError, ExternalError, InputError
from rdp.infra.state import StatePaths, initialize_state, state_paths
from rdp.jobs.navwrite.journal import (
    discard_journal,
    journal_directory,
    list_journals,
    read_before_image,
    read_journal,
    write_journal,
)
from rdp.jobs.navwrite.models import NavWritePlan

NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)


def _setup(tmp_path: Path) -> tuple[StatePaths, Path, NavWritePlan, dict[int, bytes]]:
    """状态目录、导航树、计划和计划要求的前像字节。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ())
    initialize_state(paths)
    nav, steps = simple_nav(tmp_path)
    plan = plan_for(nav, steps)
    return paths, nav, plan, {1: b'{"v": 1}\n', 2: b'{"v": 2}\n'}


def test_write_journal_layout_and_fsync_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L13：write_journal 先写 images/*.before，再写 journal.json.tmp 并 rename 成 journal.json；journal.json 一出现就是完整的。"""
    paths, _nav, plan, images = _setup(tmp_path)
    directory = journal_directory(paths, 7)
    events: list[str] = []
    real_replace, real_fsync = os.replace, os.fsync

    def replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        events.append(f"replace:{Path(source).name}->{Path(target).name}")
        # rename 的瞬间：前像文件和已 fsync 的 tmp 必须都在，journal.json 还没出现。
        assert (directory / "images" / "1.before").is_file() and Path(source).is_file()
        assert not (directory / "journal.json").exists()
        real_replace(source, target)

    def fsync(descriptor: int) -> None:
        events.append("fsync")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(os, "fsync", fsync)
    journal = write_journal(paths, plan, images, 7, NOW)
    assert events.index("replace:journal.json.tmp->journal.json") > events.index("fsync")
    assert events.count("fsync") >= 4  # 两份前像、journal.json.tmp、目录
    assert sorted(p.name for p in directory.iterdir()) == ["images", "journal.json"]
    assert sorted(p.name for p in (directory / "images").iterdir()) == ["1.before", "2.before"]
    assert read_journal(directory) == journal


def test_journal_records_before_images_and_after_hashes(tmp_path: Path) -> None:
    """L13：日志里每步有路径、前像、后像哈希；不抄后像正文；前像存在的 write_file 有 before_blob。"""
    paths, _nav, plan, images = _setup(tmp_path)
    journal = write_journal(paths, plan, images, 7, NOW)
    assert [step.op for step in journal.steps] == [
        "make_dir",
        "write_file",
        "write_file",
        "write_file",
        "set_link",
    ]
    assert [step.index for step in journal.steps] == [0, 1, 2, 3, 4]
    a = journal.steps[1]
    assert a.path == "a.json" and a.before_blob == "images/1.before"
    assert a.before_file is not None and a.before_file.sha256 == sha(images[1])
    assert a.after_file is not None and a.after_file.sha256 == sha(b'{"v": 11}\n')
    created = journal.steps[3]
    assert created.before_blob is None and created.before_file is not None
    assert created.before_file.exists is False
    link = journal.steps[4]
    assert (link.before_target, link.after_target) == ("/old-target", "/new-target")
    text = (journal_directory(paths, 7) / "journal.json").read_text(encoding="utf-8")
    assert '"v": 11' not in text and "after_content" not in text  # 后像正文不进日志
    assert journal.job_id == 7 and journal.nav_root == plan.state.nav_root
    assert journal.dataset_ids == ("dataset-1",) and journal.created_at == NOW
    assert read_before_image(journal_directory(paths, 7), a) == images[1]


def test_write_journal_rejects_missing_or_wrong_before_images(tmp_path: Path) -> None:
    """契约 write_journal：before_images 缺项、多项或哈希与计划不符时报 InputError，且不留日志目录。"""
    paths, _nav, plan, images = _setup(tmp_path)
    for bad in (
        {1: images[1]},
        {**images, 0: "多余".encode()},
        {**images, 3: "不该有".encode()},
        {1: images[1], 2: "哈希不符".encode()},
    ):
        with pytest.raises(InputError):
            write_journal(paths, plan, bad, 7, NOW)
        assert not journal_directory(paths, 7).exists()


def test_write_journal_refuses_existing_directory(tmp_path: Path) -> None:
    """契约 write_journal：同一作业编号的日志目录已存在时报 ConflictError。"""
    paths, _nav, plan, images = _setup(tmp_path)
    write_journal(paths, plan, images, 7, NOW)
    marker = journal_directory(paths, 7) / "journal.json"
    before = marker.read_bytes()
    with pytest.raises(ConflictError):
        write_journal(paths, plan, images, 7, NOW)
    assert marker.read_bytes() == before  # 别人的日志原样保留


def test_write_journal_failure_leaves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """契约 write_journal：写入或 rename 失败时整个日志目录被清掉，导航层未动。"""
    paths, nav, plan, images = _setup(tmp_path)
    nav_before = {p.name: p.read_bytes() for p in nav.glob("*.json")}
    real_replace = os.replace

    def failing(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        if Path(target).name == "journal.json":
            raise OSError("磁盘满")
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", failing)
    with pytest.raises(ExternalError):
        write_journal(paths, plan, images, 7, NOW)
    assert not journal_directory(paths, 7).exists()
    assert list(paths.nav_journal.iterdir()) == []
    assert {p.name: p.read_bytes() for p in nav.glob("*.json")} == nav_before


def test_incomplete_journal_means_navigation_untouched(tmp_path: Path) -> None:
    """L13：只有 journal.json.tmp 或空目录时，list_journals 标 complete=False。"""
    paths, _nav, plan, images = _setup(tmp_path)
    (paths.nav_journal / "3").mkdir()
    (paths.nav_journal / "4").mkdir()
    (paths.nav_journal / "4" / "journal.json.tmp").write_text("{", encoding="utf-8")
    write_journal(paths, plan, images, 5, NOW)
    found = {item.job_id: item.complete for item in list_journals(paths)}
    assert found == {3: False, 4: False, 5: True}
    with pytest.raises(InputError):
        read_journal(paths.nav_journal / "4")


def test_read_journal_rejects_unknown_version_and_corruption(tmp_path: Path) -> None:
    """契约 read_journal：缺 journal.json、坏 JSON、未知 format_version 报 InputError。"""
    paths, _nav, plan, images = _setup(tmp_path)
    directory = journal_directory(paths, 7)
    write_journal(paths, plan, images, 7, NOW)
    path = directory / "journal.json"
    good = path.read_text(encoding="utf-8")
    for broken in (
        "{坏",
        good.replace('"format_version":1', '"format_version":2'),
        "[]",
        '{"a":1}',
    ):
        path.write_text(broken, encoding="utf-8")
        with pytest.raises(InputError):
            read_journal(directory)
    path.unlink()
    with pytest.raises(InputError):
        read_journal(directory)


def test_read_before_image_detects_corruption(tmp_path: Path) -> None:
    """契约 read_before_image：读到的字节哈希与日志记的不符时报 InputError。"""
    paths, _nav, plan, images = _setup(tmp_path)
    directory = journal_directory(paths, 7)
    journal = write_journal(paths, plan, images, 7, NOW)
    (directory / "images" / "1.before").write_bytes("被改坏".encode())
    with pytest.raises(InputError):
        read_before_image(directory, journal.steps[1])
    with pytest.raises(InputError):
        read_before_image(directory, journal.steps[3])  # 新建的文件没有前像
    (directory / "images" / "2.before").unlink()
    with pytest.raises(InputError):
        read_before_image(directory, journal.steps[2])


def test_list_journals_sorted_and_ignores_foreign_names(tmp_path: Path) -> None:
    """契约 list_journals：按作业编号升序；名字不是正整数的子目录被忽略但不删除；目录不存在返回空元组。"""
    paths, _nav, plan, images = _setup(tmp_path)
    for job_id in (12, 3, 100):
        write_journal(paths, plan, images, job_id, NOW)
    for foreign in ("abc", "0", "-1", "007", "1.5"):
        (paths.nav_journal / foreign).mkdir()
    (paths.nav_journal / "9").write_text("是文件不是目录", encoding="utf-8")
    assert [item.job_id for item in list_journals(paths)] == [3, 12, 100]
    assert (paths.nav_journal / "abc").is_dir() and (paths.nav_journal / "007").is_dir()
    paths.nav_journal.rename(tmp_path / "moved")
    assert list_journals(paths) == ()
    (tmp_path / "moved").rename(paths.nav_journal)


def test_discard_journal_is_idempotent_and_ordered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """契约 discard_journal：目录不存在视为完成；先删 journal.json 再删其余，半删状态读作日志不完整。"""
    paths, _nav, plan, images = _setup(tmp_path)
    directory = journal_directory(paths, 7)
    write_journal(paths, plan, images, 7, NOW)
    import shutil

    real_rmtree = shutil.rmtree

    def rmtree_after_check(path: Path, ignore_errors: bool = False) -> None:
        # 走到递归删除时，journal.json 必须已经没了：此刻中断，读作"日志不完整"。
        assert not (Path(path) / "journal.json").exists()
        assert [item.complete for item in list_journals(paths)] == [False]
        real_rmtree(path, ignore_errors=ignore_errors)

    monkeypatch.setattr(shutil, "rmtree", rmtree_after_check)
    discard_journal(directory)
    assert not directory.exists()
    discard_journal(directory)  # 幂等
    broken = paths.nav_journal / "8"
    broken.mkdir()

    def failing_rmtree(_path: Path, ignore_errors: bool = False) -> None:
        raise OSError("坏")

    monkeypatch.setattr(shutil, "rmtree", failing_rmtree)
    with pytest.raises(ExternalError):
        discard_journal(broken)
    assert broken.exists()


def test_discard_journal_refuses_foreign_directory(tmp_path: Path) -> None:
    """契约 discard_journal：目录不在 nav-journal 之下时报 InputError，不删除。"""
    paths, nav, _plan, _images = _setup(tmp_path)
    with pytest.raises(InputError):
        discard_journal(nav)
    with pytest.raises(InputError):
        discard_journal(paths.nav_journal)
    with pytest.raises(InputError):
        discard_journal(paths.nav_journal / "7" / "images")
    assert nav.is_dir() and (nav / "a.json").is_file()
