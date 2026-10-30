"""M1-08 契约行为清单；只使用临时目录或 tests 假导航，真实副本演练由执行线负责。"""

from pathlib import Path

import pytest
from nav_manifest import FakeNavigation
from pydantic import ValidationError

from rdp.jobs.navwrite.create_models import (
    FormatEntrySelection,
    validate_data_origin,
    validate_entry_name,
)


def test_link_target_must_exist(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L1：在线本地存储根下目标不存在时拒绝，导航和目标均不变。"""
    from creation_support import creation_case, link_parameters, target_path
    from navwrite_support import noop, tree_state

    from rdp.infra.diagnostics import InputError
    from rdp.jobs.navwrite.create_builders import build_link_preview

    with creation_case(tmp_path, fake_nav) as h:
        hparams = link_parameters(h)
        params = hparams.model_copy(
            update={
                "link": hparams.link.model_copy(
                    update={"target_path": str(target_path(h) / "missing")}
                )
            }
        )
        before = tree_state(h.nav)
        with pytest.raises(InputError):
            build_link_preview(h.case.scanning, params, checkpoint=noop)
        assert tree_state(h.nav) == before


def test_link_target_must_be_absolute() -> None:
    """验证契约：L1：相对目标路径按参数错误拒绝，所有 SetLinkStep 都是绝对目标。"""
    from rdp.jobs.navwrite.create_models import FirstLink

    with pytest.raises(ValidationError):
        FirstLink(name="x", target_path="relative", fallback_format="mcap")


def test_link_target_must_be_registered(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L1：原始目标不属于任何登记根时拒绝。"""
    from creation_support import creation_case, link_parameters
    from navwrite_support import noop

    from rdp.infra.diagnostics import InputError
    from rdp.jobs.navwrite.create_builders import build_link_preview
    from rdp.jobs.navwrite.create_models import FirstLink

    with creation_case(tmp_path, fake_nav) as h:
        outside = tmp_path / "outside"
        outside.mkdir()
        params = link_parameters(
            h, link=FirstLink(name="x", target_path=str(outside), fallback_format="mcap")
        )
        with pytest.raises(InputError):
            build_link_preview(h.case.scanning, params, checkpoint=noop)


def test_link_realpath_must_stay_registered(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L1：祖先软链接使 realpath 逃出登记根时拒绝。"""
    from creation_support import creation_case, link_parameters, target_path
    from navwrite_support import noop

    from rdp.infra.diagnostics import InputError
    from rdp.jobs.navwrite.create_builders import build_link_preview
    from rdp.jobs.navwrite.create_models import FirstLink

    with creation_case(tmp_path, fake_nav) as h:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "child").mkdir()
        escape = target_path(h) / "escape"
        escape.symlink_to(outside, target_is_directory=True)
        params = link_parameters(
            h, link=FirstLink(name="x", target_path=str(escape / "child"), fallback_format="mcap")
        )
        with pytest.raises(InputError):
            build_link_preview(h.case.scanning, params, checkpoint=noop)


def test_link_target_outside_navigation(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L1：目标位于导航根内部时拒绝，即使同样落在登记根下。"""
    from dataclasses import replace

    from creation_support import creation_case, link_parameters
    from navwrite_support import noop

    from rdp.infra.diagnostics import InputError
    from rdp.jobs.navwrite.create_builders import build_link_preview
    from rdp.jobs.navwrite.create_models import FirstLink

    with creation_case(tmp_path, fake_nav) as h:
        root = h.case.scanning.roots[0].model_copy(update={"path": h.nav.parent})
        deps = replace(h.case.scanning, roots=(root,))
        params = link_parameters(
            h, link=FirstLink(name="x", target_path=str(h.nav), fallback_format="mcap")
        )
        with pytest.raises(InputError):
            build_link_preview(deps, params, checkpoint=noop)


def test_link_target_not_symlink(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L1：目标自身是软链接时拒绝，不能链到链接。"""
    from creation_support import creation_case, link_parameters, target_path
    from navwrite_support import noop

    from rdp.infra.diagnostics import InputError
    from rdp.jobs.navwrite.create_builders import build_link_preview
    from rdp.jobs.navwrite.create_models import FirstLink

    with creation_case(tmp_path, fake_nav) as h:
        path = target_path(h) / "link"
        path.symlink_to(target_path(h))
        params = link_parameters(
            h, link=FirstLink(name="x", target_path=str(path), fallback_format="mcap")
        )
        with pytest.raises(InputError):
            build_link_preview(h.case.scanning, params, checkpoint=noop)


def test_link_destination_stays_in_views(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L1：禁止格式、版本或名称穿越，所有目的都在两个视图的入口下。"""
    from creation_support import creation_case, target_path

    from rdp.jobs.navwrite.create_models import FirstLink

    with creation_case(tmp_path, fake_nav) as h:
        for value in ("../x", "a/b", ".x"):
            with pytest.raises(ValidationError):
                FirstLink(name=value, target_path=str(target_path(h)))


def test_link_name_no_slash() -> None:
    """验证契约：L1：链接名含 / 时拒绝，不产生多层路径。"""
    with pytest.raises(ValueError):
        validate_entry_name("a/b")
    assert validate_entry_name("原始数据") == "原始数据"


def test_link_name_no_dot_prefix() -> None:
    """验证契约：L1：链接名以 . 开头时拒绝，包括 . 和 ..。"""
    for value in [".x", ".", ".."]:
        with pytest.raises(ValueError):
            validate_entry_name(value)


def test_link_name_no_reserved_json() -> None:
    """验证契约：L1：四份 JSON 保留名逐个拒绝，不覆盖事实文件。"""
    for value in ["原始路径.json", "子任务.json", "数据集信息.json", "来源.json"]:
        with pytest.raises(ValueError):
            validate_entry_name(value)


def test_names_reject_empty_and_nul() -> None:
    """验证契约：执行线名称规则：空名及 NUL 无法作为目录分量，模型拒绝。"""
    for value in ["", "a\x00b"]:
        with pytest.raises(ValueError):
            validate_entry_name(value)


def test_dataset_name_uses_link_rules(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：最后 Comment：数据集名共用不含 /、不以 . 开头及保留名规则。"""
    from creation_support import creation_case, new_parameters

    with creation_case(tmp_path, fake_nav) as h:
        for value in ("../x", "a/b", ".x", "来源.json"):
            with pytest.raises(ValidationError):
                new_parameters(h, dataset_name=value)


def test_dataset_name_cannot_collide(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：最后 Comment：按任务下同名目录、文件、链接或断链均拒绝。"""
    from creation_support import creation_case, new_parameters, stamp
    from navwrite_support import noop

    from rdp.infra.diagnostics import InputError
    from rdp.jobs.navwrite.create_builders import build_dataset_preview

    with creation_case(tmp_path, fake_nav) as h:
        for name in ("EgoProDemo", "occupied"):
            if name == "occupied":
                (h.nav / "按任务" / name).symlink_to(tmp_path / "absent")
            with pytest.raises(InputError):
                build_dataset_preview(
                    h.case.scanning, new_parameters(h, dataset_name=name), stamp(), checkpoint=noop
                )


def test_readonly_local_root_is_allowed(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L1 与 ADR 0006：只读本地存储根可作为链接目标，整个操作不改目标。"""
    from creation_support import creation_case, link_parameters, target_path
    from navwrite_support import noop, tree_state

    from rdp.jobs.navwrite.create_builders import build_link_preview

    with creation_case(tmp_path, fake_nav) as h:
        assert not h.case.scanning.roots[0].writable
        root = target_path(h)
        before = tree_state(root)
        assert (
            build_link_preview(
                h.case.scanning, link_parameters(h), checkpoint=noop
            ).report.link_count
            == 1
        )
        assert tree_state(root) == before


def test_root_offline_identity_timeout(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：ADR 0006：根未挂载和UUID身份不符分别以外部失败结束，不伪装成路径缺失；超时由构造控制用例覆盖。"""
    from dataclasses import replace

    from creation_support import creation_case, link_parameters
    from navwrite_support import noop

    from rdp.infra.diagnostics import ExternalError
    from rdp.jobs.navwrite.create_builders import build_link_preview

    with creation_case(tmp_path, fake_nav) as h:

        def missing_uuid(_name: str) -> None:
            return None

        checker = h.case.scanning.storage
        assert checker is not None
        for mounts in (
            replace(checker.mounts, read_mountinfo=lambda: ""),
            replace(checker.mounts, resolve_uuid_device=missing_uuid),
        ):
            deps = replace(h.case.scanning, storage=replace(checker, mounts=mounts))
            with pytest.raises(ExternalError):
                build_link_preview(deps, link_parameters(h), checkpoint=noop)


def test_nas_is_out_of_scope(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：工单不做项：NAS 目标明确拒绝，不自行批准 1B。"""
    from dataclasses import replace

    from creation_support import creation_case, link_parameters
    from navwrite_support import noop

    from rdp.infra.diagnostics import InputError
    from rdp.jobs.navwrite.create_builders import build_link_preview

    with creation_case(tmp_path, fake_nav) as h:
        root = h.case.scanning.roots[0].model_copy(
            update={"uuid": None, "nfs_export": "server:/export"}
        )
        with pytest.raises(InputError):
            build_link_preview(
                replace(h.case.scanning, roots=(root,)), link_parameters(h), checkpoint=noop
            )


def test_meta_info_is_authoritative(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L3 与最后 Comment：有元信息时用其格式/版本，不被 fallback_format 覆盖；v3.0 映射到格式版本 3.0。"""
    from creation_support import creation_case, link_parameters, target_path
    from navwrite_support import noop

    from rdp.jobs.navwrite.create_builders import build_link_preview

    with creation_case(tmp_path, fake_nav) as h:
        meta = target_path(h) / "meta"
        meta.mkdir()
        (meta / "info.json").write_text('{"codebase_version":"v3.0"}')
        report = build_link_preview(
            h.case.scanning, link_parameters(h), checkpoint=noop
        ).report.creation
        assert report is not None and report.resolved_format == "lerobot"
        assert report.resolved_version == "3.0" and report.metadata_source == "meta_info"


def test_missing_meta_uses_selected_format(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：最后 Comment：mcap/tar 无元信息时用登记格式选择，sources[].version 明确 null。"""
    from creation_support import creation_case, link_parameters, target_path
    from navwrite_support import noop

    from rdp.jobs.navwrite.create_builders import build_link_preview
    from rdp.jobs.navwrite.create_models import FirstLink

    with creation_case(tmp_path, fake_nav) as h:
        for kind in ("mcap", "archives"):
            params = link_parameters(
                h, link=FirstLink(name="x", target_path=str(target_path(h)), fallback_format=kind)
            )
            details = build_link_preview(h.case.scanning, params, checkpoint=noop).report.creation
            assert (
                details is not None
                and details.resolved_format == kind
                and details.resolved_version is None
            )


def test_missing_meta_requires_selection(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：最后 Comment：缺元信息且未选择格式时拒绝，不猜格式。"""
    from creation_support import creation_case, link_parameters, target_path
    from navwrite_support import noop

    from rdp.infra.diagnostics import InputError
    from rdp.jobs.navwrite.create_builders import build_link_preview
    from rdp.jobs.navwrite.create_models import FirstLink

    with creation_case(tmp_path, fake_nav) as h:
        params = link_parameters(h, link=FirstLink(name="x", target_path=str(target_path(h))))
        with pytest.raises(InputError):
            build_link_preview(h.case.scanning, params, checkpoint=noop)


def test_bad_meta_is_not_missing(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：契约：损坏、越界、超预算或不可读元信息不能静默降级为缺文件。"""
    from creation_support import creation_case, link_parameters, target_path
    from navwrite_support import noop

    from rdp.infra.diagnostics import InputError
    from rdp.jobs.navwrite.create_builders import build_link_preview

    with creation_case(tmp_path, fake_nav) as h:
        meta = target_path(h) / "meta"
        meta.mkdir()
        info = meta / "info.json"
        for raw in ("not-json", "x" * (1024 * 1024 + 1), '{"codebase_version":8}'):
            info.write_text(raw)
            with pytest.raises(InputError):
                build_link_preview(h.case.scanning, link_parameters(h), checkpoint=noop)


def test_format_registry_and_version_layer() -> None:
    """验证契约：ADR 0006：拒绝未登记格式；lerobot 必填版本，mcap/archives 不接收版本。"""
    assert FormatEntrySelection(format="mcap").version is None
    for values in (
        {"format": "missing"},
        {"format": "lerobot"},
        {"format": "mcap", "version": "3.0"},
    ):
        with pytest.raises(ValidationError):
            FormatEntrySelection.model_validate(values)
    assert FormatEntrySelection(format="lerobot", version="3.0").version == "3.0"


def test_format_selection_no_duplicates() -> None:
    """验证契约：契约：重复格式位置拒绝，不能悄悄去重后预览。"""
    from rdp.jobs.navwrite.create_models import LinkPreviewParameters

    with pytest.raises(ValidationError):
        LinkPreviewParameters.model_validate(
            {
                "dataset_id": "dataset-01",
                "link": {
                    "name": "x",
                    "target_path": "/temporary-target",
                    "fallback_format": "mcap",
                },
                "format_entries": [{"format": "mcap"}, {"format": "mcap"}],
            }
        )


def test_origin_required_and_registered() -> None:
    """验证契约：L5：数据来源必填且来自 DATA_ORIGINS，显式未知可用，英文筛选键不可用。"""
    assert validate_data_origin("开源下载") == "开源下载"
    assert validate_data_origin("未知") == "未知"
    for value in ("", "open_source", "采集"):
        with pytest.raises(ValueError):
            validate_data_origin(value)


def test_budgets_and_control_checkpoints(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：规范 2.7：构造取消检查点立即退出，存储访问超时归外部失败且导航不变；参数预算由接口用例覆盖。"""
    from dataclasses import replace
    from threading import Event

    from creation_support import creation_case, link_parameters
    from navwrite_support import noop, tree_state

    from rdp.infra.config import MIN_STORAGE_ACCESS_TIMEOUT_S, StorageConfig
    from rdp.infra.diagnostics import ExternalError
    from rdp.jobs.errors import JobCancelledError
    from rdp.jobs.navwrite.create_builders import build_link_preview
    from rdp.jobs.navwrite.errors import nav_conflict_error

    with creation_case(tmp_path, fake_nav) as h:
        params = link_parameters(h)
        before = tree_state(h.nav)

        def stop() -> None:
            raise JobCancelledError(nav_conflict_error("TEST_CANCEL", "取消").diagnostics)

        with pytest.raises(JobCancelledError):
            build_link_preview(h.case.scanning, params, checkpoint=stop)
        checker = h.case.scanning.storage
        assert checker is not None
        release, finished = Event(), Event()
        # 清理等待两秒有上限，确保测试注入的阻塞回调在用例结束前释放。
        cleanup_timeout_s = 2

        def blocked() -> str:
            try:
                release.wait(cleanup_timeout_s)
                return checker.mounts.read_mountinfo()
            finally:
                finished.set()

        limited = replace(
            checker,
            options=StorageConfig(access_timeout_s=MIN_STORAGE_ACCESS_TIMEOUT_S),
            mounts=replace(checker.mounts, read_mountinfo=blocked),
        )
        try:
            with pytest.raises(ExternalError) as caught:
                build_link_preview(
                    replace(h.case.scanning, storage=limited), params, checkpoint=noop
                )
            assert "timeout" in caught.value.diagnostics[0].actual
        finally:
            release.set()
            assert finished.wait(cleanup_timeout_s)
        assert tree_state(h.nav) == before
