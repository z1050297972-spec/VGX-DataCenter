"""输出根身份规则只处理内存路径，覆盖历史作业跨根误定位的安全边界。"""

from pathlib import Path

import pytest
from nav_manifest import FakeNavigation

from rdp.infra.config import StorageRootConfig
from rdp.jobs.conversion._output_storage import locate_root
from rdp.jobs.errors import JobInputError


def test_legacy_output_selects_b_and_rejects_conflicting_evidence(tmp_path: Path) -> None:
    """历史实际 B 产物不受配置排序影响；错编号、越界和矛盾记录均拒绝。"""
    roots = tuple(
        StorageRootConfig(
            name=name.lower(), path=tmp_path / name, writable=True, nfs_export=f"nas:/{name}"
        )
        for name in ("A", "B")
    )
    stage = tmp_path / "B/暂存/转换/60"
    for ordered in (roots, roots[::-1]):
        assert locate_root(ordered, 60, None, (str(stage),), str(stage / "cleaned")) == roots[1]
        assert locate_root(ordered, 60, None, (), str(stage / "out")) == roots[1]
    for artifacts, output in (
        ((), str(tmp_path / "B/暂存/转换/61/out")),
        ((), str(tmp_path / "B/other/out")),
        ((str(tmp_path / "A/暂存/转换/60"),), str(stage / "out")),
        ((), None),
    ):
        with pytest.raises(JobInputError):
            locate_root(roots, 60, None, artifacts, output)
    with pytest.raises(JobInputError):
        locate_root(roots, 60, "a", (str(stage),), str(stage / "out"))
    with pytest.raises(JobInputError):
        locate_root(
            (roots[0], roots[1].model_copy(update={"path": tmp_path / "moved"})),
            60,
            "b",
            (str(stage),),
            str(stage / "out"),
        )
    with pytest.raises(JobInputError):
        locate_root(
            (roots[1], roots[1].model_copy(update={"name": "alias"})),
            60,
            None,
            (),
            str(stage / "out"),
        )


def test_submission_freezes_default_and_resubmission_recovers_legacy_b(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """提交省略根时立即固化 a；历史无参数的 B 实际产物在重提时固化 b，原记录不变。"""
    from accounts_support import AUDIT_CONTEXT, EXAMPLE_SECRET, NOW
    from argon2 import PasswordHasher
    from conversion_support import fake_converter, settings
    from datasets_execution_support import dataset_case

    from rdp.accounts.security import PasswordCodec
    from rdp.accounts.service import AccountService
    from rdp.accounts.types import Credentials, NewAccount, Role
    from rdp.audit.types import OPS_AUDIT_CONTEXT
    from rdp.infra.db.connection import session_scope
    from rdp.jobs.conversion.registration import register_conversion_jobs
    from rdp.jobs.models import JobRow
    from rdp.jobs.registry import production_registry
    from rdp.jobs.service import JobRequest, JobService

    files = fake_converter(tmp_path / "tool")
    roots = tuple(
        StorageRootConfig(name=name, path=tmp_path / name, writable=True, nfs_export=f"nas:/{name}")
        for name in ("a", "b")
    )
    registry = production_registry()
    register_conversion_jobs(registry, settings(files), roots, None)
    with dataset_case(tmp_path / "scan", fake_nav) as scan:
        scan.run()
        accounts = AccountService(
            scan.engine, PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
        )
        accounts.create_first_admin(
            NewAccount(Credentials("admin", EXAMPLE_SECRET), "管理员", Role.ADMINISTRATOR),
            now=NOW,
            audit=OPS_AUDIT_CONTEXT,
        )
        admin = accounts.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        service = JobService(accounts.engine, registry)
        request = JobRequest(admin.identity, NOW, AUDIT_CONTEXT)
        submitted = service.submit(
            request,
            "convert_mcap2lerobot",
            {
                "dataset_id": "dataset-35",
                "source_ids": ["src_01e0bc7e9cc8"],
                "robot_model": "Galaxea R1 Lite",
            },
        )
        assert submitted.parameters["output_root"] == "a"
        service.cancel(request, submitted.job_id)
        reordered = production_registry()
        register_conversion_jobs(reordered, settings(files), roots[::-1], None)
        service = JobService(accounts.engine, reordered)
        assert service.resubmit(request, submitted.job_id).parameters["output_root"] == "a"
        with session_scope(accounts.engine) as session:
            row = session.get(JobRow, submitted.job_id)
            assert row is not None and row.summary is not None
            row.parameters = {
                key: value for key, value in row.parameters.items() if key != "output_root"
            }
            row.artifacts = [str(tmp_path / "b/暂存/转换" / str(submitted.job_id))]
            row.summary = {**row.summary, "artifacts": row.artifacts}
        assert service.resubmit(request, submitted.job_id).parameters["output_root"] == "b"
        assert "output_root" not in service.get(request, submitted.job_id).parameters
